"""STEP 7 - verification: independent, automatic checks that a generated page is what its label claims.

Per page (reads the saved artifacts, so it can run on any finished run):
  content   facts_present        every required fact appears verbatim in the text
            amount_words_parse   the Hindi words in the deed are parsed BACK to a number and must equal the entity amount
            amount_digits        the amount's digits (Indian grouping, deed numeral style) appear in the text
            labels_match_text    scored label words == transcript_scored; body words == the written paragraphs
  layout    fill_in_range        text fills the configured share of the usable area; fit status ok
            boxes_in_page        step-3 word boxes inside the page; no overlapping words on a line
  compose   composition_valid    asset files referenced exist; elements carry polygons
  damage    folded_and_torn      every page has folds AND a torn edge (required by spec); severity valid
            polygons_valid       all final polygons finite, 4 points, non-degenerate
  alignment boxes_on_ink_target  pixel check: tracked word polygons sit on ink in the aligned clean target (centroid offset + ink density)
            boxes_on_ink_final   same on the degraded image (looser: noise/blur/fade)
An overlay image (green = scored word, orange = occluded, red = invisible/torn, blue = elements) is saved for eyeballing.
`negative_control` shifts every polygon and shows the alignment check FAILS, i.e. the check can actually detect misalignment.
"""
import hashlib, json, re, math
from collections import Counter
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from .common import load_json, dump_json
from .hindi_numbers import _W, indian_group, to_devanagari_digits
from .step1_entities import required_facts

PROCEDURAL = {"text_stamp"}                 # stamps drawn in code, not from an asset file
UNITS = {"करोड़": 10_000_000, "लाख": 100_000, "हज़ार": 1000}


def _nn(s): return s.replace("\u093c", "").replace("ज़", "ज")          # ignore nukta (हज़ार == हजार)


def parse_hindi_number(words: str):
    """Inverse of number_words(): 'एक लाख बीस हज़ार' -> 120000. Leading non-number tokens (e.g. 'अक्षरी') are ignored; None if nothing parses."""
    idx = {_nn(w): i for i, w in enumerate(_W)}; units = {_nn(k): v for k, v in UNITS.items()}
    cur = total = 0; seen = False
    for t in words.split():
        t = _nn(t)
        if t in idx: cur += idx[t]; seen = True
        elif t == "सौ": cur = max(cur, 1) * 100; seen = True
        elif t in units: total += max(cur, 1) * units[t]; cur = 0; seen = True
        elif not seen: continue
        else: return None
    return total + cur if seen else None


def _check(ok, detail=""): return {"pass": bool(ok), "detail": detail}


# ------------------------------------------------------------------ content
def check_content(rec):
    out, txt, ent = {}, rec["transcript"], rec["entities"]
    miss = [f for f in required_facts(ent) if f not in txt]
    out["facts_present"] = _check(not miss, f"missing: {miss[:3]}" if miss else f"{len(required_facts(ent))} facts")
    amt = int(ent["amount"])
    caps = re.findall(r"\(([^()]*?)\s*रुपये मात्र\)", txt)
    vals = [parse_hindi_number(s) for s in caps]
    out["amount_words_parse"] = _check(bool(caps) and all(v == amt for v in vals), f"amount={amt} parsed from words={vals}")
    digs = {indian_group(amt), to_devanagari_digits(indian_group(amt))}
    out["amount_digits"] = _check(any(d in txt for d in digs), f"expected one of {sorted(digs)}")
    words = [w for w in rec["words_all"] if w.get("scored")]
    lab = " ".join(w["text"] for w in words).split(); ref = rec["transcript_scored"].split()
    body_lab = [w["text"] for w in words if w.get("kind") in ("body", "title")]
    body_ref = " ".join(p["text"] if isinstance(p, dict) else p for p in rec["paragraphs"]).split()
    out["labels_match_text"] = _check(Counter(lab) == Counter(ref) and Counter(body_lab) == Counter(body_ref),
                                      f"label words={len(lab)} transcript_scored={len(ref)} body {len(body_lab)}/{len(body_ref)}")
    return out


