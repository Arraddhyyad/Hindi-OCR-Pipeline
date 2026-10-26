"""Smoke test: 2 pages through steps 1-6, checks every per-step artifact exists, then checks determinism on re-run from step 5."""
import sys, pathlib, hashlib, shutil; ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline.common import load_config
from pipeline.assets import AssetLib
from pipeline.step3_layout import Renderer
from pipeline.orchestrator import PageRunner
cfg = load_config(ROOT / "config/hindi_sale_deed.yaml"); run = ROOT / "runs" / "_smoke"; shutil.rmtree(run, ignore_errors=True)
with Renderer() as r:
    pr = PageRunner(cfg, run, r, AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", [])))
    for s in (0, 1):
        out = pr.run(s); d = run / "pages" / f"doc_{s:07d}"
        for f in ("01_entities.json", "02_text.json", "03_layout.png", "03_layout.json", "04_composed.png", "04_composed.json",
                  "05_degraded.png", "05_target.png", "05_degraded.json", "06_label.json", "steps.json"):
            assert (d / f).exists(), f"missing {f}"
    h = lambda p: hashlib.md5(p.read_bytes()).hexdigest(); p0 = run / "pages/doc_0000000/05_degraded.png"; before = h(p0)
    pr.run(0, from_step=5); assert h(p0) == before, "re-running step 5 from saved files must reproduce the same image"
print("PASS: all step artifacts written; step 5 re-run is byte-identical")
shutil.rmtree(run, ignore_errors=True)
