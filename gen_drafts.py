#!/usr/bin/env python3.12
"""
Generate draft [.svgmap] blocks for PR #689 modules (letters q-z).

Scope: schemas/modules/<letter>*/{arm,mim}.exp with diagrams named
{arm,mim}expg<N>.svg. Diagrams without hotspots get an image-only block
(matching the convention in the committed a-p blocks). SVG-only asset
directories (no arm.exp/mim.exp) are skipped and reported.

Output (per module, resumable):
  drafts-qz/<module>/<kind>.svgmap.txt   ready-to-insert block text
  drafts-qz/<module>/<kind>.rows.json    per-entry OCR/resolution detail

Usage:
  ISO10303_REPO=/path/to/worktree python3.12 gen_drafts.py q          # one letter
  ISO10303_REPO=/path/to/worktree python3.12 gen_drafts.py q-z        # range
  ISO10303_REPO=... python3.12 gen_drafts.py q-z 2/6                  # shard 2 of 6
  ISO10303_REPO=... python3.12 gen_drafts.py mod_a,mod_b              # explicit
      module directory names (selector containing '_' or ',')
  ISO10303_REPO=... python3.12 gen_drafts.py --reresolve              # re-run
      resolution + drafts from the OCR text cached in rows.json (no OCR)
Shards partition the in-scope module list round-robin; per-module output
files make the run resumable, so shards never conflict.

Env: DRAFTS_OUT names the output directory (default drafts-qz);
KINDS restricts the schema kinds processed (default arm,mim) so one
module's arm and mim can run as parallel processes.
"""
import io, json, os, re, sys
from pathlib import Path

SELF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SELF_DIR))
import sim_pipeline as sp
from lxml import etree
from PIL import Image
from rapidfuzz import process, fuzz

REPO = sp.REPO
OUT = SELF_DIR / os.environ.get("DRAFTS_OUT", "drafts-qz")
KINDS = tuple(k for k in os.environ.get("KINDS", "arm,mim").split(",") if k)
TMP_CROP = os.environ.get("CROP_TMP", "/tmp") + f"/_gen_drafts_crop_{os.getpid()}.png"

NSL = lambda el: etree.QName(el).localname

# Flag any resolution that is not an exact/convention match.
CLEAN_METHODS = {
    "exact-local-concat", "exact-name-local", "exact-name-local-clean",
    "qualified-verbatim", "page-reference",
    "schema-prefix-exact-tail", "schema-prefix-exact-tail-global",
}
# schema->primary carries the known ambiguity class (required_am_arms /
# short_listing / bare schema): always listed in review, severity "convention".
CONVENTION_METHODS = {
    "schema->primary", "schema->primary-global",
    "schema-prefix-only", "schema-prefix-only-global",
}


# ── interface (USE/REFERENCE FROM) closure — candidate generation only ─────
USE_FROM = re.compile(
    r"\b(?:USE|REFERENCE)\s+FROM\s+(\w+)\s*(\(([^;]*?)\))?\s*;",
    re.IGNORECASE | re.DOTALL)


