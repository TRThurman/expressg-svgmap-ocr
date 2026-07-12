#!/usr/bin/env python3.12
"""
Simulate the manual svgmap authoring workflow of PR #689 using PaddleOCR.

For modules already updated in the PR:
  1. Build a catalog of every ENTITY/TYPE/SUBTYPE_CONSTRAINT in every .exp file (whole repo).
  2. Read each module's *.svg, extract polygons (numbered hrefs) + decode the embedded GIF.
  3. For each polygon, crop the GIF region, OCR with PaddleOCR (PP-OCRv5 server),
     and resolve the cleaned text to a canonical "Schema.entity" via fuzzy match against the catalog,
     biased toward the schema's own decls + USE/REFERENCE FROM imports.
  4. Compare predicted (number -> canonical) against the hand-authored svgmap entries from the .exp diff.
"""
import re, sys, json, base64, io, glob, os, subprocess
from pathlib import Path
from collections import defaultdict
from PIL import Image
from lxml import etree
from rapidfuzz import process, fuzz

REPO = Path(os.environ.get("ISO10303_REPO", os.path.expanduser("~/iso-10303")))

# ── catalog ───────────────────────────────────────────────────────────────
def parse_exp(path: Path):
    """Return (schema_name, decls, uses) where decls is list of (kind, name)."""
    text = path.read_text(errors="replace")
    # strip block comments to avoid catching ENTITY/TYPE inside doc text
    text_nc = re.sub(r"\(\*.*?\*\)", "", text, flags=re.DOTALL)
    # SCHEMA name may be followed by an optional SDS version string, then ';'
    schemas = re.findall(r"\bSCHEMA\s+(\w+)\b", text_nc, re.IGNORECASE)
    decls = re.findall(r"\b(ENTITY|TYPE|FUNCTION|RULE|SUBTYPE_CONSTRAINT)\s+(\w+)",
                       text_nc, re.IGNORECASE)
    uses = re.findall(r"(?:USE|REFERENCE)\s+FROM\s+(\w+)", text_nc, re.IGNORECASE)
    return (schemas[0] if schemas else None,
            [(k.upper(), n) for k, n in decls],
            list(set(uses)))

def build_catalog():
    catalog = {}            # "schema.name" -> {schema, name, kind}
    dotless = {}            # lowercase concat -> "schema.name"
    by_name = defaultdict(list)  # lowercase name -> list of "schema.name"
    per_schema = {}
    exp_files = sorted(glob.glob(str(REPO / "schemas/**/*.exp"), recursive=True))
    for ep in exp_files:
        schema, decls, uses = parse_exp(Path(ep))
        if not schema: continue
        per_schema[schema] = {
            "own": [n for _, n in decls],
            "uses": uses,
            "file": ep,
        }
        for kind, name in decls:
            canonical = f"{schema}.{name}"
            catalog[canonical] = {"schema": schema, "name": name, "kind": kind}
            dotless[(schema + name).lower()] = canonical
            by_name[name.lower()].append(canonical)
    return catalog, dotless, by_name, per_schema

# ── parse ground truth from .exp ─────────────────────────────────
SVGMAP_BLOCK = re.compile(
    r'\(\*"([^"]+?)\.__expressg".*?image::(\w+)\.svg\[\](.*?)====\s*\*\)',
    re.DOTALL,
)
SVGMAP_ENTRY = re.compile(
    r'<<express:([^,>]+?)(?:,[^>]+)?>>;\s*(\d+)',
)

def extract_groundtruth(exp_path: Path):
    """Return {svg_basename: {number_str: 'Schema.name'}} from svgmap blocks."""
    out = defaultdict(dict)
    text = exp_path.read_text(errors="replace")
    for m in SVGMAP_BLOCK.finditer(text):
        _wrapper, svg_name, body = m.groups()
        for em in SVGMAP_ENTRY.finditer(body):
            ref, num = em.group(1).strip(), em.group(2).strip()
            out[svg_name][num] = ref
    return dict(out)

