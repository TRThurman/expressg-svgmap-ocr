#!/usr/bin/env python3
"""Assemble part-49 svgmap data (Group 3 raster path).

Every box was transcribed by eye from the 2x renders (p49_*.png); detector
JSON was only used to cross-check geometry. Each entry below carries an
INTERIOR seed rect (transcribed box inset ~12px, containing all label text)
so the border probe starts outside the text block -- underscore-heavy labels
defeat small center seeds. Borders snapped with ocr_boxes.find_box.
Writes final_49.json (render px, 2x) + QA overlay PNGs. py312 (cv2)."""
import os, json, importlib.util
import cv2

SP = os.path.dirname(os.path.abspath(__file__))
for name in ("ocr_boxes", "gen_svgmap"):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SP, name + ".py"))
    globals()[name] = importlib.util.module_from_spec(spec); spec.loader.exec_module(globals()[name])

# (express_target, x0, y0, x1, y1) -- interior seed rect, render px (2x)
BOXES = {
 "method_definition_schema": [
  ("express:effectivity_schema.effectivity", 355, 28, 585, 68),
  ("express:process_property_schema.product_definition_process", 1060, 137, 1305, 210),
  ("express:process_or_process_relationship_effectivity", 350, 167, 593, 231),
  ("express:process_property_schema.property_process", 1060, 257, 1300, 328),
  ("express:action_schema.action_relationship", 277, 309, 515, 356),
  ("express:context_dependent_action_relationship", 715, 308, 955, 360),
  ("express:action_schema.action_method_relationship", 360, 447, 570, 521),
  ("express:context_dependent_action_method_relationship", 770, 474, 1012, 548),
  ("express:relationship_condition", 925, 595, 1170, 645),
  ("express:concurrent_action_method", 305, 609, 478, 661),
  ("express:serial_action_method", 503, 611, 665, 664),
  ("express:sequential_method", 481, 761, 607, 812),
  ("express:measure_schema.count_measure", 790, 774, 985, 820),
  ("express:action_schema.action_method", 500, 864, 690, 920),
  ("express:action_method_to_select_from", 596, 995, 808, 1060),
  ("express:measure_schema.count_measure", 1060, 1008, 1280, 1052),
  ("express:action_method_with_associated_documents", 525, 1118, 782, 1186),
  ("express:document_schema.document", 1113, 1124, 1320, 1180),
  ("express:action_method_with_associated_documents_constrained", 471, 1288, 748, 1389),
  ("express:document_schema.document_usage_constraint", 1116, 1310, 1379, 1389),
 ],
 "process_property_schema": [
  ("express:product_property_definition_schema.shape_definition", 833, 38, 1050, 115),
  ("express:action_schema.action_relationship", 383, 136, 597, 170),
  ("express:action_schema.action_method_relationship", 693, 168, 865, 245),
  ("express:product_property_definition_schema.property_definition", 908, 161, 1132, 240),
  ("express:property_or_shape_select", 1200, 142, 1337, 180),
  ("express:replacement_relationship", 429, 262, 559, 295),
  ("express:action_schema.action_method", 693, 312, 870, 350),
  ("express:process_property_association", 992, 332, 1097, 389),
  ("express:characterized_action_definition", 445, 362, 622, 400),
  ("express:action_schema.action", 695, 400, 870, 440),
  ("express:action_property", 518, 477, 605, 520),
  ("express:property_process", 833, 502, 1005, 538),
  ("express:product_definition_process", 788, 575, 884, 640),
  ("express:action_property_relationship", 540, 608, 703, 648),
  ("express:action_resource_requirement_relationship", 475, 722, 710, 760),
  ("express:process_product_association", 933, 742, 1033, 803),
  ("express:action_resource_requirement", 528, 870, 652, 953),
  ("express:product_property_definition_schema.characterized_product_definition", 1000, 873, 1235, 982),
  ("express:resource_requirement_type", 450, 1047, 577, 1110),
  ("express:requirement_for_action_resource", 647, 1041, 820, 1080),
  ("express:characterized_resource_definition", 987, 1025, 1192, 1065),
  ("express:action_schema.action_resource", 645, 1152, 825, 1215),
  ("express:resource_property", 1101, 1152, 1194, 1185),
  ("express:resource_requirement_type_relationship", 333, 1225, 519, 1298),
  ("express:action_schema.action_resource_relationship", 645, 1252, 833, 1326),
  ("express:resource_property_relationship", 998, 1297, 1202, 1328),
 ],
 "process_property_representation_schema": [
  ("express:process_property_schema.action_property", 333, 32, 713, 101),
  ("express:process_property_schema.resource_property", 920, 60, 1305, 130),
  ("express:process_property_representation_schema.action_property_representation", 405, 207, 565, 288),
  ("express:process_property_representation_schema.resource_property_representation", 1022, 215, 1228, 319),
  ("express:representation_schema.representation", 693, 620, 1075, 688),
 ],
}

def oval_lr(binv, seed, top, bot):
    """true left/right extremes of a wobbly scanned stadium: horizontal ray
    scan from the seed edges over the middle band; extreme hit wins."""
    H, W = binv.shape
    h = bot - top
    band = range(top + h // 4, bot - h // 4)
    lxs, rxs = [], []
    for r in band:
        row = binv[r]
        seg = row[max(0, seed['x0'] - 70):seed['x0'] + 1]
        nz = seg.nonzero()[0]
        if nz.size: lxs.append(max(0, seed['x0'] - 70) + int(nz[-1]))  # nearest ink leftward
        seg = row[seed['x1']:min(W, seed['x1'] + 70)]
        nz = seg.nonzero()[0]
        if nz.size: rxs.append(seed['x1'] + int(nz[0]))
    if not lxs or not rxs: return None
    return min(lxs), max(rxs)

def main():
    final = {}
    for schema, rows_in in BOXES.items():
        img = cv2.imread(f"{SP}/p49_{schema}.png", cv2.IMREAD_GRAYSCALE)
        _, binv = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        rows = []
        for target, x0, y0, x1, y1 in rows_in:
            # local (unqualified) names -> express:<this schema>.<name>
            if '.' not in target:
                target = f"express:{schema}.{target[len('express:'):]}"
            fake = {'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1}
            fb = ocr_boxes.find_box(binv, fake, up=25, side=35, maxratio=12)
            if not fb:
                print(f"{schema}: PROBE FAILED {target} seed=({x0},{y0},{x1},{y1})"); continue
            kind, x, y, w, h = fb
            if kind == 'oval':
                lr = oval_lr(binv, fake, int(y), int(y) + int(h) - 1)
                if lr: x, w = lr[0], lr[1] - lr[0] + 1
            rows.append({'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
                         'kind': kind, 'target': target})
        rows.sort(key=lambda r: (r['y'], r['x']))
        final[schema] = rows
        print(f"{schema}: {len(rows)}/{len(rows_in)} boxes")
        # QA overlay
        vis = cv2.imread(f"{SP}/p49_{schema}.png")
        for i, r in enumerate(rows, 1):
            cv2.rectangle(vis, (r['x'], r['y']), (r['x']+r['w'], r['y']+r['h']), (255, 0, 0), 3)
            cv2.putText(vis, str(i), (r['x']+6, r['y']+30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imwrite(f"{SP}/qa_49_{schema}.png", vis)
    json.dump(final, open(f"{SP}/final_49.json", 'w'), indent=1)
    print("wrote final_49.json + qa overlays")

if __name__ == '__main__':
    main()