class Ctx:
    """Catalog + derived indexes shared by the resolution chain."""

    def __init__(self):
        print("Building catalog...", file=sys.stderr)
        (self.catalog, self.dotless, self.by_name,
         self.per_schema) = sp.build_catalog()
        print(f"  {len(self.catalog)} declarations across "
              f"{len(self.per_schema)} schemas", file=sys.stderr)
        # clean(schema) -> schema
        self.schema_by_clean = {sp.clean(s): s for s in self.per_schema}
        # clean(name) -> sorted declared-case names
        idx = {}
        for cands in self.by_name.values():
            for c in cands:
                n = c.split(".", 1)[1]
                idx.setdefault(sp.clean(n), set()).add(n)
        self.name_by_clean = {k: sorted(v) for k, v in idx.items()}
        # schema -> [(source, [visible items] | None)]
        self.interfaces = {}
        for sc, info in self.per_schema.items():
            text = Path(info["file"]).read_text(errors="replace")
            text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.DOTALL)
            imps = []
            for m in USE_FROM.finditer(text):
                src, _, items = m.groups()
                names = None
                if items:
                    names = [re.sub(r".*\bAS\s+", "", it.strip(),
                                    flags=re.IGNORECASE)
                             for it in items.split(",") if it.strip()]
                imps.append((src, names))
            self.interfaces[sc] = imps
        self._closure = {}

    def visible_names(self, sc, _stack=None):
        """Names visible in schema sc: own declarations plus USE/REFERENCE
        FROM items, transitively. Heuristic candidate pool for OCR matching,
        not an authoritative EXPRESS interface closure."""
        if sc in self._closure:
            return self._closure[sc]
        _stack = _stack or set()
        if sc in _stack or sc not in self.per_schema:
            return set()
        _stack.add(sc)
        names = set(self.per_schema[sc]["own"])
        for src, items in self.interfaces.get(sc, []):
            if items is not None:
                names.update(items)
            else:
                names.update(self.visible_names(src, _stack))
        _stack.discard(sc)
        self._closure[sc] = names
        return names


# ── resolution chain ────────────────────────────────────────────────────────
def resolve_local_exact(txt, schema, ctx):
    """Clean-exact match over the local candidate pool (own schema first,
    imports second). sim_pipeline's exact-name index keys on n.lower()
    (underscores kept) while the OCR string is cleaned to [a-z0-9], so
    'value qualifier' misses 'value_qualifier' and lands in fuzzy."""
    cleaned = sp.clean(txt)
    if not cleaned or schema not in ctx.per_schema:
        return None
    pools = [(schema, ctx.per_schema[schema]["own"])]
    pools += [(u, ctx.per_schema[u]["own"])
              for u in ctx.per_schema[schema]["uses"] if u in ctx.per_schema]
    for sc, names in pools:
        hits = [n for n in names if sp.clean(n) == cleaned]
        if len(hits) == 1:
            return (f"{sc}.{hits[0]}", 100, "exact-name-local-clean")
        if len(hits) > 1:
            return None
    return None


def resolve_qualified(txt, ctx):
    """Diagram labels of the form '<Schema>.<name>' (or '<Schema> <name>'
    with the dot lost by OCR) where the name is interfaced via USE FROM, not
    declared locally — sim_pipeline's declaration catalog misses these.
    Convention per the committed a-p blocks: transcribe the qualified label
    as the diagram shows it.

    The schema part itself is OCR-corrupted on AP overview diagrams
    ('_arm' read as 'amm'/'anm'/'am', doubled letters), so exact prefix
    matching alone strands hundreds of boxes per module: after the exact
    paths fail, the schema is matched fuzzily (cutoff 90, dotted left part
    or a head slice of the dotless text). Any fuzzy-schema resolution
    returns a method outside CLEAN_METHODS so it always classifies as
    'check', and it stands only if the remaining tail also resolves."""
    if not txt:
        return None
    schema = tail_txt = None
    fuzzy_schema = 0  # ratio when the schema part matched fuzzily
    if "." in txt:
        left, right = txt.split(".", 1)
        schema = ctx.schema_by_clean.get(sp.clean(left))
        tail_txt = right
        if schema is None:
            lc = sp.clean(left)
            if len(lc) >= 8:
                m = process.extractOne(lc, list(ctx.schema_by_clean),
                                       scorer=fuzz.ratio, score_cutoff=90)
                if m:
                    schema = ctx.schema_by_clean[m[0]]
                    fuzzy_schema = int(m[1])
                    tail_txt = right
    if schema is None:
        # dot lost by OCR: longest schema whose clean form prefixes the text
        cleaned = sp.clean(txt)
        for sc_clean in sorted(ctx.schema_by_clean, key=len, reverse=True):
            if len(sc_clean) >= 8 and cleaned.startswith(sc_clean) \
                    and len(cleaned) > len(sc_clean):
                schema = ctx.schema_by_clean[sc_clean]
                tail_txt = cleaned[len(sc_clean):]
                break
    if schema is None:
        # dot lost AND schema part corrupted: fuzzy head-slice split
        cleaned = sp.clean(txt)
        best = None
        for sc_clean, sc in ctx.schema_by_clean.items():
            L = len(sc_clean)
            if L < 8 or len(cleaned) < L - 1:
                continue
            for k in range(max(6, L - 2), min(len(cleaned) - 1, L + 2) + 1):
                s = fuzz.ratio(cleaned[:k], sc_clean)
                if s >= 90 and (best is None or s > best[0]):
                    best = (s, sc, cleaned[k:])
        if best:
            fuzzy_schema, schema, tail_txt = int(best[0]), best[1], best[2]
    if schema is None:
        return None
    rc = sp.clean(tail_txt)
    if not rc:
        return None
    # names visible in the schema (own + USE FROM closure) take priority;
    # a global-only hit keeps the diagram's schema but stays flagged
    closure_hits = {n for n in ctx.visible_names(schema) if sp.clean(n) == rc}
    if closure_hits:
        if fuzzy_schema:
            return (f"{schema}.{sorted(closure_hits)[0]}", fuzzy_schema,
                    "qualified-fuzzy-schema")
        return (f"{schema}.{sorted(closure_hits)[0]}", 100, "qualified-verbatim")
    global_hits = set(ctx.name_by_clean.get(rc, []))
    if global_hits:
        if fuzzy_schema:
            return (f"{schema}.{sorted(global_hits)[0]}", fuzzy_schema,
                    "qualified-fuzzy-schema-global")
        return (f"{schema}.{sorted(global_hits)[0]}", 100,
                "qualified-verbatim-global")
    pool = sorted(ctx.visible_names(schema))
    if pool:
        m = process.extractOne(rc, [sp.clean(n) for n in pool],
                               scorer=fuzz.ratio, score_cutoff=80)
        if m:
            return (f"{schema}.{pool[m[2]]}",
                    min(int(m[1]), fuzzy_schema or 100), "qualified-fuzzy")
    return None