# ── parse SVG: polygons + base64 GIF ──────────────────────────────────────
NS = {"s": "http://www.w3.org/2000/svg", "x": "http://www.w3.org/1999/xlink"}

def parse_svg(svg_path: Path):
    """Return (PIL.Image, viewbox, list of (number, polygon_pts))."""
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    vb = root.get("viewBox", "0 0 100 100").split()
    vb = tuple(float(x) for x in vb)
    # find embedded GIF
    img = None
    for el in root.iter():
        if etree.QName(el).localname == "image":
            href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href")
            if href and href.startswith("data:image/"):
                b64 = href.split(",", 1)[1]
                raw = base64.b64decode(b64)
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                break
    polys = []
    for a in root.iter():
        if etree.QName(a).localname != "a": continue
        href = a.get("href") or a.get("{http://www.w3.org/1999/xlink}href")
        if not href or not href.isdigit(): continue
        for poly in a.iter():
            if etree.QName(poly).localname == "polygon":
                pts_attr = poly.get("points", "")
                pts = re.findall(r"-?\d+(?:\.\d+)?", pts_attr)
                pts = [(float(pts[i]), float(pts[i+1])) for i in range(0, len(pts)-1, 2)]
                if pts:
                    polys.append((href, pts))
    return img, vb, polys

# ── OCR engine ────────────────────────────────────────────────────────────
_ocr = None
def get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        # Highest-accuracy server models (not mobile). Disable doc preprocessing
        # since these are tiny diagrams not full pages.
        _ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )
    return _ocr