# ------------------------------------------------------------------ layout
def _poly_overlap(p, q):
    """Overlap area of two convex quadrilaterals as a share of the smaller one."""
    p, q = np.asarray(p, np.float32), np.asarray(q, np.float32)
    area, _ = cv2.intersectConvexConvex(p, q)
    return area / max(1.0, min(cv2.contourArea(p), cv2.contourArea(q)))


def check_layout(rec, cfg):
    out, pg = {}, rec["page"]; lo, hi = cfg["fit"]["fill_lo"], cfg["fit"]["fill_hi"]
    out["fill_in_range"] = _check(rec["status"] == "ok" and lo - 0.02 <= pg["fill"] <= hi + 0.02, f"fill={pg['fill']} want {lo}-{hi} status={rec['status']}")
    W, H = pg["width"], pg["height"]; bad = [w["text"] for w in rec["words"] if w["bbox"][0] < -1 or w["bbox"][1] < -1 or w["bbox"][2] > W + 1 or w["bbox"][3] > H + 1]
    over = 0
    for ln in rec["lines"]:
        ws = sorted((rec["words"][i] for i in ln["words"]), key=lambda w: w["bbox"][0])
        for a, b in zip(ws, ws[1:]):
            if "poly" in a and "poly" in b:     # v2 hand words are tilted: compare the real polygons, not their axis-aligned boxes
                if b["bbox"][0] < a["bbox"][2] and _poly_overlap(a["poly"], b["poly"]) > 0.25: over += 1
            else:
                over += b["bbox"][0] < a["bbox"][2] - 2
    out["boxes_in_page"] = _check(not bad and not over, f"off-page={len(bad)} overlapping={over}")
    return out


def check_compose(rec, lib_names):
    comp = rec["composition"]; used = [comp["paper"]] + comp.get("stamps", [])
    missing = [u for u in used if u not in lib_names and u not in PROCEDURAL]
    noply = [e["type"] for e in rec["elements"] if "poly" not in e]
    return {"composition_valid": _check(not missing and not noply, f"unknown assets={missing} elements without polygon={len(noply)}")}


# ------------------------------------------------------------------ damage
def check_damage(rec, final_size):
    ops = [o["op"] for o in rec["degradation"]["ops"]]; W, H = final_size
    bad = 0
    for it in rec["words_all"] + rec["elements"]:
        p = np.asarray(it["poly"], float)
        if p.shape != (4, 2) or not np.isfinite(p).all() or cv2.contourArea(p.astype(np.float32)) < 1: bad += 1
    return {"folded_and_torn": _check("folds" in ops and "torn_edge" in ops and rec["degradation"]["severity"] in ("light", "medium", "heavy"),
                                      f"ops={len(ops)} severity={rec['degradation']['severity']}"),
            "polygons_valid": _check(bad == 0, f"{bad} bad polygons")}


# ------------------------------------------------------------------ fonts (v2 pages only)
def check_fonts(layout_rec):
    """The page's bundled font file must really have loaded; a failed load silently falls back to another font and the page would be mislabelled."""
    ext = layout_rec["page"].get("ext") or {}
    st = ext.get("fonts_status") or []
    fam, wt = layout_rec["page"]["font"], layout_rec["page"]["weight"]
    mine = [f for f in st if f["family"] == fam]
    ok = bool(mine) and any(f["status"] == "loaded" for f in mine)
    return {"font_file_loaded": _check(ok, f"{fam}: " + ", ".join(f"{f['weight']}={f['status']}" for f in mine) if mine else f"{fam}: no font face found")}


# ------------------------------------------------------------------ pixel alignment
def _ink(img_rgb):
    """Ink mask: pixels clearly darker than the local paper. Threshold adapts to the page contrast (faded/blurred scans)."""
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    paper = cv2.medianBlur(g, 31); diff = paper.astype(np.int16) - g.astype(np.int16)
    contrast = float(np.percentile(diff, 99.5))
    return diff > max(14.0, 0.35 * contrast)