def resolve_chain(txt, schema, ctx, polygon_num):
    r = resolve_local_exact(txt, schema, ctx)
    if r:
        return r
    # page references first (sp.resolve puts them ahead of everything)
    if re.search(r"\d+\s*,\s*\d+\s*\(\s*\d+\s*\)", txt or "") and schema:
        return (f"{schema}.{polygon_num}", 100, "page-reference")
    # inter-page reference boxes carry a 'page,ref' coordinate prefix before
    # the referenced name ('4,1 risk_communication_select') — strip and retry
    m = re.match(r"\s*\d+\s*[.,]\s*\d+\s+(.*[A-Za-z].*)", txt or "")
    if m:
        r = resolve_local_exact(m.group(1), schema, ctx) \
            or resolve_qualified(m.group(1), ctx)
        if r:
            return r
    # letterless OCR is a page-reference marker; a clear 'page,ref' pair is
    # trusted, bare digits stay flagged for review via the non-clean method
    if txt and schema and not re.search(r"[A-Za-z]", txt):
        if re.search(r"\d+\s*[.,]\s*\d+", txt):
            return (f"{schema}.{polygon_num}", 100, "page-reference")
        return (f"{schema}.{polygon_num}", 90, "page-reference-numeric")
    r = resolve_qualified(txt, ctx)
    if r:
        return r
    return sp.resolve(txt, schema, ctx.dotless, ctx.by_name, ctx.per_schema,
                      ctx.catalog, polygon_num=polygon_num)


def classify(pred, score, method):
    if pred is None:
        return "UNRESOLVED"
    if method in CONVENTION_METHODS:
        return "convention"
    if method in CLEAN_METHODS and score >= 99:
        return ""
    return "check"


def verify_ref(ref, ctx):
    """Static check: ref must be a declared or interfaced name, a bare
    schema, or a toolchain section/page anchor."""
    if ref is None:
        return False
    if "." not in ref:
        return ref in ctx.per_schema
    sc, ent = ref.split(".", 1)
    if ent in ("required_am_arms", "short_listing") or ent.isdigit():
        return sc in ctx.per_schema
    if f"{sc}.{ent}" in ctx.catalog:
        return True
    return sc in ctx.per_schema and ent in ctx.visible_names(sc)


