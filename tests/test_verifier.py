"""Mutation tests: break a good page in specific ways and confirm the verifier catches each one (so a green report means something).
Needs a run with at least one page:  python main.py generate --count 2 --run-id _vt  (created automatically if missing)."""
import sys, pathlib, copy, shutil, json; ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image
from pipeline.common import load_config, load_json
from pipeline import step7_verify as vf
from pipeline.assets import AssetLib
cfg = load_config(ROOT / "config/hindi_sale_deed.yaml"); lib = AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", [])); names = {a.name for c in lib.by_cat.values() for a in c}
run = ROOT / "runs" / "_vt"
if not (run / "pages/doc_0000000/05_degraded.json").exists():
    from pipeline.step3_layout import Renderer; from pipeline.orchestrator import PageRunner
    with Renderer() as r: PageRunner(cfg, run, r, lib).run(0)
d = run / "pages/doc_0000000"; rec = load_json(d / "05_degraded.json"); lay = load_json(d / "03_layout.json")
fails = 0
def expect(name, cond):
    global fails; print(("PASS " if cond else "FAIL ") + name); fails += (not cond)

expect("good page: content checks pass", all(v["pass"] for v in vf.check_content(rec).values()))
expect("good page: layout checks pass", all(v["pass"] for v in vf.check_layout(lay, cfg).values()))
expect("good page: damage checks pass", all(v["pass"] for v in vf.check_damage(rec, rec["final_size"]).values()))
expect("good page: alignment passes", all(v["pass"] for v in vf.check_alignment(d, rec).values()))

m = copy.deepcopy(rec); m["transcript"] = m["transcript"].replace(m["entities"]["seller"]["name"], "XXXX")
expect("catches a missing fact (seller name removed)", not vf.check_content(m)["facts_present"]["pass"])
m = copy.deepcopy(rec); m["transcript"] = m["transcript"].replace("हज़ार", "लाख", 1) if "हज़ार" in m["transcript"] else m["transcript"].replace("लाख", "करोड़", 1)
expect("catches wrong amount in words (parsed back)", not vf.check_content(m)["amount_words_parse"]["pass"])
m = copy.deepcopy(rec); [w for w in m["words_all"] if w.get("scored")][5]["text"] = "गलत"
expect("catches label/text mismatch", not vf.check_content(m)["labels_match_text"]["pass"])
m = copy.deepcopy(lay); m["page"]["fill"] = 0.55
expect("catches underfilled page", not vf.check_layout(m, cfg)["fill_in_range"]["pass"])
m = copy.deepcopy(rec); m["degradation"]["ops"] = [o for o in m["degradation"]["ops"] if o["op"] != "torn_edge"]
expect("catches a page that is not torn", not vf.check_damage(m, m["final_size"])["folded_and_torn"]["pass"])
m = copy.deepcopy(rec); m["words_all"][3]["poly"] = [[0, 0], [0, 0], [0, 0], [0, 0]]
expect("catches a degenerate polygon", not vf.check_damage(m, m["final_size"])["polygons_valid"]["pass"])
m = copy.deepcopy(rec)
for w in m["words_all"]: w["poly"] = [[x + 18, y + 12] for x, y in w["poly"]]
expect("catches boxes shifted by ~18 px (alignment on target)", not vf.check_alignment(d, m)["boxes_on_ink_target"]["pass"])
m = copy.deepcopy(rec); ang = np.deg2rad(1.5)    # a rotation that was NOT tracked
c = np.array([rec["final_size"][0] / 2, rec["final_size"][1] / 2]); R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
for w in m["words_all"]: w["poly"] = ((np.asarray(w["poly"]) - c) @ R.T + c).tolist()
expect("catches an untracked 1.5 degree rotation", not vf.check_alignment(d, m)["boxes_on_ink_target"]["pass"])
print("ALL PASS" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
