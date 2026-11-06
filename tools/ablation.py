#!/usr/bin/env python3
"""Ablation: which realism switch makes the pages harder? Same seeds for every arm, one switch changed at a time, scored with an OCR reader.

  python tools/ablation.py --count 100 --backend tesseract --workers 2          # generate + score + summary (re-runs skip finished arms)
  python tools/ablation.py --count 20 --arms a1_new_assets,a6_uneven            # a few arms only
  python tools/ablation.py --group variants --count 40                        # stage 8 split into its five variants, stage 9 into 72/100/120 dpi
  python tools/ablation.py --list                                              # show the arms

Arms (a1 is the reference for the Delta columns; every other arm = a1 + one switch):
  a0_legacy        v2 config, printed pages only, original assets and ops            (the pipeline before this work)
  a1_new_assets    new papers, torn edges, headers (stretched), stains from the old ops; no tape/stain images, no stage 8/9, normal typography
  a2_tape ... a9_small_only    + one switch
  a10_all          the v3 config as it is
Output: runs/ablation/ablation_summary.md (+ per-arm benchmark folders). Pages are generated into runs/abl_<arm>/ .
"""
import argparse, copy, csv, json, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "runs" / "ablation"


def load(p): return yaml.safe_load(open(ROOT / p, encoding="utf-8"))


def arms():
    v3 = load("config/hindi_sale_deed_v3_typed.yaml")
    a1 = copy.deepcopy(v3)
    a1["degrade"]["realism"] = {"cap_tear": True}
    a1["typography"] = {"spacing": {"normal": 1.0}, "font_mix": {"none": 1.0}}
    def with_(f):
        c = copy.deepcopy(a1); f(c); return c
    def real(**kw): return lambda c: c["degrade"]["realism"].update(kw)
    def typo(**kw): return lambda c: c["typography"].update(kw)
    a0 = load("config/hindi_sale_deed_v2.yaml"); a0["page_style"] = {"printed": 1.0, "hybrid": 0.0, "handwritten": 0.0}
    variants = {f"v{i}_{v}": with_(real(scan_of_scan=True, scan_of_scan_p=1.0, scan_variant=v))
                for i, v in enumerate(["photocopy", "fax", "halftone", "flatbed_rescan", "phone_photo"], 1)}
    variants.update({f"d{d}_dpi": with_(real(low_dpi=True, low_dpi_p=1.0, dpi=d)) for d in (72, 100, 120)})
    main_arms = {
        "a0_legacy": a0, "a1_new_assets": a1,
        "a2_tape": with_(real(tape=True)), "a3_stain_images": with_(real(stain_assets=True)),
        "a4_scan_of_scan": with_(real(scan_of_scan=True, scan_of_scan_p=1.0)), "a5_low_dpi": with_(real(low_dpi=True, low_dpi_p=1.0)),
        "a6_uneven": with_(typo(spacing={"uneven": 1.0})), "a7_tight_messy": with_(typo(spacing={"tight_messy": 1.0})),
        "a8_mixed_fonts": with_(typo(font_mix={"mixed": 1.0})), "a9_small_only": with_(typo(font_mix={"small_only": 1.0})),
        "a10_all": v3,
    }
    return main_arms, variants


def generate(name, cfg, count, workers):
    run = ROOT / "runs" / f"abl_{name}"
    if (run / "summary.json").exists():
        print(f"[{name}] pages exist, skipping generation"); return run
    cdir = OUT / "configs"; cdir.mkdir(parents=True, exist_ok=True)
    cp = cdir / f"{name}.yaml"; cp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cmd = [sys.executable, "main.py", "generate", "--config", str(cp), "--count", str(count), "--run-id", f"abl_{name}", "--workers", str(workers)]
    print(f"[{name}] generating {count} pages ..."); subprocess.run(cmd, cwd=ROOT, check=True)
    return run


def score(name, run, backend, out_root):
    from benchmark import run as br
    out = out_root / name
    if not (out / "results.csv").exists():
        br.main(["--set", f"{name}={run / 'dataset'}", "--backend", backend, "--out", str(out)])
    return list(csv.DictReader(open(out / "results.csv", encoding="utf-8")))


def pooled(rows):
    f = lambda k: sum(float(r[k]) for r in rows)
    return {"pages": len(rows), "CER": f("char_err") / max(1, f("char_len")), "missed": (f("c_sub") + f("c_del")) / max(1, f("char_len")),
            "extra": f("c_ins") / max(1, f("char_len")), "WER": f("word_err") / max(1, f("word_len")),
            "failed": sum(float(r["CER"]) > 0.5 for r in rows) / len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100); ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--backend", default="tesseract"); ap.add_argument("--arms"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--group", default="main", choices=["main", "variants"])
    a = ap.parse_args()
    main_arms, variant_arms = arms(); A = {**main_arms, **variant_arms}
    if a.list:
        print("\n".join(A)); return
    group = list(variant_arms) if a.group == "variants" else list(main_arms)
    names = a.arms.split(",") if a.arms else group
    if "a1_new_assets" not in names: names = ["a1_new_assets"] + names          # the reference arm is always part of a table
    out_root = OUT / ("bench_" + a.backend); results = {}
    for n in names:
        run = generate(n, A[n], a.count, a.workers); results[n] = score(n, run, a.backend, out_root)
    base = results.get("a1_new_assets")
    bmap = {r["page"]: float(r["CER"]) for r in base} if base else {}
    lines = [f"# Ablation ({a.backend}, {a.count} pages per arm, same seeds)", "",
             "Delta columns compare with a1_new_assets page by page (same seed): mean change in page CER, and the share of pages that got worse (> +2 points).", "",
             "| arm | pages | CER | missed | extra | WER | failed (CER>50%) | mean Δ page CER | pages worse |", "|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        p = pooled(results[n]); d = [float(r["CER"]) - bmap[r["page"]] for r in results[n] if r["page"] in bmap]
        dm = f"{sum(d) / len(d) * 100:+.1f} pts" if d and n != "a1_new_assets" else "-"
        worse = f"{sum(x > 0.02 for x in d) / len(d) * 100:.0f}%" if d and n != "a1_new_assets" else "-"
        lines.append(f"| {n} | {p['pages']} | {p['CER']*100:.1f}% | {p['missed']*100:.1f}% | {p['extra']*100:.1f}% | {p['WER']*100:.1f}% | {p['failed']*100:.0f}% | {dm} | {worse} |")
    fn = OUT / ("ablation_summary.md" if a.group == "main" else "ablation_summary_variants.md")
    fn.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines)); print(f"\nsaved {fn}")


if __name__ == "__main__":
    main()