def crop_for_polygon(img: Image.Image, vb, pts, upscale=4):
    """Crop the image rectangle bounding the polygon, in image coords, then upscale."""
    iw, ih = img.size
    vbx, vby, vbw, vbh = vb
    xs = [(x - vbx) / vbw * iw for x, _ in pts]
    ys = [(y - vby) / vbh * ih for _, y in pts]
    x0 = max(0, int(min(xs)) - 1)
    y0 = max(0, int(min(ys)) - 1)
    x1 = min(iw, int(max(xs)) + 1)
    y1 = min(ih, int(max(ys)) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = img.crop((x0, y0, x1, y1))
    if upscale != 1:
        crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    return crop

def ocr_text(crop: Image.Image):
    """Run OCR, return concatenated detected strings."""
    arr = crop
    # paddleocr 3.x .ocr or .predict?
    ocr = get_ocr()
    # Save then call predict on path (more stable across versions)
    buf = io.BytesIO()
    arr.save(buf, format="PNG")
    tmpp = "/tmp/_crop.png"
    with open(tmpp, "wb") as f:
        f.write(buf.getvalue())
    try:
        result = ocr.predict(tmpp)
    except AttributeError:
        result = ocr.ocr(tmpp)
    texts = []
    # Result format varies between versions; try a few shapes.
    def harvest(obj):
        if isinstance(obj, dict):
            if "rec_texts" in obj:
                texts.extend(obj["rec_texts"])
                return
            for v in obj.values():
                harvest(v)
        elif isinstance(obj, list):
            for v in obj:
                harvest(v)
        elif isinstance(obj, tuple):
            # (text, score) common shape
            if len(obj) >= 1 and isinstance(obj[0], str):
                texts.append(obj[0])
    harvest(result)
    return " ".join(t for t in texts if t).strip()

# ── resolution ────────────────────────────────────────────────────────────
def preclean(s):
    """Strip diagram artifacts: (EX), (ABS), (OPT), leading *, leading periods."""
    s = re.sub(r"\([A-Z]{1,4}\)", " ", s)   # drop (EX), (ABS), (OPT) markers
    s = re.sub(r"[*\[\]]", " ", s)          # drop *, [, ]
    return s.strip()

def clean(s): return re.sub(r"[^a-z0-9]", "", preclean(s).lower())

def schema_primary_entity(schema, per_schema):
    """Return the synthetic anchor used when a polygon represents a whole schema.
    ARM schema → required_am_arms; MIM schema → short_listing; plain resource schema → None
    (canonical is just the bare schema name, no entity suffix)."""
    s = schema.lower()
    if s.endswith("_arm"):
        return "required_am_arms"
    if s.endswith("_mim"):
        return "short_listing"
    return None  # bare schema reference

def resolve(ocr_str, current_schema, dotless, by_name, per_schema, catalog,
            polygon_num=None):
    """Return (canonical, score, method)."""
    # 0) Page-reference diagram: OCR is a coordinate marker like "2,10(3)" or "5,9(2)".
    # Canonical target is "<current_schema>.<polygon_num>".
    if (re.search(r"\d+\s*,\s*\d+\s*\(\s*\d+\s*\)", ocr_str or "") and
            polygon_num is not None and current_schema):
        return (f"{current_schema}.{polygon_num}", 100, "page-reference")

    cleaned = clean(ocr_str)
    if not cleaned:
        return (None, 0, "empty")

    # Build local candidate pool: own schema's decls + each USE/REFERENCE schema's decls,
    # plus the schema names themselves (so a box labeled with a schema name resolves).
    candidates = []                     # list of (schema, entity_name)
    schema_names = []                   # list of schema names in scope (own + imports)
    if current_schema in per_schema:
        schema_names.append(current_schema)
        for n in per_schema[current_schema]["own"]:
            candidates.append((current_schema, n))
        for u in per_schema[current_schema]["uses"]:
            schema_names.append(u)
            if u in per_schema:
                for n in per_schema[u]["own"]:
                    candidates.append((u, n))

    # 1) exact concat (Schema+Entity)
    for sc, n in candidates:
        if (sc + n).lower() == cleaned:
            return (f"{sc}.{n}", 100, "exact-local-concat")

    # 2) cleaned matches a schema name in scope -> map to its primary entity
    for sc in schema_names:
        if clean(sc) == cleaned:
            ent = schema_primary_entity(sc, per_schema)
            return (f"{sc}.{ent}" if ent else sc, 100, "schema->primary")

    # 3) exact entity-name in local pool
    name_to_full = {}
    for sc, n in candidates:
        name_to_full.setdefault(n.lower(), []).append((sc, n))
    if cleaned in name_to_full:
        sc, n = name_to_full[cleaned][0]
        return (f"{sc}.{n}", 100, "exact-name-local")

    # 4) prefix/suffix: cleaned starts with a schema name (multiline OCR reading "SchemaName Entity")
    for sc in sorted(schema_names, key=lambda s: len(clean(s)), reverse=True):
        sc_clean = clean(sc)
        if not sc_clean: continue
        if cleaned.startswith(sc_clean):
            tail = cleaned[len(sc_clean):]
            if not tail:
                ent = schema_primary_entity(sc, per_schema)
                return (f"{sc}.{ent}" if ent else sc, 99, "schema-prefix-only")
            else:
                # find entity in that schema whose cleaned name == tail (or fuzzy)
                if sc in per_schema:
                    own_clean = {clean(n): n for n in per_schema[sc]["own"]}
                    if tail in own_clean:
                        return (f"{sc}.{own_clean[tail]}", 100, "schema-prefix-exact-tail")
                    m = process.extractOne(tail, list(own_clean.keys()), scorer=fuzz.ratio,
                                           score_cutoff=80)
                    if m:
                        return (f"{sc}.{own_clean[m[0]]}", m[1], "schema-prefix-fuzzy-tail")

    # 3b) global schema name exact match (e.g., 'action_schema')
    for sc in per_schema.keys():
        if clean(sc) == cleaned:
            ent = schema_primary_entity(sc, per_schema)
            return (f"{sc}.{ent}" if ent else sc, 98, "schema->primary-global")

    # 4b) global schema-prefix fallback — many diagrams reference schemas
    # that are not in the local USE FROM list (transitive imports).
    for sc in sorted(per_schema.keys(), key=lambda s: len(clean(s)), reverse=True):
        sc_clean = clean(sc)
        if not sc_clean or len(sc_clean) < 8: continue   # avoid spurious tiny matches
        if cleaned.startswith(sc_clean):
            tail = cleaned[len(sc_clean):]
            if not tail:
                ent = schema_primary_entity(sc, per_schema)
                return (f"{sc}.{ent}" if ent else sc, 95, "schema-prefix-only-global")
            else:
                own_clean = {clean(n): n for n in per_schema[sc]["own"]}
                if tail in own_clean:
                    return (f"{sc}.{own_clean[tail]}", 100, "schema-prefix-exact-tail-global")
                m = process.extractOne(tail, list(own_clean.keys()), scorer=fuzz.ratio,
                                       score_cutoff=80)
                if m:
                    return (f"{sc}.{own_clean[m[0]]}", m[1], "schema-prefix-fuzzy-tail-global")

    # 5) fuzzy local-pool (concat or name-only)
    pool_concat = {f"{sc}.{n}": (sc + n).lower() for sc, n in candidates}
    pool_name = {f"{sc}.{n}": n.lower() for sc, n in candidates}
    pool_schema = {f"__schema__{sc}": sc.lower() for sc in schema_names}
    best = None
    for label, pool in [("fuzzy-local-concat", pool_concat),
                        ("fuzzy-local-name",   pool_name),
                        ("fuzzy-local-schema", pool_schema)]:
        if not pool: continue
        m = process.extractOne(cleaned, list(pool.values()), scorer=fuzz.ratio)
        if not m: continue
        score, idx = m[1], m[2]
        if best is None or score > best[1]:
            key = list(pool.keys())[idx]
            if label == "fuzzy-local-schema":
                sc = key[len("__schema__"):]
                ent = schema_primary_entity(sc, per_schema)
                if ent:
                    best = (f"{sc}.{ent}", score, label)
            else:
                best = (key, score, label)

    if best and best[1] >= 70:
        return best

    return (None, 0, "no-match")

# ── main ──────────────────────────────────────────────────────────────────
def main():
    print("Building catalog from .exp files...", file=sys.stderr)
    catalog, dotless, by_name, per_schema = build_catalog()
    print(f"  {len(catalog)} declarations across {len(per_schema)} schemas",
          file=sys.stderr)

    # Pick modules from the PR diff, round-robin by first letter, until we hit
    # the target polygon count.
    TARGET_POLYGONS = int(os.environ.get("TARGET_POLYGONS", "300"))
    diff = subprocess.check_output(
        ["git", "-C", str(REPO), "diff", "main..pr689", "--name-only",
         "--", "schemas/modules/*/arm.exp", "schemas/modules/*/mim.exp"],
        text=True,
    )
    all_paths = sorted(set(diff.strip().splitlines()))
    by_letter = defaultdict(list)
    for p in all_paths:
        first = Path(p).parts[2][0].lower()  # schemas/modules/<name>/...
        by_letter[first].append(p)
    letters = sorted(by_letter.keys())
    print(f"Letters in PR: {letters}", file=sys.stderr)
    print(f"  module counts: " + ", ".join(f"{L}:{len(by_letter[L])//2}" for L in letters),
          file=sys.stderr)
    # Round-robin
    idxs = {L: 0 for L in letters}
    paths = []
    while True:
        picked_this_round = False
        for L in letters:
            if idxs[L] < len(by_letter[L]):
                paths.append(by_letter[L][idxs[L]])
                idxs[L] += 1
                picked_this_round = True
        if not picked_this_round:
            break  # exhausted
        # rough polygon estimate: ~2.5 per .exp file; stop early-ish
        if len(paths) * 2.5 >= TARGET_POLYGONS * 1.3:
            break
    print(f"Processing up to {len(paths)} .exp files (target: {TARGET_POLYGONS} polys)",
          file=sys.stderr)

    rows = []
    correct = wrong = missing = no_truth = 0
    per_letter = defaultdict(lambda: [0, 0, 0])  # [correct, wrong, missing]
    for ep in paths:
        if correct + wrong + missing >= TARGET_POLYGONS:
            break
        epath = REPO / ep
        gt = extract_groundtruth(epath)
        if not gt: continue
        letter = Path(ep).parts[2][0].lower()
        for svg_name, num_to_ref in gt.items():
            svg_path = epath.parent / f"{svg_name}.svg"
            if not svg_path.exists(): continue
            try:
                img, vb, polys = parse_svg(svg_path)
            except Exception as e:
                print(f"  parse fail {svg_path}: {e}", file=sys.stderr)
                continue
            if img is None: continue
            schema = parse_exp(epath)[0]
            for num, pts in polys:
                truth = num_to_ref.get(num)
                crop = crop_for_polygon(img, vb, pts, upscale=4)
                if crop is None:
                    rows.append((svg_path.name, num, "", "(empty)", truth, 0, "no-crop", letter))
                    continue
                txt = ocr_text(crop)
                pred, score, method = resolve(
                    txt, schema, dotless, by_name, per_schema, catalog,
                    polygon_num=num)
                ok = (pred is not None and truth is not None and
                      pred.lower() == truth.lower())
                if truth is None:
                    no_truth += 1
                elif ok:
                    correct += 1
                    per_letter[letter][0] += 1
                elif pred is None:
                    missing += 1
                    per_letter[letter][2] += 1
                else:
                    wrong += 1
                    per_letter[letter][1] += 1
                rows.append((str(svg_path.relative_to(REPO)), num, txt, pred, truth, score, method, letter))
                if (correct + wrong + missing) % 25 == 0:
                    print(f"  progress: {correct+wrong+missing} polygons "
                          f"({correct} OK, {wrong} ERR, {missing} MISS)", file=sys.stderr)

    # Per-letter summary
    print()
    print("Per-letter accuracy:")
    print(f"  {'letter':<6} {'OK':>5} {'ERR':>5} {'MISS':>5} {'total':>6} {'pct':>6}")
    for L in sorted(per_letter.keys()):
        c, w, m = per_letter[L]
        t = c + w + m
        pct = 100 * c / t if t else 0
        print(f"  {L:<6} {c:>5} {w:>5} {m:>5} {t:>6} {pct:>5.1f}%")

    # Method-level summary (which resolution path produced correct vs wrong)
    method_stats = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        svg, num, txt, pred, truth, score, method, letter = r
        if truth is None: continue
        ok = (pred is not None and pred.lower() == truth.lower())
        if ok: method_stats[method][0] += 1
        elif pred is None: method_stats[method][2] += 1
        else: method_stats[method][1] += 1
    print()
    print("Per-method accuracy:")
    print(f"  {'method':<32} {'OK':>5} {'ERR':>5} {'MISS':>5} {'total':>6} {'pct':>6}")
    for m_name in sorted(method_stats, key=lambda k: -sum(method_stats[k])):
        c, w, mm = method_stats[m_name]
        t = c + w + mm
        pct = 100 * c / t if t else 0
        print(f"  {m_name:<32} {c:>5} {w:>5} {mm:>5} {t:>6} {pct:>5.1f}%")

    # Sample of errors (first 30)
    print()
    print("Sample of errors (first 30):")
    print(f"  {'svg':<60} {'#':>2} {'OCR':<40} {'predicted':<50} {'truth':<50}")
    err_rows = [r for r in rows if r[4] is not None and
                (r[3] is None or r[3].lower() != r[4].lower())]
    for r in err_rows[:30]:
        svg, num, txt, pred, truth, score, method, letter = r
        print(f"  {svg:<60} {num:>2} {(txt or '')[:40]:<40} {(pred or '-')[:50]:<50} {(truth or '-')[:50]:<50}")

    total = correct + wrong + missing
    print()
    print(f"Total polygons evaluated: {total}")
    if total:
        print(f"  correct:  {correct} ({100*correct/total:.1f}%)")
        print(f"  wrong:    {wrong} ({100*wrong/total:.1f}%)")
        print(f"  missing:  {missing} ({100*missing/total:.1f}%)")

if __name__ == "__main__":
    main()
