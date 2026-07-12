#!/usr/bin/env python3
"""Part 112 (procedural_sketch_schema) svgmap generator: extract boxes+labels
from the vector SVGs, resolve targets, inject numeric <a href="N"> anchors,
and emit svgmap entries. Report-only unless --apply.

Box model (verified on expg1/expg14):
  - box geometry = white-fill paths (fill:#ffffff ... stroke:none), positive-y
    root-g space; the y-flipped stroked copies are ignored.
  - labels = <text transform="matrix(a,0,0,1,TX,TY)"> tspans; abs = (a*x+TX, y+TY)
  - stadium boxes starting with a "p,r" tspan are outgoing page-refs ->
    <<procedural_sketch_schema_expgP>> (geometry_schema precedent)
  - single-tspan "p,r(refs)" boxes are the page's self-anchor -> NOT anchored
  - leading "(ABS)" and "*" markers are stripped from names
"""
import os, re, sys, glob, importlib.util

SP = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g", os.path.join(SP, "gen_svgmap.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

SCHEMA = "procedural_sketch_schema"
RES = g.RES
DIR = f"{RES}/{SCHEMA}/images"
EXP = f"{RES}/{SCHEMA}/{SCHEMA}.exp"

PAGEPAIR = re.compile(r'^(\d+),\d+$')
SELFANCH = re.compile(r'^\d+,\d+\s*\(')

ANCHOR_STYLE = ("opacity: 0; fill:#2180ff;fill-opacity:0.3;stroke:#000000;"
                "stroke-width:0;stroke-linecap:square;stroke-miterlimit:10.1;"
                "stroke-dasharray:none")

def path_bbox(d):
    """evaluate a path d-string (M,m,L,l,H,h,V,v,C,c,Z) -> bbox"""
    toks = re.findall(r'([MmLlHhVvCcZz])|(-?\d*\.?\d+(?:e-?\d+)?)', d)
    nums, cmds = [], []
    seq = []
    for c, n in toks:
        if c: seq.append(('cmd', c))
        else: seq.append(('num', float(n)))
    xs, ys = [], []
    cx = cy = 0.0
    i = 0; cmd = None
    def take(k):
        nonlocal i
        out = []
        for _ in range(k):
            assert i < len(seq) and seq[i][0] == 'num', d[:60]
            out.append(seq[i][1]); i += 1
        return out
    while i < len(seq):
        if seq[i][0] == 'cmd':
            cmd = seq[i][1]; i += 1
            if cmd in 'Zz': continue
        if cmd in 'Mm' or cmd in 'Ll':
            x, y = take(2)
            if cmd in 'ml': cx += x; cy += y
            else: cx, cy = x, y
            if cmd == 'M': cmd = 'L'
            if cmd == 'm': cmd = 'l'
        elif cmd in 'Hh':
            (x,) = take(1); cx = cx + x if cmd == 'h' else x
        elif cmd in 'Vv':
            (y,) = take(1); cy = cy + y if cmd == 'v' else y
        elif cmd in 'Cc':
            x1, y1, x2, y2, x, y = take(6)
            if cmd == 'c':
                xs += [cx + x1, cx + x2]; ys += [cy + y1, cy + y2]
                cx += x; cy += y
            else:
                xs += [x1, x2]; ys += [y1, y2]; cx, cy = x, y
        else:
            raise ValueError(f"cmd {cmd} in {d[:60]}")
        xs.append(cx); ys.append(cy)
    return min(xs), min(ys), max(xs), max(ys)

def parse_112(svgpath):
    """-> (root_matrix(a,f), boxes=[bbox], labels=[(x,y,text)])"""
    h = open(svgpath, encoding='utf-8', errors='replace').read()
    m = re.search(r'<g\b[^>]*?transform="matrix\(([^)]+)\)"', h, re.S)
    assert m, svgpath
    mv = [float(x) for x in m.group(1).split(',')]
    assert len(mv) == 6 and mv[1] == 0 and mv[2] == 0, (svgpath, mv)
    ra, rd, re_, rf = mv[0], mv[3], mv[4], mv[5]
    boxes = []
    for pm in re.finditer(r'<path[^>]*style="fill:#ffffff[^"]*stroke:none"[^>]*d="([^"]+)"', h):
        boxes.append(path_bbox(pm.group(1)))
    # also attribute order d= before style=
    for pm in re.finditer(r'<path[^>]*d="([^"]+)"[^>]*style="fill:#ffffff[^"]*stroke:none"', h):
        boxes.append(path_bbox(pm.group(1)))
    labels = []
    for tm in re.finditer(r'<text\b[^>]*?transform="matrix\(([^)]+)\)"[^>]*>(.*?)</text>', h, re.S):
        tv = [float(x) for x in tm.group(1).split(',')]
        assert len(tv) == 6 and tv[1] == 0 and tv[2] == 0, (svgpath, tv)
        a, d, tx, ty, body = tv[0], tv[3], tv[4], tv[5], tm.group(2)
        for sm in re.finditer(r'<tspan[^>]*\bx="([\d.\s+-eE]+)"[^>]*\by="([\d.eE+-]+)"[^>]*>([^<]*)</tspan>', body) or []:
            x0 = float(sm.group(1).split()[0]); y0 = float(sm.group(2))
            txt = sm.group(3).strip()
            if txt: labels.append((a * x0 + tx, d * y0 + ty, txt))
        for sm in re.finditer(r'<tspan[^>]*\by="([\d.eE+-]+)"[^>]*\bx="([\d.\s+-eE]+)"[^>]*>([^<]*)</tspan>', body):
            x0 = float(sm.group(2).split()[0]); y0 = float(sm.group(1))
            txt = sm.group(3).strip()
            if txt: labels.append((a * x0 + tx, d * y0 + ty, txt))
    # dedupe (two regex passes may double-collect)
    labels = sorted(set(labels), key=lambda t: (t[1], t[0]))
    boxes = sorted(set(boxes), key=lambda b: (b[1], b[0]))
    return (ra, rd, re_, rf), boxes, labels