# ── svg parsing / ocr ───────────────────────────────────────────────────────
def parse_svg_shapes(svg_path: Path, decode_img=True):
    """Return (PIL.Image|None, viewbox, {number: [pts,...]}) — polygons AND rects."""
    root = etree.parse(str(svg_path)).getroot()
    vb = tuple(float(x) for x in root.get("viewBox", "0 0 100 100").split())
    img = None
    if decode_img:
        for el in root.iter():
            if NSL(el) == "image":
                href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href")
                if href and href.startswith("data:image/"):
                    import base64
                    img = Image.open(io.BytesIO(
                        base64.b64decode(href.split(",", 1)[1]))).convert("RGB")
                    break
    shapes = {}
    for a in root.iter():
        if NSL(a) != "a":
            continue
        href = a.get("href") or a.get("{http://www.w3.org/1999/xlink}href")
        if not href or not href.isdigit():
            continue
        for el in a.iter():
            pts = None
            if NSL(el) == "polygon":
                nums = re.findall(r"-?\d+(?:\.\d+)?", el.get("points", ""))
                pts = [(float(nums[i]), float(nums[i + 1]))
                       for i in range(0, len(nums) - 1, 2)]
            elif NSL(el) == "rect":
                try:
                    x, y = float(el.get("x", 0)), float(el.get("y", 0))
                    w, h = float(el.get("width")), float(el.get("height"))
                except (TypeError, ValueError):
                    continue
                pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            if pts:
                shapes.setdefault(href, []).append(pts)
    return img, vb, shapes


def largest_shape(pts_list):
    def area(pts):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))
    return max(pts_list, key=area)


def diagram_class(svg_path: Path):
    """Classify a diagram's hotspot health; returns (class, dup_numbers).

    'all-identical'  n>1 anchors all sharing one geometry: a placeholder
                     ('Special case') image. Committed convention: single
                     entry, highest number, module's own primary anchor.
    'broken-coords'  most shape centers fall outside the viewBox (source
                     conversion defect, e.g. requirement_management
                     armexpg3): hotspots unusable, image-only block.
    'healthy'        otherwise; dup_numbers lists anchor numbers that share
                     their geometry with another number (review hint)."""
    _, vb, shapes = parse_svg_shapes(svg_path, decode_img=False)
    if not shapes:
        return "healthy", []
    sig = {}
    for num, pts_list in shapes.items():
        pts = largest_shape(pts_list)
        sig[num] = tuple(sorted(pts))
    n, d = len(sig), len(set(sig.values()))
    if n > 1 and d == 1:
        return "all-identical", sorted(sig, key=int)
    vbx, vby, vbw, vbh = vb
    outside = 0
    for num, pts_list in shapes.items():
        pts = largest_shape(pts_list)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        if not (vbx <= cx <= vbx + vbw and vby <= cy <= vby + vbh):
            outside += 1
    if outside / n > 0.5:
        return "broken-coords", []
    from collections import Counter
    counts = Counter(sig.values())
    dups = sorted((num for num, s in sig.items() if counts[s] > 1), key=int)
    return "healthy", dups


def ocr_crop(crop: Image.Image) -> str:
    crop.save(TMP_CROP, format="PNG")
    ocr = sp.get_ocr()
    try:
        result = ocr.predict(TMP_CROP)
    except AttributeError:
        result = ocr.ocr(TMP_CROP)
    texts = []
    def harvest(obj):
        if isinstance(obj, dict):
            if "rec_texts" in obj:
                texts.extend(obj["rec_texts"]); return
            for v in obj.values(): harvest(v)
        elif isinstance(obj, list):
            for v in obj: harvest(v)
        elif isinstance(obj, tuple):
            if len(obj) >= 1 and isinstance(obj[0], str):
                texts.append(obj[0])
    harvest(result)
    return " ".join(t for t in texts if t).strip()


