#!/usr/bin/env python3
"""502 adjudication table: resolve detected box texts to express targets.
Reads sbw{N}.json from the detector; prints per-page proposal + flags."""
import os, re, json, glob, importlib.util

SP = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g", os.path.join(SP, "gen_svgmap.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

AIC = "aic_shell_based_wireframe"
# declaring-schema candidates (sibling aic_edge_based_wireframe precedent order)
CANDS = [AIC, "representation_schema", "support_resource_schema", "geometry_schema",
         "topology_schema", "geometric_model_schema", "measure_schema",
         "product_property_representation_schema"]
PAGE = re.compile(r'^(\d+)\s*,\s*\d+\s+(.*)$')
SELF = re.compile(r'^\d+\s*,\s*\d+\s*\(')

def norm(text):
    t = text.strip()
    t = re.sub(r'^\((?:ABS|RT)\)\s*', '', t, flags=re.I)
    t = t.lstrip('*')
    # OCR artifacts: spaces inside identifiers -> underscores if close match later
    return t

def resolve_name(name):
    n = name.lower().replace(' ', '_').replace('-', '_')
    hits = [s for s in CANDS if (c := g.cat(s)) and n in c]
    if hits: return ('ok' if len(hits) == 1 else 'COLLISION', hits, n)
    # OCR fuzz: try common substitutions then Levenshtein<=2 vs union catalog
    best = None
    for s in CANDS:
        c = g.cat(s) or set()
        for e in c:
            dl = g.lev(n, e)
            if dl <= 2 and (best is None or dl < best[0]):
                best = (dl, s, e)
    if best: return ('fuzzy', [best[1]], best[2])
    return ('unresolved', [], n)

def main():
    for n in range(1, 7):
        p = os.path.join(SP, f"sbw{n}.json")
        if not os.path.exists(p): continue
        d = json.load(open(p))
        print(f"===== page {n} ({d['image']}) =====")
        rows = []
        for b in d['boxes']:
            if b['kind'] == 'nobox': continue
            t = norm(b['text'])
            if SELF.match(t):
                print(f"  [self-anchor] {t!r} -- skip"); continue
            pm = PAGE.match(t)
            if pm:
                rows.append((b, 'pageref', f"{AIC}_expg{pm.group(1)}", t)); continue
            verdict, schemas, name = resolve_name(t)
            if verdict in ('ok', 'fuzzy'):
                rows.append((b, verdict, f"express:{schemas[0]}.{name}", t))
            else:
                print(f"  [DROP {verdict}] {t!r} @({b['x']},{b['y']}) {b['w']}x{b['h']} {b['kind']}")
        for i, (b, verdict, target, raw) in enumerate(rows, 1):
            mark = '' if verdict == 'ok' else f'   <<< {verdict.upper()} from {raw!r}'
            print(f"  {i:>2} ({b['x']:>3},{b['y']:>3}) {b['w']:>3}x{b['h']:<3} {b['kind']:<5} {target}{mark}")
        print()

if __name__ == '__main__':
    main()
