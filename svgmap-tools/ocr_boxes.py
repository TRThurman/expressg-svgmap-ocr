#!/usr/bin/env python3
"""Text-anchored EXPRESS-G box detector (Group 3).

Full-page PaddleOCR gives text lines + positions; for each candidate label,
directed gap-tolerant ray search finds the enclosing box borders (works for
solid rects, dashed rects, and stadium ovals). Text with no enclosure =
attribute label / annotation -> skipped. Output JSON for adjudication.
Runs on python3.12 (cv2 + paddleocr).
"""
import sys, json, os
import numpy as np
import cv2

def ocr_page(img, scale=2):
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, lang='en')
    up = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    res = ocr.predict(cv2.cvtColor(up, cv2.COLOR_GRAY2BGR))
    lines = []
    for r in res:
        polys = r['rec_polys'] if 'rec_polys' in r else r['dt_polys']
        for txt, poly in zip(r['rec_texts'], polys):
            xs = [p[0] / scale for p in poly]; ys = [p[1] / scale for p in poly]
            lines.append({'text': txt, 'x0': min(xs), 'y0': min(ys),
                          'x1': max(xs), 'y1': max(ys)})
    return lines

def merge_lines(lines):
    """merge vertically stacked, horizontally overlapping lines (multi-line labels)"""
    lines = sorted(lines, key=lambda l: (l['y0'], l['x0']))
    merged = []
    for l in lines:
        hit = None
        for m in merged:
            xov = min(l['x1'], m['x1']) - max(l['x0'], m['x0'])
            if xov > 0.4 * min(l['x1'] - l['x0'], m['x1'] - m['x0']) and \
               0 <= l['y0'] - m['y1'] < 1.1 * (l['y1'] - l['y0']):
                hit = m; break
        if hit:
            hit['text'] += ' ' + l['text']
            hit['x0'] = min(hit['x0'], l['x0']); hit['x1'] = max(hit['x1'], l['x1'])
            hit['y1'] = l['y1']
        else:
            merged.append(dict(l))
    return merged

def find_box(binv, t, up=45, side=70, maxratio=5):
    """directed ray search for enclosing borders around text bbox t.
    returns (kind, x, y, w, h) or None"""
    H, W = binv.shape
    tx0, ty0, tx1, ty1 = int(t['x0']), int(t['y0']), int(t['x1']), int(t['y1'])
    span0, span1 = max(0, tx0 - 6), min(W, tx1 + 6)
    def row_cov(yy, x0, x1):
        if yy < 0 or yy >= H or x1 <= x0: return 0.0
        return float((binv[yy, x0:x1] > 0).mean())
    def col_cov(xx, y0, y1):
        if xx < 0 or xx >= W or y1 <= y0: return 0.0
        return float((binv[y0:y1, xx] > 0).mean())
    # nearest strong horizontal line above and below (dash-tolerant >=0.55)
    top = next((yy for yy in range(ty0 - 2, max(-1, ty0 - up), -1)
                if row_cov(yy, span0, span1) >= 0.55), None)
    bot = next((yy for yy in range(ty1 + 2, min(H, ty1 + up))
                if row_cov(yy, span0, span1) >= 0.55), None)
    if top is None or bot is None: return None
    iy0, iy1 = top + 3, bot - 2
    # verticals left/right between the horizontal borders
    left = next((xx for xx in range(tx0 - 2, max(-1, tx0 - side), -1)
                 if col_cov(xx, iy0, iy1) >= 0.5), None)
    right = next((xx for xx in range(tx1 + 2, min(W, tx1 + side))
                  if col_cov(xx, iy0, iy1) >= 0.5), None)
    if left is not None and right is not None:
        kind = 'rect'
        x, y, w, h = left, top, right - left + 1, bot - top + 1
    else:
        # stadium: extent = ink run of the top border row
        row = (binv[top, :] > 0).astype(np.uint8)
        # find run containing the text span center
        cxm = (tx0 + tx1) // 2
        if not row[cxm]:
            nz = np.nonzero(row[max(0, cxm - 30):cxm + 30])[0]
            if nz.size == 0: return None
            cxm = max(0, cxm - 30) + int(nz[0])
        l = cxm
        while l > 0 and row[l - 1]: l -= 1
        r = cxm
        while r < W - 1 and row[r + 1]: r += 1
        # arc extends ~h/2 beyond the straight run on each side
        arc = (bot - top) // 2
        kind = 'oval'
        x, y, w, h = max(0, l - arc), top, min(W - 1, r + arc) - max(0, l - arc) + 1, bot - top + 1
    # sanity: box must not dwarf the text
    if h > maxratio * (ty1 - ty0 + 2) or w > W * 0.95: return None
    return kind, x, y, w, h

def main():
    img_path = sys.argv[1]
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    _, binv = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    lines = merge_lines(ocr_page(img))
    out = []
    for t in lines:
        fb = find_box(binv, t)
        rec = {'text': t['text'],
               'tx': int(t['x0']), 'ty': int(t['y0'])}
        if fb:
            kind, x, y, w, h = fb
            rec.update({'kind': kind, 'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)})
        else:
            rec['kind'] = 'nobox'
        out.append(rec)
    # dedupe: same box found from multiple text lines -> merge texts
    boxes = {}
    for r in out:
        if r['kind'] == 'nobox':
            boxes[('nobox', r['tx'], r['ty'])] = r; continue
        key = (r['x'] // 4, r['y'] // 4, r['w'] // 4, r['h'] // 4)
        if key in boxes:
            boxes[key]['text'] += ' ' + r['text']
        else:
            boxes[key] = r
    final = sorted(boxes.values(), key=lambda b: (b.get('y', b['ty']), b.get('x', b['tx'])))
    print(json.dumps({'image': os.path.basename(img_path), 'boxes': final}, indent=1))

if __name__ == '__main__':
    main()
