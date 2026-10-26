"""Calibration of the easy / medium / hard label against real OCR error rates.

  python tools/calibrate.py models                                   list the Gemini models your key can use (needs GEMINI_API_KEY)
  python tools/calibrate.py make-set  --run-id calib --count 60      pages in all 5 stages (ladder), balanced over printed / hybrid / handwritten
  python tools/calibrate.py run       --run-id calib --model NAME    OCR every image AND its clean target; writes calibration/calibration_raw.json
  python tools/calibrate.py spotcheck --run-id calib                 contact sheets + answers.csv for a human to mark "readable y/n"
  python tools/calibrate.py analyze   --run-id calib [--spot answers.csv]   report + calibrated_difficulty.yaml (+ guardrail limits if --spot)

`run` has no default model on purpose: use a name from `models`. `--ocr fake` runs the whole chain offline (for testing the tool, not for calibrating).
Everything the analysis needs is stored raw: per-image error rates, the model name, the prompt hash, the clean-image baseline per page style.
"""
import argparse, asyncio, csv, datetime, hashlib, json, pathlib, random, subprocess, sys
import numpy as np, yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, dump_json
from pipeline import step8_evaluate as ev

STYLES = ("printed", "hybrid", "handwritten")
V2 = ROOT / "config/hindi_sale_deed_v2.yaml"


def cdir(run_id):
    d = ROOT / "runs" / run_id / "calibration"; d.mkdir(parents=True, exist_ok=True); return d


# ------------------------------------------------------------------ models
def cmd_models(a):
    for name, disp in ev.list_gemini_models(): print(f"{name}\t{disp}")


