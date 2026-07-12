#!/usr/bin/env python3
"""EXPRESS-G raster box detector (Group 3).
Detect entity/type boxes in a raster diagram page, classify rect vs oval
(page-ref stadiums get no anchors), OCR each box label with PaddleOCR.
Output: JSON per page {boxes: [{x,y,w,h,kind,text}]}. Runs on python3.12.
"""
import sys, json, os
import numpy as np
import cv2

def border_search(binv, x, y, w, h, reach):
    """Directed outward search for the 4 border lines of a hole bbox.
    Returns (coverages, outer_bbox): per-edge best ink coverage and the
    outer box extended to the found border rows/cols."""
    H, W = binv.shape
    r = max(6, h // 2)               # stadium end allowance for horiz edges
    def best_row(y_from, y_to, x0, x1):
        best, at = 0.0, y_from
        for yy in range(max(0, y_from), min(H, y_to + 1)):
            row = binv[yy, max(0, x0):min(W, x1)]
            f = float((row > 0).mean()) if row.size else 0.0
            if f > best: best, at = f, yy
        return best, at
    def best_col(x_from, x_to, y0, y1):
        best, at = 0.0, x_from
        for xx in range(max(0, x_from), min(W, x_to + 1)):
            col = binv[max(0, y0):min(H, y1), xx]
            f = float((col > 0).mean()) if col.size else 0.0
            if f > best: best, at = f, xx
        return best, at
    top, ty = best_row(y - reach, y + 3, x + r, x + w - r)
    bot, by = best_row(y + h - 4, y + h + reach, x + r, x + w - r)
    left, lx = best_col(x - reach, x + 3, y + h // 4, y + h - h // 4)
    right, rx = best_col(x + w - 4, x + w + reach, y + h // 4, y + h - h // 4)
    return (top, bot, left, right), (lx, ty, rx - lx + 1, by - ty + 1)

def detect(img_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    H, W = img.shape
    _, binv = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # multi-kernel candidate holes (small kernels catch solid boxes/ovals
    # crisply; larger ones seal dashed borders)
    cands = []
    for k in (3, 7, 9, 11):
        sealed = cv2.morphologyEx(binv, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
        cs, hier = cv2.findContours(sealed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        for i, c in enumerate(cs):
            if hier[0][i][3] == -1: continue
            x, y, w, h = cv2.boundingRect(c)
            if w < 45 or h < 16 or w > 0.9 * W or h > 0.25 * H: continue
            cands.append((x, y, w, h, k))
    # dedupe by IoU (tight hole bboxes across kernels land nearly identical)
    dedup = []
    for b in cands:
        bx, by, bw, bh, _ = b
        dup = False
        for kx, ky, kw, kh, _ in dedup:
            ix = max(0, min(bx + bw, kx + kw) - max(bx, kx))
            iy = max(0, min(by + bh, ky + kh) - max(by, ky))
            if ix * iy > 0.55 * min(bw * bh, kw * kh): dup = True; break
        if not dup: dedup.append(b)
    # validate + classify by directed border search
    out = []
    for x, y, w, h, k in dedup:
        (top, bot, left, right), (ox, oy, ow, oh) = border_search(binv, x, y, w, h, reach=k // 2 + 4)
        if top < 0.6 or bot < 0.6:          # no real horizontal borders
            continue
        if left > 0.5 and right > 0.5:
            kind = 'rect'                    # incl. dashed (coverage ~0.5-0.8)
        elif top > 0.85 and bot > 0.85 and h < 60:
            kind = 'oval'                    # solid middle run, rounded ends
        else:
            continue
        out.append({'x': ox, 'y': oy, 'w': ow, 'h': oh, 'kind': kind,
                    'edges': [round(v, 2) for v in (top, bot, left, right)]})
    # final dedupe on outer boxes
    final = []
    for b in sorted(out, key=lambda b: -(b['w'] * b['h'])):
        dup = False
        for k2 in final:
            ix = max(0, min(b['x'] + b['w'], k2['x'] + k2['w']) - max(b['x'], k2['x']))
            iy = max(0, min(b['y'] + b['h'], k2['y'] + k2['h']) - max(b['y'], k2['y']))
            if ix * iy > 0.6 * min(b['w'] * b['h'], k2['w'] * k2['h']): dup = True; break
        if not dup: final.append(b)
    final.sort(key=lambda b: (b['y'], b['x']))
    return img, final

def main():
    img_path = sys.argv[1]
    img, boxes = detect(img_path)
    # OCR each box interior
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, lang='en')
    for b in boxes:
        pad = 3
        crop = img[b['y'] + pad:b['y'] + b['h'] - pad, b['x'] + pad:b['x'] + b['w'] - pad]
        # upscale small crops for OCR
        scale = 2 if crop.shape[0] < 80 else 1
        if scale > 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        crop_rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        try:
            res = ocr.predict(crop_rgb)
            texts = []
            for r in res:
                texts.extend(r.get('rec_texts', []) if isinstance(r, dict) else r['rec_texts'])
            b['text'] = ' '.join(texts)
        except Exception as e:
            b['text'] = f'<OCR-ERROR {e}>'
    print(json.dumps({'image': os.path.basename(img_path),
                      'boxes': boxes}, indent=1))

if __name__ == '__main__':
    main()
