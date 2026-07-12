#!/usr/bin/env python3
"""Group 1 svgmap generator.

For schemas whose EXPRESS-G SVGs already contain numbered <a href="N"><rect/></a>
anchors, resolve each anchor to its EXPRESS target by geometric containment of
SVG text labels, validate against catalogs parsed from the .exp files, and emit
svgmap entry lists. Report-only unless --apply.
"""
import os, re, sys, glob, unicodedata
import xml.etree.ElementTree as ET

ROOT = os.environ.get("WT", ".")
RES = os.path.join(ROOT, "schemas/resources")
BUILTINS = {"BOOLEAN","STRING","NUMBER","INTEGER","REAL","LOGICAL","BINARY","GENERIC","AGGREGATE"}

SCHEMAS = {
    "mathematical_functions_schema": "iso-10303-50",
    "solid_shape_element_schema": "iso-10303-111",
    "iso13584_expressions_schema": "iso-13584-20",
    "iso13584_generic_expressions_schema": "iso-13584-20",
}

DECL = re.compile(r'^\s*(?:ENTITY|TYPE)\s+([a-zA-Z0-9_]+)\b', re.M)

def catalog(schema):
    """set of ENTITY/TYPE names declared in schema's .exp"""
    f = os.path.join(RES, schema, f"{schema}.exp")
    if not os.path.exists(f): return None
    txt = open(f, errors="replace").read()
    # strip EXPRESS comments (they contain doc text w/ ENTITY prose)
    txt = re.sub(r'\(\*.*?\*\)', '', txt, flags=re.S)
    return set(n.lower() for n in DECL.findall(txt))

ALL_SCHEMA_NAMES = set(os.path.basename(d) for d in glob.glob(RES + "/*") if os.path.isdir(d))
CATS = {}
def cat(s):
    if s not in CATS: CATS[s] = catalog(s)
    return CATS[s]

def lev(a, b, cap=3):
    if abs(len(a)-len(b)) > cap: return cap+1
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j]+1, cur[j-1]+1, prev[j-1]+(ca!=cb)))
        prev = cur
    return prev[-1]

def strip_ns(t): return t.split('}')[-1]

ATTR = re.compile(r'([\w:.-]+)\s*=\s*("[^"]*")')

def dedupe_attrs(svgtext):
    """in-memory fix for duplicate attributes (a source defect) so ET can parse;
    keeps the FIRST occurrence of each attribute name per tag."""
    def fix(m):
        seen = set(); out = []
        for name, val in ATTR.findall(m.group(2)):
            if name in seen: continue
            seen.add(name); out.append(f'{name}={val}')
        return '<' + m.group(1) + (' ' + ' '.join(out) if out else '') + m.group(3) + '>'
    return re.sub(r'<([a-zA-Z][\w:-]*)((?:\s+[\w:.-]+\s*=\s*"[^"]*")*)\s*(/?)>', fix, svgtext)

def parse_svg(path):
    """return (anchors=[(n,x,y,w,h)], labels=[(x,y,text)])"""
    text = open(path, encoding='utf-8', errors='replace').read()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = ET.fromstring(dedupe_attrs(text))
    anchors, labels = [], []
    def walk(el):
        tag = strip_ns(el.tag)
        if tag == 'a':
            href = el.get('href') or el.get('{http://www.w3.org/1999/xlink}href')
            if href and href.isdigit():
                for c in el:
                    if strip_ns(c.tag) == 'rect':
                        anchors.append((int(href), float(c.get('x',0)), float(c.get('y',0)),
                                        float(c.get('width',0)), float(c.get('height',0))))
        elif tag == 'text':
            # collect per-fragment coords: tspans with x/y, else text's own x/y
            base_x, base_y = el.get('x'), el.get('y')
            frags = []
            own = (el.text or '').strip()
            if own and base_x and base_y:
                frags.append((float(base_x), float(base_y), own))
            for ts in el.iter():
                if strip_ns(ts.tag) == 'tspan':
                    t = ''.join(ts.itertext()).strip()
                    tx, ty = ts.get('x', base_x), ts.get('y', base_y)
                    if t and tx and ty:
                        frags.append((float(tx), float(ty), t))
            labels.extend(frags)
        for c in el:
            if strip_ns(c.tag) != 'text':
                walk(c)
            else:
                walk(c)
    walk(root)
    return anchors, labels

PAGEREF = re.compile(r'^\d+\s*,\s*\d+')

