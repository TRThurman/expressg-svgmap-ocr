#!/usr/bin/env python3
"""Assemble final 502 svgmap data: detector output + human adjudication.
Recoveries are snapped to precise borders with the ray probe. py312 (cv2)."""
import os, re, json, glob, importlib.util
import cv2

SP = os.path.dirname(os.path.abspath(__file__))
for name in ("ocr_boxes", "gen_svgmap"):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SP, name + ".py"))
    globals()[name] = importlib.util.module_from_spec(spec); spec.loader.exec_module(globals()[name])

AIC = "aic_shell_based_wireframe"
DIR = f"{os.environ.get('WT', '.')}/schemas/resources/{AIC}"
CANDS = [AIC, "representation_schema", "support_resource_schema", "geometry_schema",
         "topology_schema", "geometric_model_schema", "measure_schema",
         "product_property_representation_schema"]

# page -> [(x,y) of detected boxes to DROP]  (attribute-label false positives,
# name->face fuzz, page-refs per AIC sibling convention, bogus geometry)
DROP = {
 1: [(176,28),(71,354),(398,605),(133,266),(0,591),(380,693),(210,766),(36,784),(128,786),(341,786),(221,787),(519,789)],
 2: [(274,8),(335,395),(25,440),(333,800),(135,554),(40,662)],   # pagerefs + 2 bad-geometry (re-probed below)
 3: [(291,57),(290,784)],
 4: [(321,22),(467,166),(192,462),(31,471),(215,210),(123,797)], # pagerefs + transformation FP + bogus plm
 5: [(124,197),(440,317),(562,794),(410,796)],
 6: [],
}
# page -> [(entity_name, express_target, seed_cx, seed_cy)] recoveries + re-probes
RECOVER = {
 2: [("trimming_select","express:geometry_schema.trimming_select",182,565),
     ("length_measure","express:measure_schema.length_measure",77,682)],
 3: [("length_measure","express:measure_schema.length_measure",247,520)],
 4: [("line","express:geometry_schema.line",515,490),
     ("positive_length_measure","express:measure_schema.positive_length_measure",130,670),
     ("positive_length_measure","express:measure_schema.positive_length_measure",130,712),
     ("length_measure","express:measure_schema.length_measure",160,747),
     ("positive_length_measure","express:measure_schema.positive_length_measure",130,777),
     ("positive_length_measure","express:measure_schema.positive_length_measure",130,812,40,70)],
 5: [("label","express:support_resource_schema.label",563,101),
     ("text","express:support_resource_schema.text",563,139),
     ("b_spline_curve","express:geometry_schema.b_spline_curve",120,470,200,90,25),
     ("quasi_uniform_curve","express:geometry_schema.quasi_uniform_curve",557,695),
     ("parameter_value","express:measure_schema.parameter_value",460,813),
     ("knot_type","express:geometry_schema.knot_type",581,813)],
 6: [("reversible_topology_item","express:topology_schema.reversible_topology_item",450,75),
     ("edge_curve","express:topology_schema.edge_curve",270,325),
     ("loop","express:topology_schema.loop",163,682)],
}
PAGE = re.compile(r'^(\d+)\s*,\s*\d+\s+')
SELF = re.compile(r'^\d+\s*,\s*\d+\s*\(')

def resolve_name(t):
    n = re.sub(r'^\((?:ABS|RT)\)\s*', '', t.strip(), flags=re.I).lstrip('*')
    n = n.lower().replace(' ', '_').replace('-', '_').strip('_|')
    hits = [s for s in CANDS if (c := gen_svgmap.cat(s)) and n in c]
    if hits: return f"express:{hits[0]}.{n}"
    best = None
    for s in CANDS:
        for e in (gen_svgmap.cat(s) or set()):
            dl = gen_svgmap.lev(n, e)
            if dl <= 2 and (best is None or dl < best[0]): best = (dl, s, e)
    return f"express:{best[1]}.{best[2]}" if best else None

def main():
    final = {}
    for n in range(1, 7):
        det = json.load(open(f"{SP}/sbw{n}.json"))
        img = cv2.imread(f"{DIR}/{AIC}expg{n}.png", cv2.IMREAD_GRAYSCALE)
        _, binv = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        drops = DROP.get(n, [])
        rows = []
        for b in det['boxes']:
            if b['kind'] == 'nobox': continue
            if any(abs(b['x']-dx) < 6 and abs(b['y']-dy) < 6 for dx, dy in drops): continue
            t = b['text']
            if SELF.match(t.strip()) or PAGE.match(t.strip()): continue
            target = resolve_name(t)
            if not target:
                print(f"p{n} UNRESOLVED kept-box {t!r} @({b['x']},{b['y']}) -- dropping"); continue
            rows.append({'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h'], 'target': target, 'src': t})
        for rec in RECOVER.get(n, []):
            name, target, cx, cy = rec[:4]
            up = rec[4] if len(rec) > 4 else 45
            side = rec[5] if len(rec) > 5 else 70
            mr = rec[6] if len(rec) > 6 else 5
            fake = {'x0': cx - 25, 'y0': cy - 9, 'x1': cx + 25, 'y1': cy + 9}
            fb = ocr_boxes.find_box(binv, fake, up=up, side=side, maxratio=mr)
            if not fb:
                print(f"p{n} RECOVERY FAILED {name} @({cx},{cy})"); continue
            kind, x, y, w, h = fb
            rows.append({'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h), 'target': target, 'src': f"recovered:{name}"})
        rows.sort(key=lambda r: (r['y'], r['x']))
        final[n] = rows
        print(f"page {n}: {len(rows)} entries")
    json.dump(final, open(f"{SP}/final_502.json", 'w'), indent=1)
    print("wrote final_502.json")

if __name__ == '__main__':
    main()