def _ink_text(img_rgb, words):
    """Style-aware ink mask (v2 pages): the contrast reference comes from the body-text boxes themselves instead of the whole page, because stamps
    and signatures are darker than thin or small text and made the page-wide reference too high for faint text."""
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    paper = cv2.medianBlur(g, 31); diff = paper.astype(np.int16) - g.astype(np.int16)
    m = np.zeros(g.shape, np.uint8)
    for w in words:
        if w.get("scored") and w.get("kind") == "body": cv2.fillPoly(m, [np.round(np.asarray(w["poly"])).astype(np.int32)], 1)
    vals = diff[m > 0]
    contrast = float(np.percentile(vals, 97)) if vals.size > 50 else float(np.percentile(diff, 99.5))
    return diff > max(8.0, 0.35 * contrast)


def alignment(img_rgb, words, shift_h=(0.0, 0.0), style_aware=False):
    """Per-word pixel check in each word's own frame (u along the baseline, v across, h = box height).
    The deed's ink must (a) reach both ends of the box (|ink_left - box_left| and |ink_right - box_right| <= 0.25h),
    (b) have its vertical centre of mass inside the middle 60% of the box (fonts differ in where glyphs sit in the line box). Words overlapped/torn/off-frame are skipped.
    `shift_h` moves every polygon by that many box-heights (x, y): the negative control. Returns (pass_rate, n_checked)."""
    ink = _ink_text(img_rgb, words) if style_aware else _ink(img_rgb); H, W = ink.shape; ok = n = 0
    for w in words:
        if not (w.get("scored") and w.get("visible", 1) >= 0.99 and w.get("occluded", 0) <= 0.05): continue
        p = np.asarray(w["poly"], np.float32)
        hh = float(np.linalg.norm(p[3] - p[0])); ww = float(np.linalg.norm(p[1] - p[0]))
        if hh < 6 or ww < 4: continue
        if shift_h != (0, 0): p = p + np.array(shift_h, np.float32) * hh
        if p[:, 0].min() < hh or p[:, 1].min() < hh or p[:, 0].max() > W - hh or p[:, 1].max() > H - hh: continue
        o = p[0]; ux = (p[1] - p[0]) / (ww + 1e-6); vx = (p[3] - p[0]) / (hh + 1e-6)
        x0, y0 = np.floor(p.min(0) - hh).astype(int); x1, y1 = np.ceil(p.max(0) + hh).astype(int)
        ys, xs = np.nonzero(ink[y0:y1, x0:x1]); n += 1
        if len(ys) < 5: continue
        d = np.stack([xs + x0, ys + y0], 1).astype(np.float32) - o; u, v = d @ ux, d @ vx
        vm = 0.1 if w.get("hand") else 0.3      # tall script glyphs on tilted, tightly set lines: the neighbouring line must not leak into the word's window
        sel = (u >= -0.12 * hh) & (u <= ww + 0.12 * hh) & (v >= -vm * hh) & (v <= (1 + vm) * hh)      # this word's column, a little margin
        if sel.sum() < 5: continue
        u, v = u[sel], v[sel]; inside = (u >= 0) & (u <= ww) & (v >= 0) & (v <= hh)
        if inside.sum() < 0.6 * sel.sum(): continue
        lo_v, hi_v = (0.1, 0.9) if w.get("hand") else (0.2, 0.8)     # script fonts (e.g. Amita) put their ink mass higher in the box than print fonts do
        ok += (u.min() <= 0.25 * hh) and (u.max() >= ww - 0.25 * hh) and lo_v * hh <= float(v.mean()) <= hi_v * hh
    return (ok / n if n else None), n


def check_alignment(page_dir, rec, thr_target=0.9, thr_final=0.6, style_aware=False, sfx=""):
    out = {}
    for key, fn, thr in (("boxes_on_ink_target", f"05_target{sfx}.png", thr_target), ("boxes_on_ink_final", f"05_degraded{sfx}.png", thr_final)):
        f = page_dir / fn
        if not f.exists(): out[key] = {"pass": None, "detail": "no image"}; continue
        img = np.asarray(Image.open(f).convert("RGB")); rate, n = alignment(img, rec["words_all"], style_aware=style_aware)
        neg, _ = alignment(img, rec["words_all"], shift_h=(0.4, 0.4), style_aware=style_aware)   # negative control: every box moved 0.4 box-heights
        out[key] = _check(rate is not None and rate >= thr, f"aligned {rate if rate is None else round(rate, 3)} of {n} words (need {thr}); shifted-control {neg if neg is None else round(neg, 3)}")
        out[key]["rate"], out[key]["n"], out[key]["control_rate"] = rate, n, neg
    return out