# ------------------------------------------------------------------ make-set
def cmd_make_set(a):
    from pipeline.step3_layout import plan_page
    cfg = load_config(a.config); per = -(-a.count // len(STYLES)); got = {s: [] for s in STYLES}; seed = a.start
    while any(len(v) < per for v in got.values()):                       # stratified by page style (planning is cheap, no rendering)
        st = plan_page(cfg, random.Random(seed), seed).ext["page_style"]
        if len(got[st]) < per: got[st].append(seed)
        seed += 1
    seeds = sorted(x for v in got.values() for x in v)[: a.count if a.count >= len(STYLES) else None]
    raw = yaml.safe_load(pathlib.Path(a.config).read_text(encoding="utf-8"))
    raw["degrade"]["staged"]["ladder"] = {"enabled": True, "splits": ["train", "val", "test"]}       # every page at all five stages
    tmp = ROOT / "config" / "_calibration_tmp.yaml"; tmp.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    try:
        subprocess.run([sys.executable, str(ROOT / "main.py"), "generate", "--config", str(tmp), "--run-id", a.run_id, "--seeds", ",".join(map(str, seeds)), "--verify"], check=True)
    finally:
        tmp.unlink(missing_ok=True)
    dump_json(cdir(a.run_id) / "set.json", {"seeds": seeds, "per_style": {k: len(v) for k, v in got.items()}, "config": str(a.config)})
    print(f"calibration set: {len(seeds)} pages x 5 stages in runs/{a.run_id}/dataset")


# ------------------------------------------------------------------ run
def _labels(run_id):
    ds = ROOT / "runs" / run_id / "dataset"
    return ds, sorted(p for p in ds.glob("*/doc_*_s[1-5].json"))


async def _run(a):
    ds, labs = _labels(a.run_id)
    if not labs: sys.exit("no ladder pages found: run make-set first")
    if a.ocr == "fake":
        cache = {}
        def look(k):
            if k not in cache: cache[k] = json.loads(next(ds.glob(f"*/{k}.json")).read_text(encoding="utf-8"))
            return cache[k]
        ocr, model = ev.FakeOCR(look), "fake"
    else:
        if not a.model: sys.exit("--model is required (list the models your key can use with: python tools/calibrate.py models)")
        ocr, model = ev.GeminiOCR(model=a.model, concurrency=a.conc, cache_dir=cdir(a.run_id) / "ocr_cache"), a.model
    sem = asyncio.Semaphore(a.conc); rows = []

    async def one(lp, kind):
        lab = json.loads(lp.read_text(encoding="utf-8"))
        img = lp.with_name(lp.stem + "_target.png") if kind == "clean" else next(lp.with_suffix(e) for e in (".png", ".jpg") if lp.with_suffix(e).exists())
        async with sem:
            pred = await ocr.read(img.read_bytes(), "image/jpeg" if img.suffix == ".jpg" else "image/png", key=lab["id"])
        sc = ev.score(pred, lab, lab.get("facts")); st = lab.get("style") or {}; sg = lab.get("stage") or {}; n = max(1, len(lab["words"]))
        rows.append({"id": lab["id"], "base_id": lab["id"].rsplit("_s", 1)[0], "kind": kind, "stage": sg.get("stage"), "page_style": st.get("page_style"),
                     "font": st.get("font"), "font_size": st.get("font_size"), "hand_share": round(st.get("hand_words", 0) / n, 3), "measure": sg.get("measure"),
                     "difficulty": lab.get("difficulty"), "cer": sc["cer"], "gcer": sc["gcer"], "wer": sc["wer"], "token_f1": sc["token_f1"],
                     "fact_recall": sc["fact_recall"], "len_ratio": sc["len_ratio"], "pred": pred})
    jobs = [one(lp, "final") for lp in labs] + [one(lp, "clean") for lp in labs if lp.stem.endswith("_s1")]       # clean baseline: one clean target per page
    await asyncio.gather(*jobs)
    rows.sort(key=lambda r: (r["kind"], r["id"]))
    out = {"meta": {"model": model, "ocr": a.ocr, "prompt_sha": ev.prompt_sha(), "prompt": ev.PROMPT, "n_final": sum(r["kind"] == "final" for r in rows),
                    "n_clean": sum(r["kind"] == "clean" for r in rows), "date": datetime.datetime.now().isoformat(timespec="seconds"),
                    "labels_difficulty_version": (rows[0].get("difficulty") or {}).get("version") if rows else None}, "rows": rows}
    dump_json(cdir(a.run_id) / "calibration_raw.json", out); print("wrote", cdir(a.run_id) / "calibration_raw.json", "model:", model, "prompt:", out["meta"]["prompt_sha"])


def cmd_run(a): asyncio.run(_run(a))


# ------------------------------------------------------------------ spotcheck
def cmd_spotcheck(a):
    from PIL import Image, ImageDraw
    ds, labs = _labels(a.run_id); by = {"easy": [], "medium": [], "hard": []}
    for lp in labs:
        lab = json.loads(lp.read_text(encoding="utf-8")); d = lab.get("difficulty")
        if d: by[d["class"]].append((lab["id"], lp))
    d = cdir(a.run_id); rng = random.Random(7); sel = []
    for cls, items in by.items(): sel += [(cls, i, p) for i, p in rng.sample(items, min(a.per_class, len(items)))]
    with open(d / "spotcheck_answers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "class_shown_by_tool", "readable_by_a_person_y_or_n", "notes"]); [w.writerow([i, c, "", ""]) for c, i, _ in sel]
    for cls in by:
        items = [(i, p) for c, i, p in sel if c == cls]
        for k in range(0, len(items), 6):
            chunk = items[k:k + 6]; sheet = Image.new("RGB", (3 * 700, 2 * 940), "white"); dr = ImageDraw.Draw(sheet)
            for j, (i, p) in enumerate(chunk):
                im = Image.open(next(p.with_suffix(e) for e in (".png", ".jpg") if p.with_suffix(e).exists())).convert("RGB"); im.thumbnail((690, 900))
                x, y = (j % 3) * 700, (j // 3) * 940; sheet.paste(im, (x + 5, y + 30)); dr.text((x + 8, y + 8), f"{i}  (shown as {cls})", fill=(0, 0, 0))
            sheet.save(d / f"spotcheck_{cls}_{k // 6 + 1}.jpg", quality=90)
    print(f"wrote sheets and {d / 'spotcheck_answers.csv'}: for each id fill column 3 with y or n (could a well-versed person read this page?)")


# ------------------------------------------------------------------ analyze
def _spearman(x, y):
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1]) if len(x) > 2 else float("nan")


def _split_point(good, bad, higher_is_bad):
    """Value separating readable (good) from unreadable (bad) pages; None when there are no bad pages."""
    if not bad: return None
    g, b = np.array(good), np.array(bad)
    return float((g.min() + b.max()) / 2) if (higher_is_bad is False and g.min() > b.max()) else (float((g.max() + b.min()) / 2) if (higher_is_bad and g.max() < b.min()) else float(g.min() * 0.9 if not higher_is_bad else g.max() * 1.1))


def cmd_analyze(a):
    from scipy.optimize import nnls
    raw = json.loads((cdir(a.run_id) / "calibration_raw.json").read_text(encoding="utf-8")); meta, rows = raw["meta"], raw["rows"]
    fin = [r for r in rows if r["kind"] == "final"]; cln = [r for r in rows if r["kind"] == "clean"]
    base = {s: float(np.mean([r["cer"] for r in cln if r["page_style"] == s])) if any(r["page_style"] == s for r in cln) else 0.0 for s in STYLES}
    for r in fin: r["excess"] = max(0.0, r["cer"] - base.get(r["page_style"], 0.0))
    md = [f"# Calibration report - {a.run_id}", f"Model `{meta['model']}` ({meta['ocr']}), prompt `{meta['prompt_sha']}`, {meta['n_final']} images + {meta['n_clean']} clean baselines, {meta['date']}.", "",
          "## Clean-image baseline (CER on the aligned clean target, per style)", "", "| style | clean CER |", "|---|---|"] + [f"| {s} | {base[s]:.3f} |" for s in STYLES]
    md += ["", "Excess CER = CER minus the clean baseline of the same style, so a style the model finds hard even when clean is not mistaken for damage.", "",
           "## CER by style and stage (median, excess over clean)", "", "| style | " + " | ".join(f"stage {k}" for k in range(1, 6)) + " |", "|---|" + "---|" * 5]
    viol = []
    for s in STYLES:
        meds = [float(np.median([r["excess"] for r in fin if r["page_style"] == s and r["stage"] == k] or [np.nan])) for k in range(1, 6)]
        md.append(f"| {s} | " + " | ".join("-" if np.isnan(m) else f"{m:.3f}" for m in meds) + " |")
        for k in range(4):
            if not (np.isnan(meds[k]) or np.isnan(meds[k + 1])) and meds[k + 1] < meds[k] - 0.03: viol.append(f"{s}: stage {k + 1} -> {k + 2} falls {meds[k]:.3f} -> {meds[k + 1]:.3f}")
    md += ["", "**Error rises with stage in every style** (tolerance 0.03): " + ("yes" if not viol else "NO - " + "; ".join(viol)), ""]
    # ---- fit weights: non-negative least squares of excess CER on the difficulty components
    comps = list(fin[0]["difficulty"]["components"]) if fin and fin[0].get("difficulty") else []
    cfgd = yaml.safe_load(V2.read_text(encoding="utf-8")).get("difficulty", {})
    if comps and len(fin) >= 20:
        X = np.array([[r["difficulty"]["components"][c] for c in comps] for r in fin]); y = np.array([r["excess"] for r in fin])
        w, _ = nnls(X, y); prov = np.array([cfgd["weights"][c] for c in comps]); prov = prov / prov.sum()
        w = w / w.sum() if w.sum() > 1e-9 else prov
        lam = min(1.0, len(fin) / 300)                     # small samples: pull the fit back towards the provisional weights (it would overfit)
        w = lam * w + (1 - lam) * prov; weights = {c: round(float(v), 4) for c, v in zip(comps, w)}
        fitted = True; md.append(f"> Sample size {len(fin)}: fitted weights are blended {lam:.0%} fitted / {1 - lam:.0%} provisional" + (" (use 300+ images for a full fit)." if lam < 1 else "."))
    else:
        weights = cfgd.get("weights", {}); fitted = False
    sc = np.array([sum(weights[c] * r["difficulty"]["components"][c] for c in comps) / (sum(weights.values()) or 1) for r in fin]) if comps else np.array([])
    ex = np.array([r["excess"] for r in fin])
    rho = _spearman(sc, ex) if len(sc) else float("nan")
    md += ["## Difficulty score vs measured error", "", f"Weights {'fitted (non-negative least squares)' if fitted else 'kept provisional (fewer than 20 images)'}: `{json.dumps(weights)}`", "",
           f"Spearman correlation between score and excess CER: **{rho:.3f}** (1 = perfect ordering).", ""]
    target = {"easy": 0.20, "medium": 0.40, "hard": 0.40}
    if len(sc):
        q1, q2 = np.quantile(sc, target["easy"]), np.quantile(sc, target["easy"] + target["medium"])
        e1, e2 = np.quantile(ex, target["easy"]), np.quantile(ex, target["easy"] + target["medium"])
        cls_s = np.where(sc < q1, 0, np.where(sc < q2, 1, 2)); cls_e = np.where(ex < e1, 0, np.where(ex < e2, 1, 2)); names = ["easy", "medium", "hard"]
        conf = np.zeros((3, 3), int)
        for p, t in zip(cls_s, cls_e): conf[t, p] += 1
        md += [f"Thresholds on the score for a 20 / 40 / 40 split: easy < {q1:.3f} <= medium < {q2:.3f} <= hard. Class by measured excess CER: easy < {e1:.3f}, medium < {e2:.3f}, hard above.", "",
               f"Agreement between score class and measured-error class: **{np.trace(conf) / conf.sum():.0%}**.", "", "| measured \\ score class | easy | medium | hard |", "|---|---|---|---|"] + [f"| {names[i]} | " + " | ".join(map(str, conf[i])) + " |" for i in range(3)] + [""]
        thresholds = {"easy_max": round(float(q1), 4), "medium_max": round(float(q2), 4)}
        # ---- stage weights that give the target class balance
        pc = {k: np.bincount(cls_s[[r["stage"] == k for r in fin]], minlength=3) / max(1, sum(r["stage"] == k for r in fin)) for k in range(1, 6)}
        cur_w = (yaml.safe_load(V2.read_text(encoding="utf-8"))["degrade"]["staged"]["stage_weights"]); cur = np.array([cur_w[k] for k in range(1, 6)], float)
        best, bw = 9, None
        for w5 in (np.array(c) / 20 for c in np.ndindex(*(21,) * 4)):
            if sum(w5) > 1.0001: continue
            wt = np.append(w5, 1 - sum(w5)); mix = sum(wt[k - 1] * pc[k] for k in range(1, 6))
            d = float(np.abs(mix - np.array([.2, .4, .4])).sum()) + 0.15 * float(np.abs(wt - cur).sum())        # also stay close to the current weights
            if d < best: best, bw = d, wt
        md += ["## Stage weights for a 20 / 40 / 40 class balance", "", "Suggested `degrade.staged.stage_weights`: `" + json.dumps({k: round(float(bw[k - 1]), 2) for k in range(1, 6)}) + f"` (balance distance plus drift penalty {best:.3f}).", ""]
        suggested_stage = {k: round(float(bw[k - 1]), 2) for k in range(1, 6)}
    else:
        thresholds, suggested_stage = cfgd.get("thresholds", {}), None
    # ---- guardrails from the human spot check
    guard = None
    if a.spot:
        ans = {r["id"]: r["readable_by_a_person_y_or_n"].strip().lower() for r in csv.DictReader(open(a.spot, encoding="utf-8")) if r["readable_by_a_person_y_or_n"].strip()}
        good = [r for r in fin if ans.get(r["id"]) == "y"]; bad = [r for r in fin if ans.get(r["id"]) == "n"]
        md += ["## Human spot check", "", f"{len(good)} pages marked readable, {len(bad)} marked not readable by a person.", ""]
        if good:
            g = {"provisional": False, "enforce": True}
            tc = _split_point([r["measure"]["text_contrast"] for r in good if "text_contrast" in r["measure"]], [r["measure"]["text_contrast"] for r in bad if "text_contrast" in r["measure"]], False)
            oc = _split_point([r["measure"]["occluded_frac"] for r in good], [r["measure"]["occluded_frac"] for r in bad], True)
            sh = _split_point([r["measure"]["sharpness_ratio"] for r in good if "sharpness_ratio" in r["measure"]], [r["measure"]["sharpness_ratio"] for r in bad if "sharpness_ratio" in r["measure"]], False)
            gm = lambda k, v: round(v, 3)
            g["min_text_contrast"] = gm(0, tc if tc is not None else 0.9 * min(r["measure"]["text_contrast"] for r in good if "text_contrast" in r["measure"]))
            g["max_occluded_frac"] = gm(0, oc if oc is not None else 1.1 * max(r["measure"]["occluded_frac"] for r in good))
            g["min_sharpness_ratio"] = gm(0, sh if sh is not None else 0.9 * min(r["measure"]["sharpness_ratio"] for r in good if "sharpness_ratio" in r["measure"]))
            guard = g; md += ["Guardrail limits from this check (readable pages stay inside, unreadable pages fall outside where the data separate): `" + json.dumps(g) + "`", ""]
    md += ["## Per-op effect on excess CER", "", "| damage | n pages | mean excess CER |", "|---|---|---|"]
    ops = {}
    for r in fin:
        lab = next((json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "runs" / a.run_id / "dataset").glob(f"*/{r['id']}.json")), None)
        for o in set((lab or {}).get("ops", [])): ops.setdefault(o, []).append(r["excess"])
    md += [f"| {o} | {len(v)} | {np.mean(v):.3f} |" for o, v in sorted(ops.items(), key=lambda kv: -np.mean(kv[1])) if len(v) >= 3]
    (cdir(a.run_id) / "calibration_report.md").write_text("\n".join(md), encoding="utf-8")
    out = {"difficulty": {"enabled": True, "provisional": False, "version": 2, "weights": weights, "thresholds": thresholds,
                          "font_difficulty": cfgd.get("font_difficulty", {}), "small_text_px": cfgd.get("small_text_px", 22),
                          "calibration": {"model": meta["model"], "ocr": meta["ocr"], "prompt_sha": meta["prompt_sha"], "n": meta["n_final"], "date": meta["date"],
                                          "clean_baseline": {k: round(v, 4) for k, v in base.items()}, "spearman": round(rho, 3) if rho == rho else None}}}
    if suggested_stage: out["suggested_stage_weights"] = suggested_stage
    if guard: out["suggested_guardrails"] = guard
    (cdir(a.run_id) / "calibrated_difficulty.yaml").write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("\n".join(md[:30])); print("\nwrote", cdir(a.run_id) / "calibration_report.md", "and calibrated_difficulty.yaml")
    if meta["ocr"] == "fake": print("NOTE: the OCR was the offline fake; these numbers only test the tool, they are NOT a calibration.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    m = sub.add_parser("make-set"); m.add_argument("--run-id", required=True); m.add_argument("--count", type=int, default=60); m.add_argument("--start", type=int, default=1000); m.add_argument("--config", default=str(V2)); m.set_defaults(fn=cmd_make_set)
    r = sub.add_parser("run"); r.add_argument("--run-id", required=True); r.add_argument("--model"); r.add_argument("--ocr", default="gemini", choices=["gemini", "fake"]); r.add_argument("--conc", type=int, default=8); r.set_defaults(fn=cmd_run)
    sp = sub.add_parser("spotcheck"); sp.add_argument("--run-id", required=True); sp.add_argument("--per-class", type=int, default=30); sp.set_defaults(fn=cmd_spotcheck)
    an = sub.add_parser("analyze"); an.add_argument("--run-id", required=True); an.add_argument("--spot"); an.set_defaults(fn=cmd_analyze)
    a = ap.parse_args(); a.fn(a)