def join_frags(frags):
    """join multi-line label fragments per wrap rules"""
    out = ""
    for f in frags:
        f = f.strip()
        if not f: continue
        if f == '(ABS)' or f == '(RT)':   # graphical markers, not part of the name
            continue
        if not out:
            out = f
        elif out.endswith('-'):
            out = out[:-1] + f            # hyphen soft-wrap
        elif out.endswith('_') or out.endswith('.'):
            out = out + f                 # identifier wrap
        else:
            out = out + ' ' + f           # keep space; likely flagged later
    return out

def resolve(schema, raw):
    """raw joined label -> (verdict, target) where verdict in ok/fuzzy/builtin/pageref/schema/unresolved"""
    name = raw.strip()
    # graphical markers may share a fragment with the name: "(ABS) maths_space"
    name = re.sub(r'^\((?:ABS|RT)\)\s*', '', name, flags=re.I).strip()
    if not name: return ('empty', None)
    if PAGEREF.match(name): return ('pageref', name)
    if name.upper() in BUILTINS: return ('builtin', name)
    n = name.lower()
    if '.' in n:
        s, e = n.split('.', 1)
        c = cat(s)
        if c is not None and e in c: return ('ok', f'{s}.{e}')
        # fuzzy on both sides
        if c is None:
            best = min(ALL_SCHEMA_NAMES, key=lambda x: lev(s, x))
            if lev(s, best) <= 2:
                c2 = cat(best)
                if c2 and e in c2: return ('fuzzy', f'{best}.{e}')
        else:
            best = min(c, key=lambda x: lev(e, x)) if c else None
            if best and lev(e, best) <= 2: return ('fuzzy', f'{s}.{best}')
        return ('unresolved', n)
    c = cat(schema)
    if n in c: return ('ok', f'{schema}.{n}')
    if n in ALL_SCHEMA_NAMES: return ('schema', n)
    best = min(c, key=lambda x: lev(n, x)) if c else None
    if best and lev(n, best) <= 2: return ('fuzzy', f'{schema}.{best}')
    # schema-name fuzzy (e.g. 1SO13584 -> iso13584 typo in qualified-less context)
    bs = min(ALL_SCHEMA_NAMES, key=lambda x: lev(n, x))
    if lev(n, bs) <= 2: return ('schema-fuzzy', bs)
    return ('unresolved', n)

def group_labels_into_boxes(anchors, labels):
    """for each anchor rect, ordered fragments inside it"""
    out = {}
    for n, x, y, w, h in anchors:
        inside = sorted(set((ty, tx, t) for tx, ty, t in labels
                        if x - 1 <= tx <= x + w + 1 and y - 1 <= ty <= y + h + 1))
        out[n] = [t for _,_,t in inside]
    return out

# Manual adjudications (image basename, anchor) -> express target.
# Each is a verified diagram defect or wrap artifact.
OVERRIDES = {
    # digit/letter typos in schema qualifier (1SO/IS0/missing 's')
    ("iso13584_expressions_schema_expg1.svg", 1): "iso13584_generic_expressions_schema.generic_expression",
    ("iso13584_expressions_schema_expg2.svg", 1): "iso13584_generic_expressions_schema.generic_variable",
    ("iso13584_expressions_schema_expg3.svg", 7): "iso13584_generic_expressions_schema.unary_generic_expression",
    ("iso13584_expressions_schema_expg5.svg", 8): "iso13584_generic_expressions_schema.generic_expression",
    # diagram abbreviation: gen -> generic
    ("iso13584_generic_expressions_schema_expg1.svg", 5): "iso13584_generic_expressions_schema.multiple_arity_generic_expression",
    # diagram label typo: box above maths_string_variable whose declared
    # supertype is string_variable (mathematical_functions_schema.exp:484)
    ("mathematical_functions_schemaexpg2.svg", 9): "iso13584_expressions_schema.string_variable",
    # line-wrap artifacts (space instead of underscore)
    ("mathematical_functions_schemaexpg7.svg", 15): "mathematical_functions_schema.strict_triangular_matrix",
    ("solid_shape_element_schemaexpg10.svg", 1): "geometric_model_schema.revolved_face_solid",
    ("solid_shape_element_schemaexpg5.svg", 4): "solid_shape_element_schema.solid_with_stepped_round_hole",
    # diagram typo: symmetry_ -> symmetric_
    ("mathematical_functions_schemaexpg7.svg", 22): "mathematical_functions_schema.symmetric_banded_matrix",
    # diagram typo: edge_curve is declared in topology_schema, not geometry_schema
    ("solid_shape_element_schemaexpg2.svg", 9): "topology_schema.edge_curve",
}

# Anchors placed over EXPRESS builtin-type boxes: no linkable target exists;
# delete the anchors from the SVGs (corpus invariant: anchor-set == entry-set).
DELETE_ANCHORS = {
    "iso13584_expressions_schema_expg3.svg": [1],
    "iso13584_expressions_schema_expg7.svg": [1, 3, 11, 15, 16],
}