# ------------------------------------------------------------------ overlay
def save_overlay(page_dir, rec, path, sfx=""):
    f = page_dir / f"05_degraded{sfx}.png"
    if not f.exists(): return
    im = np.asarray(Image.open(f).convert("RGB")).copy()
    for w in rec["words_all"]:
        if not w.get("scored"): continue
        col = (220, 0, 0) if w.get("visible", 1) < 0.5 else ((255, 140, 0) if w.get("occluded", 0) > 0.3 else (0, 170, 0))
        cv2.polylines(im, [np.round(np.asarray(w["poly"])).astype(np.int32)], True, col, 1)
    for e in rec["elements"]:
        if e["type"] not in ("header_text", "footer_text"): cv2.polylines(im, [np.round(np.asarray(e["poly"])).astype(np.int32)], True, (0, 90, 255), 2)
    Image.fromarray(im).save(path)


# ------------------------------------------------------------------ ladder (v2)
LADDER_TOL = {"occluded_frac": 0.03, "contrast_ratio": 0.10, "sharpness_ratio": 0.10}


def check_ladder(recs):
    """Monotonic by MEASUREMENT, not by stage number: from stage 1 to 5 the share of covered/cut-off body words must not fall, and the text's
    contrast and sharpness (relative to the clean target) must not rise, each within a small tolerance for random page detail.
    Also the final stage must be measurably harder than the first on at least one of the three."""
    ms = [r["degradation"]["measure"] for r in recs]; bad = []; moved = False
    for key, tol in LADDER_TOL.items():
        vals = [m.get(key) for m in ms]
        if any(v is None for v in vals): continue
        sign = 1 if key == "occluded_frac" else -1
        for a, b in zip(vals, vals[1:]):
            t_ = tol + (0.5 * max(a, b) if key == "sharpness_ratio" else 0.0)      # sharpness is a ratio of small numbers once the page is blurred: tolerance grows with it
            if sign * (b - a) < -t_: bad.append(f"{key} {a}->{b}")
        moved |= sign * (vals[-1] - vals[0]) > tol
    return {"pass": not bad and moved, "detail": ("; ".join(bad) if bad else "") + ("" if moved else " stage 5 not measurably harder than stage 1"),
            "measures": ms}


# ------------------------------------------------------------------ page + run
def verify_page(page_dir: Path, cfg, lib_names, overlay=True, sfx=""):
    rec = load_json(page_dir / f"05_degraded{sfx}.json"); ck = {}
    lay = load_json(page_dir / "03_layout.json")
    ck.update(check_content(rec)); ck.update(check_layout(lay, cfg))
    if any(f["family"] == lay["page"]["font"] for f in (lay["page"].get("ext") or {}).get("faces", [])): ck.update(check_fonts(lay))   # only pages whose body font is a bundled file (system fonts have nothing to load)
    ck.update(check_compose(rec, lib_names)); ck.update(check_damage(rec, rec["final_size"])); ck.update(check_alignment(page_dir, rec, style_aware=bool(lay["page"].get("ext")), sfx=sfx))
    if overlay: save_overlay(page_dir, rec, page_dir / f"07_verify_overlay{sfx}.png", sfx)
    res = {"id": rec["id"], "pass": all(v["pass"] is not False for v in ck.values()), "checks": ck,
           "meta": {"size": rec["final_size"], "font": rec["page"]["font"], "severity": rec["degradation"]["severity"], "fill": rec["page"]["fill"],
                    "header": rec["composition"]["header"]["mode"], "footer": rec["composition"]["footer"]["mode"], "stamps": len(rec["composition"].get("stamps", [])),
                    "ops": [o["op"] for o in rec["degradation"]["ops"]], "transcript_sha": hashlib.sha1(rec["transcript"].encode()).hexdigest()[:12]}}
    dump_json(page_dir / f"07_verify{sfx}.json", res); return res