# ── output ──────────────────────────────────────────────────────────────────
def block_text(schema, svg_stem, entries):
    lines = [f'(*"{schema}.__expressg"', "[.svgmap]", "====",
             f"image::{svg_stem}.svg[]"]
    if entries:
        lines.append("")
        for num, ref in entries:
            lines.append(f"* <<express:{ref}>>; {num}")
    lines += ["====", "*)"]
    return "\n".join(lines) + "\n"


def module_svgs(mod: Path, kind: str):
    return sorted(mod.glob(f"{kind}expg[0-9]*.svg"),
                  key=lambda p: int(re.search(r"(\d+)\.svg$", p.name).group(1)))


def in_scope_modules(letters):
    all_dirs = sorted(p for p in (REPO / "schemas/modules").iterdir()
                      if p.is_dir() and p.name[0].lower() in letters)
    skipped = [p.name for p in all_dirs
               if not (p / "arm.exp").exists() and not (p / "mim.exp").exists()]
    return [p for p in all_dirs if p.name not in skipped], skipped


def primary_ref(schema, ctx):
    ent = sp.schema_primary_entity(schema, ctx.per_schema)
    return f"{schema}.{ent}" if ent else schema


def write_drafts(mod: Path, kind: str, schema, rows, outdir: Path, ctx):
    """Rebuild <kind>.svgmap.txt from resolution rows (includes image-only
    blocks for diagrams without hotspots, single-primary-entry blocks for
    all-identical placeholders, image-only blocks for broken hotspots)."""
    by_svg = {}
    for r in rows:
        by_svg.setdefault(r["svg"], {})[r["num"]] = r
    blocks = []
    for svg in module_svgs(mod, kind):
        cls, _ = diagram_class(svg)
        _, _, shapes = parse_svg_shapes(svg, decode_img=False)
        if cls == "broken-coords" or not shapes:
            entries = []
        elif cls == "all-identical":
            entries = [(max(shapes, key=int), primary_ref(schema, ctx))]
        else:
            entries = []
            for num in sorted(shapes, key=int):
                r = by_svg.get(svg.name, {}).get(num)
                ref = (r and r["ref"]) or "UNRESOLVED"
                entries.append((num, ref))
        blocks.append(block_text(schema, svg.stem, entries))
    (outdir / f"{kind}.svgmap.txt").write_text("\n".join(blocks))


