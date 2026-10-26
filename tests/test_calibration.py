"""Calibration tooling, no rendering: difficulty score behaviour, model listing against a stub client, and analyze on synthetic raw results."""
import sys, pathlib, json, shutil, subprocess, random; ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline import difficulty as D, step8_evaluate as ev

def label(stage, cr, sh, oc, style="printed", hand=0, fs=24, font="Hind"):
    return {"words": [{}] * 100, "style": {"page_style": style, "font": font, "font_size": fs, "hand_words": hand, "hand_font": "Kalam"},
            "stage": {"stage": stage, "measure": {"contrast_ratio": cr, "sharpness_ratio": sh, "occluded_frac": oc}}}
easy, hard = D.assess(label(1, 1.0, 1.0, 0.0)), D.assess(label(5, 0.2, 0.05, 0.5, "handwritten", 100, 18))
assert easy["class"] == "easy" and hard["class"] == "hard" and easy["score"] < hard["score"], (easy, hard)
assert D.assess(label(3, 0.7, 0.5, 0.1))["score"] < D.assess(label(3, 0.4, 0.2, 0.1))["score"], "more blur/fade must score higher"

class M:                                  # stub of a Gemini model entry
    def __init__(self, n, acts): self.name, self.supported_actions, self.display_name = n, acts, n
class C:
    class models:
        @staticmethod
        def list(): return [M("models/b-model", ["generateContent"]), M("models/embed", ["embedContent"]), M("models/a-model", ["generateContent"])]
assert [n for n, _ in ev.list_gemini_models(C())] == ["a-model", "b-model"]

run = ROOT / "runs" / "_cal_unit"; shutil.rmtree(run, ignore_errors=True); (run / "calibration").mkdir(parents=True)
rng = random.Random(3); rows = []
for i in range(40):
    for st in ("printed", "hybrid", "handwritten"):
        for k in range(1, 6):
            cr, sh, oc = 1 - 0.15 * (k - 1) - rng.random() * 0.05, 1 - 0.2 * (k - 1), 0.05 * k
            d = D.assess(label(k, cr, sh, oc, st, 80 if st == "handwritten" else 0))
            rows.append({"id": f"doc_{i:03d}_s{k}", "base_id": f"doc_{i:03d}", "kind": "final", "stage": k, "page_style": st, "font": "Hind", "font_size": 24, "hand_share": 0,
                         "measure": {"contrast_ratio": cr, "sharpness_ratio": sh, "occluded_frac": oc, "text_contrast": 150 * cr}, "difficulty": d, "cer": 0.01 + 0.04 * (k - 1) ** 1.5 + rng.random() * 0.01})
        rows.append({**rows[-5], "id": f"doc_{i:03d}_s1c", "kind": "clean", "cer": 0.01})
(run / "calibration" / "calibration_raw.json").write_text(json.dumps({"meta": {"model": "unit", "ocr": "fake", "prompt_sha": ev.prompt_sha(), "n_final": 600, "n_clean": 120, "date": "now"}, "rows": rows}), encoding="utf-8")
r = subprocess.run([sys.executable, str(ROOT / "tools/calibrate.py"), "analyze", "--run-id", "_cal_unit"], capture_output=True, text=True); assert r.returncode == 0, r.stderr
rep = (run / "calibration" / "calibration_report.md").read_text(encoding="utf-8")
assert "Error rises with stage in every style** (tolerance 0.03): yes" in rep and "unit" in rep
import yaml; y = yaml.safe_load((run / "calibration" / "calibrated_difficulty.yaml").read_text(encoding="utf-8"))
assert y["difficulty"]["provisional"] is False and y["difficulty"]["calibration"]["model"] == "unit" and y["difficulty"]["thresholds"]["easy_max"] < y["difficulty"]["thresholds"]["medium_max"]
shutil.rmtree(run); print("PASS: difficulty score, model listing, calibration analysis")