def verify_run(run_dir: Path, cfg, lib_names, overlay=True, log=print):
    pages = sorted(p for p in (run_dir / "pages").glob("doc_*") if (p / "05_degraded.json").exists()); results = []
    for p in pages: results.append(verify_page(p, cfg, lib_names, overlay))
    ladder = {}                                           # v2 ladder pages: every stage variant gets the same checks, plus the monotonic check across stages
    for p in pages:
        if (p / "05_degraded_s1.json").exists():
            vs = [verify_page(p, cfg, lib_names, False, f"_s{k}") for k in range(1, 6)]; results += vs
            ladder[p.name] = check_ladder([load_json(p / f"05_degraded_s{k}.json") for k in range(1, 6)])
    names = sorted({k for r in results for k in r["checks"]}); n = len(results)
    summary = {"pages": n, "pages_passed": sum(r["pass"] for r in results),
               "per_check": {k: {"passed": sum(1 for r in results if r["checks"].get(k, {}).get("pass") is True), "failed": sum(1 for r in results if r["checks"].get(k, {}).get("pass") is False),
                                 "skipped": sum(1 for r in results if k in r["checks"] and r["checks"][k]["pass"] is None)} for k in names},   # a check absent from a page (v2-only checks) counts nowhere
               "failures": [{"id": r["id"], "failed": {k: v["detail"] for k, v in r["checks"].items() if v["pass"] is False}} for r in results if not r["pass"]],
               "duplicate_transcripts": len([r for r in results if not re.search(r"_s[1-5]$", r["id"])]) - len({r["meta"]["transcript_sha"] for r in results if not re.search(r"_s[1-5]$", r["id"])}),
               "variety": {"page_sizes": dict(Counter(f"{r['meta']['size'][0]}x{r['meta']['size'][1]}" for r in results).most_common(8)),
                           "fonts": dict(Counter(r["meta"]["font"] for r in results)), "severity": dict(Counter(r["meta"]["severity"] for r in results)),
                           "header_modes": dict(Counter(r["meta"]["header"] for r in results)), "footer_modes": dict(Counter(r["meta"]["footer"] for r in results)),
                           "stamps_per_page": dict(sorted(Counter(r["meta"]["stamps"] for r in results).items())),
                           "ops": dict(Counter(o for r in results for o in set(r["meta"]["ops"])).most_common()),
                           "fill_min_max": [min((r["meta"]["fill"] for r in results), default=None), max((r["meta"]["fill"] for r in results), default=None)]}}
    ctl = [v["checks"]["boxes_on_ink_target"].get("control_rate") for v in results if v["checks"]["boxes_on_ink_target"].get("control_rate") is not None]
    summary["negative_control_mean_rate"] = round(sum(ctl) / len(ctl), 3) if ctl else None
    if ladder:
        summary["ladder"] = {"pages": len(ladder), "passed": sum(1 for v in ladder.values() if v["pass"]),
                             "failures": {k: v["detail"] for k, v in ladder.items() if not v["pass"]}}
    dump_json(run_dir / "verify_report.json", {"summary": summary, "pages": results, **({"ladder": ladder} if ladder else {})})
    md = [f"# Verification report — {run_dir.name}", f"**{summary['pages_passed']}/{n} pages pass all checks.**  Duplicate transcripts: {summary['duplicate_transcripts']}.  Negative-control alignment rate: {summary['negative_control_mean_rate']} (must be far below the real rate).", "", "| check | passed | failed | skipped |", "|---|---|---|---|"]
    md += [f"| {k} | {v['passed']} | {v['failed']} | {v['skipped']} |" for k, v in summary["per_check"].items()]
    if "ladder" in summary: md += ["", f"**Ladder (monotonic by measurement): {summary['ladder']['passed']}/{summary['ladder']['pages']} pages.** " + "; ".join(f"{k}: {d}" for k, d in summary["ladder"]["failures"].items())]
    if summary["failures"]: md += ["", "## Failures"] + [f"- **{f['id']}**: " + "; ".join(f"{k} — {d}" for k, d in f["failed"].items()) for f in summary["failures"]]
    md += ["", "## Variety", "```", json.dumps(summary["variety"], ensure_ascii=False, indent=1), "```", "", "Overlays: `pages/<id>/07_verify_overlay.png` (green=scored word, orange=occluded, red=torn away/invisible, blue=stamps/marks/signatures)."]
    (run_dir / "verify_report.md").write_text("\n".join(md), encoding="utf-8"); return summary
