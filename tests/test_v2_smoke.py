"""v2 smoke test: bundled fonts, size plan, staged degradation, hybrid and handwritten pages, all through steps 1-7.
Seeds are chosen so that all three page styles occur (0 hybrid, 2 printed, 4 handwritten with Kalam, 12 handwritten with Amita)."""
import sys, pathlib, shutil, json; ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline.common import load_config
from pipeline.assets import AssetLib
from pipeline.step3_layout import Renderer
from pipeline.orchestrator import PageRunner
from pipeline.step7_verify import verify_run
cfg = load_config(ROOT / "config/hindi_sale_deed_v2.yaml"); run = ROOT / "runs" / "_smoke_v2"; shutil.rmtree(run, ignore_errors=True)
lib = AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", []))
with Renderer() as r:
    pr = PageRunner(cfg, run, r, lib)
    for s in (0, 2, 4, 12): pr.run(s)
styles = {}
for s in (0, 2, 4, 12):
    lab = json.loads(next((run / "dataset").rglob(f"doc_{s:07d}.json")).read_text(encoding="utf-8")); styles[s] = lab["style"]["page_style"]
    assert 1 <= lab["stage"]["stage"] <= 5 and "contrast_ratio" in lab["stage"]["measure"], lab.get("stage")
    assert lab["difficulty"]["class"] in ("easy", "medium", "hard") and lab["difficulty"]["provisional"], lab.get("difficulty")
    n_hand = sum(1 for w in lab["words"] if w.get("hand"))
    assert (n_hand > 0) == (styles[s] != "printed"), f"seed {s}: hand words {n_hand} for style {styles[s]}"
assert set(styles.values()) == {"printed", "hybrid", "handwritten"}, styles
summ = verify_run(run, cfg, [a.name for c in lib.by_cat.values() for a in c], overlay=False, log=lambda *a: None)
assert summ["pages_passed"] == summ["pages"] == 4, summ["failures"]
print("PASS: v2 pages", styles, "all verified")
shutil.rmtree(run, ignore_errors=True)
