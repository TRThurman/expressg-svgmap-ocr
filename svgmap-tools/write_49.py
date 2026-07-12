#!/usr/bin/env python3
"""Write part-49 svgmap anchors into the existing strip-raster SVG wrappers
and entry lists into the .exp [.svgmap] blocks (Group 3).
Renders are 2x -> divide by 2 for viewport coords. Idempotent-guarded."""
import json, os, re

SP = os.path.dirname(os.path.abspath(__file__))
RES = os.environ.get("WT", ".") + "/schemas/resources"
STYLE = ("opacity: 0; fill:#2180ff;fill-opacity:0.3;stroke:#000000;"
         "stroke-width:0;stroke-linecap:square;stroke-miterlimit:10.1;"
         "stroke-dasharray:none")

def fmt(v):
    return f"{v/2:g}"

def main():
    final = json.load(open(f"{SP}/final_49.json"))
    for schema, rows in final.items():
        svg_path = f"{RES}/{schema}/images/{schema}expg1.svg"
        svg = open(svg_path, encoding='utf-8', errors='replace').read()
        assert '<a href="' not in svg, f"{svg_path} already has anchors"
        anchors = '\n'.join(
            f'<a href="{i}"><rect onmouseout="this.style.opacity=0" '
            f'onmouseover="this.style.opacity=1" style="{STYLE}" '
            f'x="{fmt(r["x"])}" y="{fmt(r["y"])}" width="{fmt(r["w"])}" '
            f'height="{fmt(r["h"])}" ry="0" /></a>'
            for i, r in enumerate(rows, 1))
        idx = svg.rindex('</svg>')
        svg = svg[:idx] + anchors + '\n' + svg[idx:]
        open(svg_path, 'w', encoding='utf-8').write(svg)
        print(f"svg: {schema}expg1.svg +{len(rows)} anchors")

        exp_path = f"{RES}/{schema}/{schema}.exp"
        txt = open(exp_path, encoding='utf-8', errors='replace').read()
        entries = '\n'.join(f'* <<{r["target"]}>>; {i}' for i, r in enumerate(rows, 1))
        old = f'====\nimage::images/{schema}expg1.svg[]\n===='
        assert txt.count(old) == 1, (schema, txt.count(old))
        txt = txt.replace(old, f'====\nimage::images/{schema}expg1.svg[]\n\n{entries}\n====')
        open(exp_path, 'w', encoding='utf-8').write(txt)
        print(f"exp: {schema}.exp +{len(rows)} entries")

if __name__ == '__main__':
    main()
