# Draft svgmap blocks for PR #689 modules, letters q–z

**Date:** 2026-07-14
**Requested:** [PR #689 comment](https://github.com/metanorma/iso-10303/pull/689#issuecomment-4975569015) (Manuel Fuenmayor, 2026-07-15 UTC)
**Source revision:** `mf-add-svgmaps-modules` @ `ff8cfc80a` ("letter p - part 1")
**Generator:** `gen_drafts.py` in this repository (PaddleOCR PP-OCRv5 server +
closed-vocabulary resolution, per `report.md`; no language model, no network)

## Scope

113 modules `schemas/modules/[q-z]*` with `arm.exp`/`mim.exp` and
`{arm,mim}expg<N>.svg` diagrams: **225 module files, 528 diagrams, 5,754
hotspot entries**. (The PR-comment estimate of ~550 polygons for p–z was low
by an order of magnitude; r/s/t/v dominate.)

Excluded, matching the conventions of the committed a–p blocks:

- SVG-only asset directories without `arm.exp`/`mim.exp`
  (`set_theory_schema`, `sketch_schema`, `solid_shape_element_schema`,
  `topology_schema`, `variational_representation_schema`,
  `vehicle_electric_container` incl. its 33 `vec_modelschemaexpg*.svg`)
- `_lf` diagram variants (`simplified_cataloguing/{arm,mim}expg_lf1.svg`)

## Output

- `drafts-qz/<module>/{arm,mim}.svgmap.txt` — ready-to-insert
  `(*"<Schema>.__expressg" [.svgmap] ... *)` blocks, one per diagram, in
  Manuel's committed format. Insertion point: immediately after the
  `(*"<Schema>.__title" ... *)` block.
- `drafts-qz/<module>/{arm,mim}.rows.json` — per-entry OCR text, resolved
  ref, score, method, review flag.
- `drafts-qz/REVIEW.tsv` — all 2,824 non-clean entries for human review.
- `drafts-qz/special-diagrams.txt` — 18 diagrams needing diagram-level review.

## Results

| flag | entries | meaning |
|---|---|---|
| ok | 2,930 | exact/convention resolution, statically verified |
| convention | 1,041 | `required_am_arms` / `short_listing` / bare-schema choice (mechanical in module corpus; 10 also unverified) |
| check | 618 | fuzzy or global-catalog resolution — review the proposed ref |
| check+unverified | 57 | proposed ref not among declared/interfaced names — review |
| UNRESOLVED | 117 | empty/garbled OCR; placeholder `UNRESOLVED` left in draft |
| degenerate | 342 | anchors of the 14 all-identical placeholder diagrams (drafted per committed convention: one entry, highest number → module primary anchor) |
| broken-svg | 647 | anchors of the 4 broken-coordinate diagrams (drafted image-only) |

Static verification: every emitted ref checked against declarations,
USE/REFERENCE FROM interface closure (heuristic, regex-based — not an
authoritative EXPRESS closure), bare schema names, and the toolchain section
anchors (`required_am_arms`, `short_listing`, numeric page anchors). Healthy
diagrams: draft entry sets equal the SVG anchor-number sets, 528/528 blocks,
0 mismatches. 67 flagged refs fail static verification and appear in
REVIEW.tsv as `+unverified`.

Expected residual error, based on the measured a–i baseline (report.md):
low single-digit percent among unflagged entries; the flag classes above are
designed to catch the known error modes (convention choice, OCR misreads,
interfaced-name qualification).

## Upstream defects found (worth reporting on PR #689 / issue #676)

Four diagrams have hotspot polygons whose coordinates fall mostly **outside
the SVG viewBox** (conversion defect; hotspots unusable — the extreme case
has 574 anchors on a 720×540 page):

- `requirement_management/armexpg3.svg` (574 anchors), `mimexpg2.svg`
- `risk_management/armexpg2.svg`, `mimexpg4.svg`

Fourteen diagrams are "Special case: diagrams for modules containing
EXPRESS-G only" placeholders whose anchors all share one identical geometry
(list in `special-diagrams.txt`); drafts follow the dominant committed
convention (single entry, e.g. `ap233_systems_engineering/armexpg2`).

## Per-letter summary

| letter | entries | ok | convention | needs review | degenerate/broken |
|---|---|---|---|---|---|
| q | 74 | 51 | 22 | 1 | 0 |
| r | 1,861 | 771 | 324 | 87 | 676 |
| s | 2,102 | 1,006 | 414 | 410 | 263 |
| t | 1,030 | 684 | 138 | 208 | 0 |
| u | 22 | 13 | 6 | 3 | 0 |
| v | 166 | 116 | 25 | 25 | 0 |
| w | 464 | 263 | 94 | 57 | 50 |
| z | 35 | 26 | 8 | 1 | 0 |
