#!/usr/bin/env python3
"""Hindi sale-deed OCR training-data pipeline. One entry point.

  python main.py generate --count 20                   # steps 1-6 for seeds 0..19, saves every step under runs/<run_id>/
  python main.py generate --count 20 --run-id demo --workers 2
  python main.py generate --run-id demo --seeds 7 --from-step 5   # redo degradation of page 7 from its saved composed page
  python main.py verify --run-id demo [--repro 3]       # step 7: automatic checks, report in runs/demo/verify_report.md
  python main.py sheet --run-id demo                    # contact sheets (final pages and boxes overlay)
  python main.py evaluate --run-id demo --ocr fake      # step 7 (--ocr gemini needs GEMINI_API_KEY)
  python main.py info                                   # environment check
"""
import argparse, asyncio, json, sys, time
from datetime import datetime
from pathlib import Path
from multiprocessing import Pool
from pipeline.common import ROOT, load_config, setup_logging, versions, dump_json

_W = {}


def _init(cfg, run_dir):
    import logging
    from pipeline.step3_layout import Renderer
    from pipeline.assets import AssetLib
    _W["cfg"] = cfg; _W["run_dir"] = run_dir; _W["lib"] = AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", []))
    _W["r"] = Renderer().__enter__()
    from pipeline.orchestrator import PageRunner
    log = logging.getLogger("docgen"); log.setLevel(logging.DEBUG)
    fh = logging.FileHandler(Path(run_dir) / "run.log", encoding="utf-8"); fh.setFormatter(logging.Formatter("%(asctime)s %(processName)s %(levelname)s %(message)s")); log.addHandler(fh)
    _W["runner"] = PageRunner(cfg, run_dir, _W["r"], _W["lib"])


def _job(args):
    seed, from_step, until = args
    try:
        return _W["runner"].run(seed, from_step, until)
    except Exception as e:
        import traceback, logging
        logging.getLogger("docgen").error("seed %s failed: %r\n%s", seed, e, traceback.format_exc())
        return {"seed": seed, "error": repr(e)}


def cmd_generate(a):
    cfg = load_config(a.config); run_id = a.run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S"); run_dir = ROOT / "runs" / run_id
    log = setup_logging(run_dir)
    if a.writer == "gemini" or (a.writer is None and cfg["writer"]["kind"] == "gemini"):
        sys.exit("The Gemini text writer runs through the async path (see docs/GEMINI.md); this CLI uses the offline template writer.")
    import shutil; shutil.copy(a.config, run_dir / "config.snapshot.yaml"); dump_json(run_dir / "env.json", versions())
    seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else list(range(a.start, a.start + a.count))
    log.info("run %s: %d pages, %d workers, from_step=%s", run_id, len(seeds), a.workers, a.from_step)
    t0 = time.time(); ok = err = skip = 0; man = open(run_dir / "manifest.jsonl", "a", encoding="utf-8")
    with Pool(a.workers, initializer=_init, initargs=(cfg, str(run_dir))) as p:
        for i, r in enumerate(p.imap_unordered(_job, [(s, a.from_step, a.until_step) for s in seeds]), 1):
            if isinstance(r, str): ok += 1
            elif r.get("skipped"): skip += 1
            elif "error" in r: err += 1; log.info("ERROR seed %s: %s", r["seed"], r["error"])
            else: ok += 1; man.write(json.dumps(r, ensure_ascii=False) + "\n"); man.flush()
            if i % 5 == 0 or i == len(seeds): log.info("%d/%d ok=%d skipped=%d errors=%d  %.2f pages/s", i, len(seeds), ok, skip, err, i / (time.time() - t0))
    dump_json(run_dir / "summary.json", {"run_id": run_id, "pages": len(seeds), "ok": ok, "skipped": skip, "errors": err, "sec": round(time.time() - t0, 1)})
    log.info("done. outputs: %s", run_dir)
    if a.verify:
        import subprocess; subprocess.run([sys.executable, str(ROOT / "main.py"), "verify", "--run-id", run_id])


def cmd_sheet(a):
    from PIL import Image, ImageDraw
    run_dir = ROOT / "runs" / a.run_id; pages = sorted((run_dir / "pages").glob("doc_*"))[: a.limit]
    ims, dbg = [], []
    for d in pages:
        f = d / "05_degraded.png"
        if not f.exists(): continue
        im = Image.open(f).convert("RGB"); ims.append(im); b = im.copy(); dr = ImageDraw.Draw(b)
        for w in json.load(open(d / "05_degraded.json", encoding="utf-8"))["words_all"]:
            if w.get("scored") and w.get("visible", 1) > .5: dr.polygon([tuple(p) for p in w["poly"]], outline=(255, 0, 0))
        dbg.append(b)
    def sheet(ims, path, H=620):
        ims = [i.resize((int(i.width * H / i.height), H)) for i in ims]; rows = [ims[i:i + 4] for i in range(0, len(ims), 4)]
        sh = Image.new("RGB", (max(sum(i.width + 10 for i in r) for r in rows), len(rows) * (H + 10)), (120, 120, 120))
        for ri, row in enumerate(rows):
            x = 0
            for i in row: sh.paste(i, (x, ri * (H + 10))); x += i.width + 10
        sh.save(path)
    sheet(ims, run_dir / "contact_sheet.png"); sheet(dbg, run_dir / "contact_sheet_boxes.png"); print("wrote", run_dir / "contact_sheet.png")