# ── main: OCR run ───────────────────────────────────────────────────────────
def run_ocr(sel, shard):
    explicit = None
    if "_" in sel or "," in sel:
        explicit = [s for s in sel.split(",") if s]
    elif "-" in sel:
        lo, hi = sel.split("-")
        letters = {chr(c) for c in range(ord(lo), ord(hi) + 1)}
    else:
        letters = set(sel)
    shard_i, shard_n = 0, 1
    if shard and "/" in shard:
        shard_i, shard_n = (int(x) for x in shard.split("/"))

    if explicit is not None:
        dirs = [REPO / "schemas/modules" / n for n in explicit]
        missing = [p.name for p in dirs if not p.is_dir()]
        if missing:
            sys.exit(f"unknown module dir(s): {', '.join(missing)}")
        skipped_asset_dirs = [p.name for p in dirs
                              if not (p / "arm.exp").exists()
                              and not (p / "mim.exp").exists()]
        eligible = [p for p in dirs if p.name not in skipped_asset_dirs]
    else:
        eligible, skipped_asset_dirs = in_scope_modules(letters)
    ctx = Ctx()
    OUT.mkdir(exist_ok=True)
    mod_dirs = [p for i, p in enumerate(eligible) if i % shard_n == shard_i]
    print(f"Shard {shard_i}/{shard_n}: {len(mod_dirs)} of {len(eligible)} modules",
          file=sys.stderr)
    total_entries = 0
    for mod in mod_dirs:
        for kind in KINDS:
            exp = mod / f"{kind}.exp"
            if not exp.exists():
                continue
            outdir = OUT / mod.name
            rows_f = outdir / f"{kind}.rows.json"
            if rows_f.exists():
                print(f"  skip (done): {mod.name}/{kind}", file=sys.stderr)
                continue
            svgs = module_svgs(mod, kind)
            if not svgs:
                continue
            schema = sp.parse_exp(exp)[0]
            if not schema:
                print(f"  !! no SCHEMA in {exp}", file=sys.stderr)
                continue
            rows = []
            for svg in svgs:
                img, vb, shapes = parse_svg_shapes(svg)
                for num in sorted(shapes, key=int):
                    txt, pred, score, method = "", None, 0, "no-image"
                    if img is not None:
                        crop = sp.crop_for_polygon(
                            img, vb, largest_shape(shapes[num]), upscale=4)
                        if crop is not None:
                            txt = ocr_crop(crop)
                            pred, score, method = resolve_chain(
                                txt, schema, ctx, num)
                        else:
                            method = "no-crop"
                    flag = classify(pred, score, method)
                    if pred is not None and not verify_ref(pred, ctx):
                        flag = (flag + "+unverified").lstrip("+")
                    rows.append({"module": mod.name, "kind": kind,
                                 "svg": svg.name, "num": num, "ocr": txt,
                                 "ref": pred, "score": score,
                                 "method": method, "flag": flag})
                print(f"    {mod.name}/{kind} {svg.name}: "
                      f"{len(shapes)} anchors done", file=sys.stderr)
            outdir.mkdir(exist_ok=True)
            write_drafts(mod, kind, schema, rows, outdir, ctx)
            rows_f.write_text(json.dumps(rows, indent=1))
            total_entries += len(rows)
            nflag = sum(1 for r in rows if r["flag"] and r["flag"] != "convention")
            print(f"  {mod.name}/{kind}: {len(svgs)} diagrams, "
                  f"{len(rows)} entries, {nflag} flagged  "
                  f"[running total {total_entries}]", file=sys.stderr)
    if skipped_asset_dirs:
        print("Skipped SVG-only asset dirs (no arm/mim.exp): "
              + ", ".join(skipped_asset_dirs), file=sys.stderr)
    print("DONE", file=sys.stderr)


# ── main: re-resolve from cached OCR (no OCR run) ───────────────────────────
def run_reresolve():
    ctx = Ctx()
    changed = total = 0
    for rows_f in sorted(OUT.glob("*/*.rows.json")):
        mod = REPO / "schemas/modules" / rows_f.parent.name
        kind = rows_f.stem.split(".")[0]
        exp = mod / f"{kind}.exp"
        schema = sp.parse_exp(exp)[0]
        rows = json.loads(rows_f.read_text())
        svg_meta = {}
        for svg in module_svgs(mod, kind):
            svg_meta[svg.name] = diagram_class(svg)
        for r in rows:
            total += 1
            cls, dups = svg_meta.get(r["svg"], ("healthy", []))
            if cls == "all-identical":
                r.update(ref=None, score=0, method="placeholder-diagram",
                         flag="degenerate")
                continue
            if cls == "broken-coords":
                r.update(ref=None, score=0, method="broken-svg-coords",
                         flag="broken-svg")
                continue
            if r["method"] in ("no-image", "no-crop"):
                continue
            pred, score, method = resolve_chain(r["ocr"], schema, ctx, r["num"])
            flag = classify(pred, score, method)
            if pred is not None and not verify_ref(pred, ctx):
                flag = (flag + "+unverified").lstrip("+")
            if r["num"] in dups:
                flag = (flag + "+dup-geom").lstrip("+")
            if (pred, method) != (r["ref"], r["method"]):
                changed += 1
            r.update(ref=pred, score=score, method=method, flag=flag)
        rows_f.write_text(json.dumps(rows, indent=1))
        write_drafts(mod, kind, schema, rows, rows_f.parent, ctx)
    print(f"re-resolved {total} rows, {changed} changed", file=sys.stderr)


if __name__ == "__main__":
    if "--reresolve" in sys.argv:
        run_reresolve()
    else:
        run_ocr(sys.argv[1] if len(sys.argv) > 1 else "q-z",
                sys.argv[2] if len(sys.argv) > 2 else None)
