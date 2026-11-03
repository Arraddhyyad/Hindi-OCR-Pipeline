"""v3 realism: era filtering, manifest tool, tape and stain ops. Run: python -m unittest tests.test_v3"""
import random, subprocess, sys, unittest
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline.assets import AssetLib
from pipeline.step5_degrade import State
from pipeline import realism


class V3(unittest.TestCase):
    def test_eras(self):
        old = AssetLib(ROOT / "assets"); new = AssetLib(ROOT / "assets", eras=["legacy", "v3"])
        self.assertEqual(len(old.get("tape")), 0)                                   # older configs never see the new batch
        self.assertEqual(len(old.get("paper")), 1)
        self.assertGreaterEqual(len(new.get("paper")), 10); self.assertGreaterEqual(len(new.get("tape")), 4)

    def test_manifest_tool_idempotent(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools/add_assets.py")], capture_output=True, text=True)
        self.assertIn("up to date", r.stdout)

    def test_paper_crop_and_tape_load(self):
        lib = AssetLib(ROOT / "assets", eras=["legacy", "v3"])
        for a in lib.get("paper"):
            im = a.load(); self.assertGreater(im.width, 600)
        for a in lib.get("tape"):
            im = a.load(); self.assertEqual(im.mode, "RGBA"); self.assertGreater(im.width, 100)

    def test_ops_change_pixels_and_log_elements(self):
        lib = AssetLib(ROOT / "assets", eras=["legacy", "v3"])
        img = np.full((900, 640, 3), 0.9, np.float32)
        st = State(img.copy(), None, []); st.fold_lines = [("h", 450)]
        realism.op_tape(st, random.Random(1), np.random.default_rng(1), 1.0, lib)
        self.assertTrue(any(e["type"] == "tape" for e in st.elements)); self.assertFalse(np.allclose(st.img, img))
        st2 = State(img.copy(), None, [])
        realism.op_stain_assets(st2, random.Random(2), np.random.default_rng(2), 1.0, lib)
        self.assertTrue(any(e["type"] == "stain_asset" for e in st2.elements)); self.assertLess(st2.img.mean(), 0.9)

    def test_stage8_and_9(self):
        img = np.random.default_rng(0).random((600, 420, 3)).astype(np.float32) * 0.2 + 0.7
        for v in realism.SCAN_VARIANTS:
            st = State(img.copy(), img.copy(), [{"poly": [[10, 10], [90, 10], [90, 40], [10, 40]], "bbox": [10, 10, 90, 40]}]); st.scan_bg = (0.05,) * 3
            realism.op_scan_of_scan(st, random.Random(1), np.random.default_rng(1), 1.0, v)
            self.assertEqual(st.img.shape[2], 3); self.assertTrue(np.isfinite(st.img).all()); self.assertEqual(st.log[-1]["variant"], v)
        st = State(img.copy(), img.copy(), [{"poly": [[10, 10], [90, 10], [90, 40], [10, 40]], "bbox": [10, 10, 90, 40]}])
        realism.op_low_dpi(st, random.Random(1), None, 1.0, 75)                       # 75 dpi = half of the 150 dpi canvas
        self.assertEqual(st.img.shape[:2], (300, 210)); self.assertEqual(st.clean.shape[:2], (300, 210))
        self.assertEqual(st.items[0]["bbox"], [5.0, 5.0, 45.0, 20.0])


if __name__ == "__main__":
    unittest.main()