def cmd_evaluate(a):
    from pipeline import step8_evaluate as ev
    ds = ROOT / "runs" / a.run_id / "dataset"; labels = {}
    def lookup(k):
        if k not in labels: labels[k] = json.loads(next(ds.glob(f"*/{k}.json")).read_text(encoding="utf-8"))
        return labels[k]
    ocr = ev.FakeOCR(lookup) if a.ocr == "fake" else ev.GeminiOCR(model=a.model, concurrency=a.conc, cache_dir=ds.parent / "eval" / "ocr_cache")
    rows = asyncio.run(ev.evaluate(ds, ocr, a.split, a.limit, a.clean, a.conc)); rep = ev.summarize(rows)
    out = ds.parent / "eval"; out.mkdir(exist_ok=True); tag = f"{a.ocr}_{a.split}{'_clean' if a.clean else ''}"
    dump_json(out / f"eval_{tag}.json", {"summary": rep, "rows": rows}); print(json.dumps(rep, ensure_ascii=False, indent=1)); print("saved", out / f"eval_{tag}.json")


def cmd_verify(a):
    """Runs step 7 on a finished run (uses the run's own config snapshot). --repro N also regenerates N pages from scratch and compares bytes."""
    import hashlib, shutil
    from pipeline import step7_verify as vf
    from pipeline.assets import AssetLib
    run_dir = ROOT / "runs" / a.run_id; snap = run_dir / "config.snapshot.yaml"; cfg = load_config(snap if snap.exists() else a.config)
    lib = AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", [])); names = {x.name for cat in lib.by_cat.values() for x in cat}
    s = vf.verify_run(run_dir, cfg, names); bad = s["pages"] - s["pages_passed"]
    print(f"{s['pages_passed']}/{s['pages']} pages pass all checks. Report: {run_dir / 'verify_report.md'}")
    for f in s["failures"][:10]: print(" FAIL", f["id"], f["failed"])
    if a.repro:
        from pipeline.step3_layout import Renderer
        from pipeline.orchestrator import PageRunner
        tmp = run_dir / "_repro"; shutil.rmtree(tmp, ignore_errors=True); diff = []
        pages = sorted((run_dir / "pages").glob("doc_*"))[: a.repro]
        with Renderer() as r:
            pr = PageRunner(cfg, tmp, r, lib)
            for p in pages:
                pr.run(int(p.name.split("_")[1])); h = lambda q: hashlib.md5(q.read_bytes()).hexdigest()
                if h(p / "05_degraded.png") != h(tmp / "pages" / p.name / "05_degraded.png"): diff.append(p.name)
        shutil.rmtree(tmp, ignore_errors=True); print(f"reproducibility: {len(pages) - len(diff)}/{len(pages)} pages regenerated byte-identical" + (f"  DIFFERENT: {diff}" if diff else ""))
        bad += len(diff)
    sys.exit(1 if bad else 0)


def cmd_models(a):
    """Lists the Gemini models your GEMINI_API_KEY can use. Pick one that reads images and pass it as --model (there is no default for calibration)."""
    from pipeline import step8_evaluate as ev
    for name, disp in ev.list_gemini_models(): print(f"{name}\t{disp}")


def cmd_info(a):
    print(json.dumps(versions(), indent=1))
    from pipeline.step3_layout import CHROME; print("chromium:", CHROME or "playwright default")
    import subprocess; print(subprocess.run("fc-list | grep -i -c devanagari", shell=True, capture_output=True, text=True).stdout.strip(), "Devanagari font files")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--config", default=str(ROOT / "config/hindi_sale_deed.yaml")); g.add_argument("--run-id")
    g.add_argument("--start", type=int, default=0); g.add_argument("--count", type=int, default=8); g.add_argument("--seeds"); g.add_argument("--workers", type=int, default=2)
    g.add_argument("--from-step", type=int, choices=range(1, 7)); g.add_argument("--until-step", type=int, default=6, choices=range(1, 7)); g.add_argument("--writer"); g.add_argument("--verify", action="store_true", help="run step 7 afterwards"); g.set_defaults(fn=cmd_generate)
    s = sub.add_parser("sheet"); s.add_argument("--run-id", required=True); s.add_argument("--limit", type=int, default=8); s.set_defaults(fn=cmd_sheet)
    e = sub.add_parser("evaluate"); e.add_argument("--run-id", required=True); e.add_argument("--split", default="train"); e.add_argument("--ocr", default="fake", choices=["fake", "gemini"])
    e.add_argument("--model", default="gemini-2.5-flash"); e.add_argument("--limit", type=int); e.add_argument("--clean", action="store_true"); e.add_argument("--conc", type=int, default=8); e.set_defaults(fn=cmd_evaluate)
    v = sub.add_parser("verify"); v.add_argument("--run-id", required=True); v.add_argument("--config", default=str(ROOT / "config/hindi_sale_deed.yaml")); v.add_argument("--repro", type=int, default=0, help="regenerate N pages and compare bytes"); v.set_defaults(fn=cmd_verify)
    m = sub.add_parser("models", help="list the Gemini models this API key can use"); m.set_defaults(fn=cmd_models)
    i = sub.add_parser("info"); i.set_defaults(fn=cmd_info)
    a = ap.parse_args(); a.fn(a)
