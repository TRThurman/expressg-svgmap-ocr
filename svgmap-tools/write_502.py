#!/usr/bin/env python3
"""Write 502 SVG shells (embedded PNG + numbered anchors) and .exp svgmap
entries, following the proven part-41 raster-wrapper pattern."""
import os, re, json, base64, struct

SP = os.path.dirname(os.path.abspath(__file__))
AIC = "aic_shell_based_wireframe"
DIR = f"{os.environ.get('WT', '.')}/schemas/resources/{AIC}"
STYLE = ("opacity: 0; fill: rgb(33, 128, 255); fill-opacity: 0.3; "
         "stroke: rgb(0, 128, 255); stroke-width: 1px;")

def png_dims(path):
    with open(path, 'rb') as f:
        head = f.read(26)
    assert head[12:16] == b'IHDR'
    w, h = struct.unpack('>II', head[16:24])
    return w, h

def main():
    final = json.load(open(f"{SP}/final_502.json"))
    exp_path = f"{DIR}/{AIC}.exp"
    exp = open(exp_path, encoding='utf-8', errors='replace').read()
    for n in sorted(final, key=int):
        rows = final[n]
        png = f"{DIR}/{AIC}expg{n}.png"
        w, h = png_dims(png)
        b64 = base64.b64encode(open(png, 'rb').read()).decode()
        anchors = '\n'.join(
            f'<a href="{i}"><rect onmouseout="this.style.opacity=0" '
            f'onmouseover="this.style.opacity=1" style="{STYLE}" '
            f'x="{r["x"]}" y="{r["y"]}" width="{r["w"]}" height="{r["h"]}"/></a>'
            for i, r in enumerate(rows, 1))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" '
               f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
               f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>\n'
               f'{anchors}\n</svg>\n')
        svgname = f"{AIC}expg{n}.svg"
        open(f"{DIR}/{svgname}", 'w', encoding='utf-8').write(svg)
        print(f"wrote {svgname} ({len(rows)} anchors)")
        # .exp: png -> svg, add [.svgmap] header + entries
        entries = '\n'.join(f'* <<{r["target"]}>>; {i}' for i, r in enumerate(rows, 1))
        old = f'====\nimage::{AIC}expg{n}.png[]\n===='
        new = f'[.svgmap]\n====\nimage::{svgname}[]\n\n{entries}\n===='
        assert exp.count(old) == 1, (n, exp.count(old))
        exp = exp.replace(old, new)
    open(exp_path, 'w', encoding='utf-8').write(exp)
    print(f"updated {AIC}.exp")

if __name__ == '__main__':
    main()