def classify_box(frags):
    """frags = ordered label strings inside one box -> (kind, value)
       kind: entity | pageref | selfanchor | empty"""
    if not frags: return ('empty', None)
    if len(frags) == 1 and SELFANCH.match(frags[0]): return ('selfanchor', None)
    page = None
    rest = []
    for i, f in enumerate(frags):
        f = f.strip()
        pm = PAGEPAIR.match(f)
        if pm and i == 0:
            page = int(pm.group(1)); continue
        if f == '(ABS)': continue
        f = f.lstrip('*')
        rest.append(f)
    name = g.join_frags(rest)
    if page is not None and not name:
        return ('selfanchor', None)
    if page is not None:
        return ('pageref', page)
    if not name: return ('empty', None)
    return ('entity', name)

def main():
    apply = '--apply' in sys.argv
    all_entries = {}     # img -> [(n, target)]
    anchors_out = {}     # img -> [(n, x, y, w, h)]  viewport coords
    problems = []
    exp_txt = open(EXP, errors='replace').read()
    have_page_anchor = set(int(x) for x in re.findall(r'\[\[' + SCHEMA + r'_expg(\d+)\]\]', exp_txt))
    for svg in sorted(glob.glob(f"{DIR}/*expg*.svg"), key=lambda p: (len(p), p)):
        img = os.path.basename(svg)
        (ra, rd, rex, rf), boxes, labels = parse_112(svg)
        rows = []
        used = set()
        for bb in boxes:
            x0, y0, x1, y1 = bb
            inside = [(y, x, t) for (x, y, t) in labels if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1]
            frags = [t for _, _, t in sorted(inside)]
            kind, val = classify_box(frags)
            if kind in ('selfanchor', 'empty'): continue
            if kind == 'pageref':
                if val not in have_page_anchor:
                    problems.append((img, f'pageref expg{val} has no [[anchor]] in exp')); continue
                target = f'{SCHEMA}_expg{val}'   # non-express page target
            else:
                verdict, tgt = g.resolve(SCHEMA, val)
                if verdict == 'builtin':
                    continue   # EXPRESS builtin-type box: no linkable target, no anchor
                if verdict not in ('ok',):
                    problems.append((img, f'{verdict}: {val!r}')); continue
                target = f'express:{tgt}'
            rows.append((bb, target))
        # number in reading order
        rows.sort(key=lambda r: (r[0][1], r[0][0]))
        ent = []; anc = []
        for n, (bb, target) in enumerate(rows, 1):
            x0, y0, x1, y1 = bb
            # viewport coords via root matrix
            vx, vy = ra * x0 + rex, rd * y0 + rf
            vw, vh = ra * (x1 - x0), rd * (y1 - y0)
            ent.append((n, target))
            anc.append((n, round(vx, 2), round(vy, 2), round(vw, 2), round(vh, 2)))
        all_entries[img] = ent
        anchors_out[img] = anc
    # report
    tot = sum(len(v) for v in all_entries.values())
    print(f"images: {len(all_entries)}   boxes anchored: {tot}   problems: {len(problems)}")
    for img, p in problems: print(f"  PROBLEM {img}: {p}")
    if not apply:
        for img in sorted(all_entries, key=lambda p: (len(p), p)):
            print(f"\n== {img} ==")
            for n, t in all_entries[img]:
                print(f"  * <<{t}>>; {n}")
        return
    if problems:
        sys.exit("refusing to apply with problems")
    # inject anchors into SVGs
    for svg in sorted(glob.glob(f"{DIR}/*expg*.svg")):
        img = os.path.basename(svg)
        anc = anchors_out.get(img, [])
        if not anc: continue
        raw = open(svg, encoding='utf-8', errors='replace').read()
        if '<a href=' in raw:
            print(f"  skip (anchors exist): {img}"); continue
        frag = '\n'.join(
            f'<a href="{n}">\n  <rect onmouseout="this.style.opacity=0" '
            f'onmouseover="this.style.opacity=1"\n   style="{ANCHOR_STYLE}"\n'
            f'   x="{x}" y="{y}" width="{w}" height="{h}" ry="0" />\n</a>'
            for n, x, y, w, h in anc)
        raw = raw.replace('</svg>', frag + '\n</svg>')
        open(svg, 'w', encoding='utf-8').write(raw)
        print(f"svg-edit: {img}: injected {len(anc)} anchors")
    # insert entries into .exp
    txt = open(EXP, encoding='utf-8', errors='replace').read()
    for img, ent in all_entries.items():
        if not ent: continue
        entries = '\n'.join(
            (f'* <<{t}>>; {n}' if not t.startswith('express:') else f'* <<{t}>>; {n}')
            for n, t in ent)
        if re.search(r'image::[^\n\[]*' + re.escape(img) + r'\[\]\n+\* <<', txt):
            print(f"  skip (entries exist): {img}"); continue
        pat = re.compile(r'(\[\[[^\]]+\]\]\n)(\[\.svgmap\]\n)?(====\nimage::[^\n\[]*' + re.escape(img) + r'\[\]\n)\n*(====)')
        def repl(m):
            return m.group(1) + '[.svgmap]\n' + m.group(3) + '\n' + entries + '\n' + m.group(4)
        txt, cnt = pat.subn(repl, txt)
        assert cnt == 1, (img, cnt)
    open(EXP, 'w', encoding='utf-8').write(txt)
    print(f"exp-edit: {SCHEMA}.exp updated")

if __name__ == '__main__':
    main()
