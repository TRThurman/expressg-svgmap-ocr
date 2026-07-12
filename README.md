# expressg-svgmap-ocr

Tools to automate the authoring of `[.svgmap]` blocks for EXPRESS-G
diagrams in ISO 10303 documents published with metanorma. Context:
[metanorma/iso-10303#689](https://github.com/metanorma/iso-10303/pull/689)
and issue [#687](https://github.com/metanorma/iso-10303/issues/687).

The pipeline does not use a language model and does not call any network
API. All processing runs on the local machine:
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) PP-OCRv5 models
read the diagram text, and the result is matched against a catalog of
declarations extracted from the repository's own `.exp` files. Each OCR
result is either matched to a declared name or marked for human review.

## Measured accuracy

Evaluated against 302 polygons from the letters a–i commits in PR #689.
Full method, accuracy tables, and error analysis are in
[report.md](report.md).

- **88.1%** resolved correctly with no human input, using a catalog of
  114,210 declarations across 1,449 schemas
- **91.9%** after excluding 7 defects that the pipeline found in the
  existing hand-authored entries (5 `_min`-for-`_mim` typos and
  2 entries with an empty entity name)
- ~**98%** after review, where review means one keystroke to choose
  between `required_am_arms`, `short_listing`, and the bare schema name.
  This choice is the main remaining ambiguity. It follows a per-module
  convention and cannot be derived from the `.exp` source.

## Contents

| Path | Description |
|---|---|
| `report.md` | Feasibility study (2026-05-09): method, accuracy tables, error analysis, pipeline architecture |
| `sim_pipeline.py` | The measured pipeline: `.exp` catalog builder, SVG/GIF extraction, PaddleOCR, resolver, comparison against the PR #689 ground truth |
| `svgmap-tools/` | Scripts used to author 635 svgmap entries on a related ISO 10303 corpus; all entries were verified and merged |

### svgmap-tools/

- `gen_svgmap.py` — catalog and resolver machinery; list-only authoring
  for diagrams whose SVG anchors already exist
- `gen_svgmap_112.py` — vector-SVG path: entity-box extraction from
  white-fill paths, anchor injection, list generation
- `ocr_boxes.py`, `detect_boxes.py` — raster path: text-anchored box
  detector (PaddleOCR plus directed border rays) for diagrams stored as
  embedded GIF or PNG rasters
- `assemble_*.py` — detector output plus human adjudication
  (DROP/RECOVER tables) → final per-diagram JSON
- `resolve_502.py`, `write_*.py` — catalog resolution and writers that
  emit SVG anchor overlays and `.exp` `[.svgmap]` entries

These scripts were written for one specific corpus. Set the `WT`
environment variable (or `ISO10303_REPO` for `sim_pipeline.py`) to your
working tree, and expect to adapt the per-part constants. The scripts
include a static verification step: every emitted
`<<express:Schema.entity>>` is checked against the declarations present
in that schema's `.exp` file, and the anchor set of each image is
checked for equality with its entry set.

## Requirements

Python **3.12** (paddlepaddle publishes no wheels for newer Python
versions as of mid-2026):

```bash
python3.12 -m pip install --user paddlepaddle paddleocr rapidfuzz lxml opencv-python pillow numpy
```

The first run downloads the PP-OCRv5 detection and recognition models to
`~/.paddlex/official_models/`.

## Running the PR #689 simulation

```bash
git clone https://github.com/metanorma/iso-10303
cd iso-10303
git fetch origin pull/689/head:pr689 && git checkout pr689

ISO10303_REPO=$PWD TARGET_POLYGONS=300 python3.12 /path/to/sim_pipeline.py
```

## Pipeline architecture

```
.exp catalog ─────────────┐
                          │
SVG file ─► extract polygons + base64 GIF
                ▼
         crop polygon region
                ▼
         4× Lanczos upscale
                ▼
         PaddleOCR PP-OCRv5 (local)  ──► OCR text
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
                          emit svgmap entry (or flag for review)
```

## License

MIT — see [LICENSE](LICENSE).
