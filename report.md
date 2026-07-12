# EXPRESS-G svgmap Auto-Resolution: Feasibility Study

**Date:** 2026-05-09
**Context:** PR [metanorma/iso-10303#689](https://github.com/metanorma/iso-10303/pull/689) — *"Add svgmaps in modules exp files"*
**Goal:** Determine whether the manual svgmap-authoring workflow can be automated with the technology available now, after an earlier automation attempt was evaluated and rejected in April 2026.

---

## Background

PR #689 retrofits hyperlinked svgmap blocks into the `.exp` source of every ISO 10303 module. Each EXPRESS-G diagram is stored as an SVG that wraps a base64-encoded GIF and overlays invisible numbered `<polygon>` hotspots. The svgmap block (an AsciiDoc directive embedded as an EXPRESS comment) maps each polygon's number to a canonical metanorma anchor of the form `Schema_name.entity_name`.

These blocks were being authored by hand: for each GIF, identify the entity in each numbered region and type the canonical reference. With about 316 modules remaining and about 3 polygons per module, the work was projected to take 5–8 weeks at the observed rate.

Automation was evaluated in the PR discussion in April 2026 and was rejected. That attempt used an LLM to read the diagram images, and it had two problems: recognition errors frequent enough that every image still needed human review, and API usage costs. The question for this study is whether the technology available now gives a different result. The approach tested here is different in structure: local OCR models plus a closed-vocabulary identifier catalog derived from the `.exp` files — no LLM and no network API. This also had to handle the small text and the period separator in `Schema.entity`.

## Method

A pipeline was built and run end-to-end on real PR data:

1. **Catalog**: Walk every `.exp` file in `schemas/{modules,resources,business_object_models}/` and extract every `ENTITY` / `TYPE` / `FUNCTION` / `RULE` / `SUBTYPE_CONSTRAINT` declaration plus each schema's `USE FROM` / `REFERENCE FROM` imports. Result: **114,210 declarations across 1,449 schemas**.
2. **Per-diagram preprocessing**: Parse each SVG — extract `viewBox`, the embedded GIF (decode base64 → RGB PIL image), and the list of `(href_number, polygon_points)` tuples.
3. **OCR**: Crop the GIF to each polygon's bounding rectangle, upscale 4× with Lanczos, run **PaddleOCR PP-OCRv5 server models** (`PP-OCRv5_server_det` + `PP-OCRv5_server_rec`) with no document preprocessing. PP-OCRv5 is an open-source non-VLM OCR model released in late 2025.
4. **Resolution**: Strip non-alphanumeric characters from the OCR output, then apply this priority chain against a candidate pool of (own schema's declarations + `USE FROM` imports' declarations + global schema names):
   - `page-reference` — OCR matches `\d+,\d+\(\d+\)` (page coordinates) → `<schema>.<polygon_num>`
   - `exact-local-concat` — OCR equals `Schema+Entity`
   - `schema->primary` — OCR equals a schema name → emit synthetic anchor
   - `exact-name-local` — OCR equals an entity name in the local pool
   - `schema-prefix-exact-tail` — OCR begins with a schema name; the tail is the entity
   - `schema-prefix-fuzzy-tail` — same, with fuzzy tail matching
   - `schema->primary-global` / `schema-prefix-only-global` — same, against the global catalog
   - `fuzzy-local-{concat,name,schema}` — Levenshtein fallback inside the local pool
5. **Ground truth**: Parse the hand-authored svgmap entries (`<<express:Schema.entity>>; N`) from the `.exp` diff in PR #689, compared as `(svg_basename, polygon_num, canonical)`.
6. **Sampling**: Round-robin across the first letters of module directories (`a` through `i`, the range already committed in the PR) until 300+ polygons were evaluated.

## Synthetic anchors discovered during analysis

Three "anchors" used as the entity portion of the canonical reference are NOT real EXPRESS declarations — they are metanorma-level cross-reference targets, and the pipeline must handle them as special cases:

| Anchor | When | Notes |
|---|---|---|
| `required_am_arms` | ARM schemas, when the polygon represents the whole schema | Found in many AP-level overview diagrams (ap239_*, configuration_item, analysis_representation). |
| `short_listing` | MIM schemas, and *some* ARM schemas (activity_as_realized, activity_characterized, activity_method) | Same role as `required_am_arms` but a different naming tradition. |
| (none — bare schema name) | Resource schemas (`*_schema`, not `_arm`/`_mim`) | Canonical is just `action_schema`, no entity suffix. |

The choice between them follows a per-module convention — no syntactic rule in the `.exp` file predicts which one applies.

## Results

**302 polygons evaluated, 88.1% resolved correctly with no human input.**

```text
Per-letter accuracy
  letter    OK   ERR  MISS  total    pct
  a        105    28     0    133  78.9%
  b          3     0     0      3 100.0%
  c          1     0     0      1 100.0%
  d         26     0     0     26 100.0%
  e          6     1     0      7  85.7%
  f         30     0     3     33  90.9%
  g         59     3     0     62  95.2%
  h         16     0     0     16 100.0%
  i         20     1     0     21  95.2%

Per-method accuracy
  method                              OK   ERR  MISS  total    pct
  fuzzy-local-name                   111     5     0    116  95.7%
  schema-prefix-exact-tail            70    10     0     80  87.5%
  schema->primary                     58    17     0     75  77.3%
  page-reference                      15     0     0     15 100.0%
  schema-prefix-fuzzy-tail             5     0     0      5 100.0%
  fuzzy-local-schema                   5     0     0      5 100.0%
  fuzzy-local-concat                   1     1     0      2  50.0%
  exact-name-local                     1     0     0      1 100.0%
  no-match                             0     0     2      2   0.0%
  empty                                0     0     1      1   0.0%

Total: 266 correct (88.1%), 33 wrong (10.9%), 3 missing (1.0%)
```

## Error breakdown (33 errors)

```text
Cause                                                                    Count
─────────────────────────────────────────────────────────────────────────────
Convention ambiguity: required_am_arms vs short_listing vs primary entity   22
Data defect — `_min` typo in source (truth says `Activity_min.…`,
  pipeline correctly emits `Activity_mim.…`)                                 5
AIC schema written under the current MIM schema namespace, per the
  convention used in the PR, rather than as a bare schema reference          3
Source has trailing-dot/empty entity (truth = `Schema.`)                     2
Fuzzy tail picked a sibling entity (date_or_date_time vs date_and_time)      1
```

If the data defects found by the pipeline (5 typos + 2 incomplete entries) are excluded, effective accuracy is **271/295 ≈ 91.9%** on a strict comparison. With a UI offering a top-2 choice for the 22 ambiguous-convention cases, accuracy after review approaches **98%**, at a cost of one keystroke per case.

## Findings

1. **OCR accuracy is sufficient for this task.** PaddleOCR PP-OCRv5 server at 4× Lanczos upscale reads the embedded GIF text with few errors. Almost no errors come from character recognition; nearly all come from convention or disambiguation problems.

2. **The period separator is not a problem.** None of the 302 polygons failed because of a missed `.` between schema and entity. The catalog match makes the period redundant — it is a layout convention, not a character the pipeline must read.

3. **The `.exp` catalog approach works.** Constraining OCR output to the union of (own schema's declarations + `USE FROM` imports + a global schema-name fallback) yields 95–100% accuracy whenever the OCR text contains an entity name. The vocabulary is small per diagram (~150 candidates), so fuzzy matching is nearly deterministic.

4. **Three synthetic anchors exist and must be encoded as rules**, not derived from the catalog: `required_am_arms`, `short_listing`, and the bare schema name. These were discovered by reading the diff data; they are not documented outside the PR's own content.

5. **Page-reference diagrams** (for example `general_design_connectivity/armexpg2-5.svg`), where boxes are sub-page navigators with truth `<schema>.<integer>`, were at first completely missed by the pipeline. A ~3-line OCR-pattern rule (digit-comma-digit-parenthesis-digit → emit `<schema>.<polygon_num>`) brought them to 100%.

6. **The convention split within the module corpus** is the main remaining obstacle. Within letter `a` alone:
   - `activity` uses the primary entity (`Activity_arm.Activity`)
   - `activity_as_realized`, `activity_characterized`, `activity_method` use `short_listing`
   - `analysis_representation` uses `required_am_arms`
   No rule visible in the `.exp` files predicts which convention was chosen. The pipeline's job is to suggest the most likely default and let the human change it with one keystroke.

7. **The pipeline also finds defects in the hand-authored output**: 5 instances of `Activity_min.short_listing` (typo for `_mim`) and 2 instances of `Schema.` with an empty entity. These are flagged as "predicted ≠ truth" and surfaced in review.

## Implications for PR #689

- ~316 modules remaining × ~3 polygons average ≈ ~900 polygons.
- At 88% top-1 accuracy: ~790 auto-confirmed, ~110 needing a one-keystroke disambiguation.
- Estimated review time: **3–5 hours** instead of the ~30–50 hours implied by the observed manual rate (~5 modules/day, working alphabetically through letter `i`).
- This would move the projected mid-July completion to **late May / early June 2026** if the pipeline were adopted.
- As a side benefit, the pipeline can retroactively flag the typos and incomplete entries in the ~326 modules already committed.

## Conclusion on the April 2026 question

The two reasons for the April 2026 rejection do not apply to this approach:

- **Cost**: there is no API and no LLM. All computation is local and free.
- **Error rate**: errors are constrained by the closed vocabulary. OCR output is either matched to a declared name or flagged for review. Review effort drops from "check every image" to "decide the flagged cases".

## Pipeline architecture (final)

```
.exp catalog ─────────────┐
                          │
SVG file ─► extract polygons + base64 GIF
                ▼
         crop polygon region
                ▼
         4× Lanczos upscale
                ▼
         PaddleOCR PP-OCRv5 server  ──► OCR text
                                          │
                                          ▼
                          page-ref pattern? ──yes──► <schema>.<polygon_num>
                                          │ no
                                          ▼
                          clean (drop non-alphanumerics)
                                          ▼
                          resolve against catalog priority chain
                                          ▼
                          (canonical, score, method)
                                          ▼
                          emit svgmap entry
```

## Open questions

- Would PaddleOCR-VL or DeepSeek-OCR-2 (true VLMs) reduce the OCR-only failures (the `_a m` for `_arm`, fragment cases) below their current low rate? Possibly worthwhile if the running cost is acceptable; not a blocker.
- Is there a discoverable rule for the convention split? Reading metanorma's templating code (`*.liquid` files in this PR) might show whether the choice is encoded somewhere not yet examined.
- Should the pipeline cross-validate against the *previously* committed svgmap entries within a module, to learn the convention from sibling diagrams in the same file?

## Artifacts

- Simulation script: `sim_pipeline.py` (this repository)
- Tested against a local clone of `metanorma/iso-10303`, branch `pr689` (the PR #689 head)
- PaddleOCR cache: `~/.paddlex/official_models/PP-OCRv5_server_{det,rec}`

## Reproduction

```bash
# Prerequisites (Python 3.12, since paddlepaddle has no 3.14 wheel as of 2026-05):
python3.12 -m pip install --user paddlepaddle paddleocr rapidfuzz lxml

# Fetch the PR branch
cd /path/to/iso-10303
git fetch origin pull/689/head:pr689 && git checkout pr689

# Run the simulation
ISO10303_REPO=$PWD TARGET_POLYGONS=300 python3.12 sim_pipeline.py
```
