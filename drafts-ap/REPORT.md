# Draft svgmap blocks for modules ap210 and ap242

**Date:** 2026-07-18
**Source revision:** `mf-add-svgmaps-modules` @ `380652476`
("Address unresolved svgmaps entries (modules)")
**Generator:** `gen_drafts.py` in this repository (PaddleOCR PP-OCRv5 server +
closed-vocabulary resolution, per `report.md`; no language model, no network),
extended for this run with fuzzy matching of the *schema part* of qualified
labels (see "Resolver extension" below).

## Scope

Two application-protocol modules:

| module | diagrams | hotspot entries |
|---|---|---|
| `ap210_electronic_assembly_interconnect_and_packaging_design` | 4 arm + 3 mim | 249 + 231 = 480 |
| `ap242_managed_model_based_3d_engineering` | 61 arm + 59 mim | 3,225 + 3,079 = 6,304 |
| **total** | **127** | **6,784** |

This single-module pair is larger than the entire q–z run (5,754 entries).

Current state on the source branch:

- ap210 `arm.exp`/`mim.exp` already carry 7 committed svgmap blocks, all
  **image-only** (no hotspot entries). Applying these drafts means
  **replacing** those blocks, not inserting after `__title`.
- ap242 `arm.exp`/`mim.exp` carry **no** svgmap blocks; the drafts insert
  after the `(*"<Schema>.__title" ... *)` block per the committed convention.

## Output

- `drafts-ap/<module>/{arm,mim}.svgmap.txt` — ready-to-insert
  `(*"<Schema>.__expressg" [.svgmap] ... *)` blocks, one per diagram, in the
  committed format.
- `drafts-ap/<module>/{arm,mim}.rows.json` — per-entry OCR text, resolved
  ref, score, method, review flag.
- `drafts-ap/REVIEW.tsv` — all 4,515 non-clean entries for human review.

## Results

| flag | entries | meaning |
|---|---|---|
| ok | 2,269 | exact/convention resolution, statically verified |
| convention | 115 | `required_am_arms` / `short_listing` / bare-schema choice |
| check | 4,340 | fuzzy resolution — review the proposed ref (4,093 score ≥ 90) |
| UNRESOLVED | 60 | empty/truncated/garbled OCR; placeholder `UNRESOLVED` left in draft |

Method breakdown: `qualified-verbatim` 2,172 (ok), `qualified-fuzzy` 3,031 +
`qualified-fuzzy-schema` 939 (check), `fuzzy-local-*` 370 (check),
`schema->primary` 115 (convention), `exact-name-local-clean` 94 (ok),
`page-reference` 3 (ok), `no-match` 60 (UNRESOLVED).

Unlike the q–z module corpus (dominated by local declaration names), these AP
diagrams are overwhelmingly *qualified inter-module references*
(`<Module>_arm.<Entity>` boxes on schema-relationship overview diagrams) —
hence the large check class: the proposed refs are almost all high-confidence,
but the qualified reading deserves the one-pass review.

No degenerate (all-identical placeholder) and no broken-coordinate diagrams
were found in either module (the q–z run had 14 + 4).

## Resolver extension (this run)

The AP overview diagrams defeat exact schema-prefix matching: OCR reliably
corrupts the `_arm` suffix (`amm`, `anm`, `am`), doubles letters
(`imnterconnect`), and frequently drops the `.` separator entirely
(`Document_structure_arm.File_relationship` → OCR
`"Document structure ammFile_relationship"`). The first pass left 2,219 of
6,784 entries UNRESOLVED, 125 of them on ap210 `armexpg2.svg` alone.

`resolve_qualified` was extended: after the exact paths fail, the schema part
is matched fuzzily (rapidfuzz ratio ≥ 90, schema clean-name ≥ 8 chars) —
against the left part of dotted labels, or as a sliding head-slice split of
dotless text. A fuzzy-schema resolution stands only if the remaining tail
also resolves (exact against the schema's visible names, exact against the
global catalog, or fuzzy ≥ 80), and always returns a method outside
`CLEAN_METHODS`, so it lands in `check` — never silently clean. Re-resolution
ran from the OCR text cached in `rows.json` (`--reresolve`; no second OCR
pass). UNRESOLVED dropped 2,219 → 60; the `ok` class was untouched by
construction (2,269 before and after).

## Static verification

Every emitted `<<express:...>>` ref checked against declarations, the
USE/REFERENCE FROM interface closure (heuristic, regex-based — not an
authoritative EXPRESS closure), bare schema names, and toolchain anchors:
**0 unverified refs**. Draft entry sets equal the SVG anchor-number sets on
all healthy diagrams: **127/127 blocks, 0 mismatches**.

Expected residual error, per the measured a–i baseline (`report.md`): low
single-digit percent among unflagged entries; the flag classes are designed
to catch the known error modes (convention choice, OCR misreads,
interfaced-name qualification).