def main():
    report = []
    entries_per_image = {}   # (schema, svgbasename) -> [(n, target-string or None, verdict, raw)]
    for schema in SCHEMAS:
        svgs = sorted(glob.glob(f"{RES}/{schema}/**/*expg*.svg", recursive=True),
                      key=lambda p: (len(p), p))
        for svg in svgs:
            anchors, labels = parse_svg(svg)
            if not anchors: continue
            boxes = group_labels_into_boxes(anchors, labels)
            rows = []
            for n in sorted(boxes):
                raw = join_frags(boxes[n])
                verdict, target = resolve(schema, raw)
                rows.append((n, verdict, target, raw))
            entries_per_image[(schema, os.path.basename(svg))] = rows
    # apply overrides / deletions
    final = {}     # (schema, img) -> [(n, target)]
    problems = []
    tally = {}
    for (schema, img), rows in sorted(entries_per_image.items()):
        out = []
        dels = set(DELETE_ANCHORS.get(img, []))
        for n, verdict, target, raw in rows:
            if n in dels:
                tally['deleted'] = tally.get('deleted', 0) + 1
                continue
            if (img, n) in OVERRIDES:
                out.append((n, OVERRIDES[(img, n)]))
                tally['override'] = tally.get('override', 0) + 1
            elif verdict in ('ok', 'fuzzy'):
                # fuzzy without an override entry is NOT acceptable silently
                if verdict == 'fuzzy':
                    problems.append((schema, img, n, 'fuzzy-without-override', raw))
                out.append((n, target))
                tally[verdict] = tally.get(verdict, 0) + 1
            else:
                problems.append((schema, img, n, verdict, raw))
                tally[verdict] = tally.get(verdict, 0) + 1
        final[(schema, img)] = out
    print("TALLY:", dict(sorted(tally.items())))
    print(f"total anchors: {sum(tally.values())}")
    if problems:
        print("\nPROBLEMS (must be empty before --apply):")
        for p in problems: print("  ", p)
        if '--apply' in sys.argv: sys.exit("refusing to apply with problems")
    if '--apply' not in sys.argv:
        for (schema, img), out in final.items():
            print(f"\n== {schema} / {img} ==")
            for n, t in out: print(f"  * <<express:{t}>>; {n}")
        return

    # ---- APPLY ----
    # 1) delete builtin anchors from SVGs (raw-text surgery; leaves the source
    #    duplicate-attribute defect untouched)
    for img, ns in DELETE_ANCHORS.items():
        hits = glob.glob(f"{RES}/**/{img}", recursive=True)
        assert len(hits) == 1, (img, hits)
        raw = open(hits[0], encoding='utf-8', errors='replace').read()
        for n in ns:
            pat = re.compile(r'<a href="%d">.*?</a>\s*' % n, re.S)
            raw, cnt = pat.subn('', raw)
            assert cnt <= 1, (img, n, cnt)
            if cnt == 0:
                print(f"  skip (already removed): {img} anchor {n}")
        open(hits[0], 'w', encoding='utf-8').write(raw)
        print(f"svg-edit: {img}: removed anchors {ns}")

    # 2) insert svgmap entries into the .exp blocks
    for schema in SCHEMAS:
        exp = os.path.join(RES, schema, f"{schema}.exp")
        txt = open(exp, encoding='utf-8', errors='replace').read()
        for (s, img), out in final.items():
            if s != schema or not out: continue
            entries = '\n'.join(f'* <<express:{t}>>; {n}' for n, t in sorted(out))
            # idempotency: skip if this image's block already carries entries
            already = re.search(
                r'image::[^\n\[]*' + re.escape(img) + r'\[\]\n+\* <<express:', txt)
            if already:
                print(f"  skip (already applied): {img}")
                continue
            # block: [[anchor]] (maybe [.svgmap]) ==== image::...img[] (blank*) ====
            pat = re.compile(
                r'(\[\[[^\]]+\]\]\n)(\[\.svgmap\]\n)?(====\nimage::[^\n\[]*' + re.escape(img) + r'\[\]\n)\n*(====)')
            def repl(m):
                return m.group(1) + '[.svgmap]\n' + m.group(3) + '\n' + entries + '\n' + m.group(4)
            txt, cnt = pat.subn(repl, txt)
            assert cnt == 1, (schema, img, cnt)
        open(exp, 'w', encoding='utf-8').write(txt)
        print(f"exp-edit: {schema}.exp updated")

if __name__ == '__main__':
    main()
