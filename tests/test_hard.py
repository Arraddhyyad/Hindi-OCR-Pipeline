"""Hard pages (v2 hard config): a handwritten page in the dense band is flagged hard, gets the severe damage stages, the local damage ops and (forced here) the phone photo,
carries struck-through words and corrections,
the marked transcript equals the plain scored transcript once ~~ is removed, the label carries the flags, and step 7 passes.
Seed 1 is handwritten and dense in the hard config. A printed page (seed 2) must carry none of it."""
import sys, pathlib, shutil, json; ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline.common import load_config
from pipeline.assets import AssetLib
from pipeline.step3_layout import Renderer
from pipeline.orchestrator import PageRunner
from pipeline.step7_verify import verify_run
cfg = load_config(ROOT / "config/hindi_sale_deed_v2_hard.yaml"); cfg["degrade"]["hard"]["photo"]["p"] = 1.0    # force the phone photo for this test (the config default is sometimes)
run = ROOT / "runs" / "_smoke_hard"; shutil.rmtree(run, ignore_errors=True)
lib = AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", []))
with Renderer() as r:
    pr = PageRunner(cfg, run, r, lib)
    for s in (1, 2): pr.run(s)
lab = {s: json.loads(next((run / "dataset").rglob(f"doc_{s:07d}.json")).read_text(encoding="utf-8")) for s in (1, 2)}
h, p = lab[1], lab[2]
assert h["style"]["page_style"] == "handwritten" and h["style"]["font_size"] <= 26, h["style"]
assert sum(1 for w in h["words"] if w.get("struck")) >= 2 and any(w.get("correction") for w in h["words"])
assert "~~" in h["transcript_marked"]
rec = json.loads((run / "pages" / "doc_0000001" / "04_composed.json").read_text(encoding="utf-8"))
assert h["transcript_marked"].replace("~~", "").split() == rec["transcript_scored"].split()
assert "transcript_marked" not in p and not any(w.get("struck") or w.get("correction") for w in p["words"])
ops = h["ops"]
for op in ("ink_fade", "show_through", "cracked_ink", "photocopy_look", "phone_photo"): assert op in ops, (op, ops)
assert "augraphy.BadPhotoCopy" not in ops and h["stage"]["stage"] in (4, 5), h["stage"]
assert any(e["type"] == "finger" for e in h["elements"]) and "photocopy_look" not in p["ops"] and "phone_photo" not in p["ops"]
c = h["difficulty"]["components"]; assert h["difficulty"]["version"] == 2 and {"corrections", "density", "photo"} <= set(c) and c["photo"] == 1.0, c
summ = verify_run(run, cfg, [a.name for c in lib.by_cat.values() for a in c], overlay=False, log=lambda *a: None)
assert summ["pages_passed"] == summ["pages"] == 2, summ["failures"]
print("PASS: hard page flagged, struck and corrected words labelled, marked transcript consistent, verifier passes")
shutil.rmtree(run, ignore_errors=True)
