"""Run:  python -m unittest tests.test_dashboard -v     (no OCR tool needed)"""
import csv
import json
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

from PIL import Image

from benchmark import dashboard
from benchmark.run import CSV_COLS


def make_row(s, i, kind, diff, stage, style, sub=10, dele=10, ins=5, facts=8, nums=2):
    return {"set": s, "page": f"doc_{i:07d}", "image_kind": kind, "difficulty": diff, "stage": stage, "style": style,
            "char_err": sub + dele + ins, "char_len": 100, "word_err": 20, "word_len": 50, "g_err": 15, "g_len": 80,
            "c_sub": sub, "c_del": dele, "c_ins": ins, "CER": (sub + dele + ins) / 100, "WER": 0.4, "gCER": 0.3,
            "fact_n": 10, "fact_exact": facts, "fact_close": min(10, facts + 1), "fact_num_n": 4, "fact_num_exact": nums, "fact_num_close": nums}


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(rows)


def sample_rows(with_clean=True, with_control=True):
    rows, i = [], 0
    for kind in ("damaged", "clean") if with_clean else ("damaged",):
        for d, st, sty in (("easy", "1", "printed"), ("medium", "3", "hybrid"), ("hard", "5", "handwritten")):
            for _ in range(3):
                rows.append(make_row("A", i, kind, d, st, sty, sub=5 if kind == "clean" else 15)); i += 1
        rows.append(make_row("B", i, kind, "hard", "4", "handwritten", sub=40, facts=0, nums=0)); i += 1
    if with_control:
        rows.append(make_row("P", i, "damaged", "control", "0", "printed", sub=0, dele=1, ins=0, facts=9, nums=2))
    return rows


class TestData(unittest.TestCase):
    def test_load_rows_types(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            write_csv(p, sample_rows())
            rows = dashboard.load_rows(p)
        self.assertIsInstance(rows[0]["char_err"], int)
        self.assertIsInstance(rows[0]["CER"], float)

    def test_view_groups_by_kind_and_set(self):
        v = dashboard.view(sample_rows())
        self.assertEqual(dashboard.get(v, "damaged", "difficulty", "A", "easy")["pages"], 3)
        self.assertIsNotNone(dashboard.get(v, "clean", "style", "A", "printed"))
        self.assertIsNone(dashboard.get(v, "clean", "difficulty", "P", "control"))

    def test_fmt(self):
        self.assertEqual(dashboard.fmt(None), "n/a")
        self.assertEqual(dashboard.fmt(4.26), "4.3")
        self.assertEqual(dashboard.fmt(23.4, "%"), "23%")


class TestCharts(unittest.TestCase):
    def test_svgs_are_valid_xml(self):
        svg1 = dashboard.stacked_rows("t & t", [("a <b>", 10, 5), ("c", 0, 0)])
        svg2 = dashboard.grouped_bars("t", ["one two three four five", "x"], [("s", [10, None], "a"), ("u", [3, 4], "b")])
        for svg in (svg1, svg2):
            xml.dom.minidom.parseString(svg)

    def test_bar_heights_follow_values(self):
        svg = dashboard.grouped_bars("t", ["a", "b"], [("s", [10, 40], "a")])
        import re
        hs = [float(h) for h in re.findall(r'class="a" x="[\d.]+" y="[\d.]+" width="[\d.]+" height="([\d.]+)"', svg)]
        self.assertAlmostEqual(hs[-1] / hs[-2], 4, places=1)


class TestPage(unittest.TestCase):
    def build(self, readers, gallery=None):
        d = tempfile.mkdtemp()
        dashboard.build(readers, d, gallery=gallery or {"ladder": [], "examples": []}, today="2026-01-01")
        return Path(d)

    def test_writes_all_files(self):
        out = self.build([("Tesseract", sample_rows())])
        for f in ("index.html", "README.md", "charts/chart_difficulty.svg", "charts/chart_stage.svg", "charts/chart_facts.svg"):
            self.assertTrue((out / f).exists(), f)

    def test_page_works_offline_and_has_the_story(self):
        out = self.build([("Tesseract", sample_rows())])
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("cdn", page.lower())
        self.assertNotIn("<script", page.lower())
        for needle in ("What we did, and why", "Why Tesseract", "Two papers behind this", "Augraphy", "Tesseract OCR Engine", "What comes next"):
            self.assertIn(needle, page)

    def test_no_em_dashes_anywhere(self):
        out = self.build([("Tesseract", sample_rows())])
        for f in ("index.html", "README.md"):
            self.assertNotIn("—", (out / f).read_text(encoding="utf-8"))

    def test_without_clean_copies_or_control(self):
        out = self.build([("Tesseract", sample_rows(with_clean=False, with_control=False))])
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("What we did, and why", page)
        self.assertNotIn("Same pages, no damage", page)
        self.assertNotIn("Clean printed copy</span>", page)

    def test_sentences_use_the_numbers(self):
        out = self.build([("Tesseract", sample_rows())])
        page = (out / "index.html").read_text(encoding="utf-8")
        # A damaged: missed = (15+10)/100 = 25 per 100 on every difficulty row in the sample
        self.assertIn("25 on easy pages", page)

    def test_two_readers_add_a_comparison(self):
        out = self.build([("Tesseract", sample_rows()), ("Other", sample_rows())])
        self.assertTrue((out / "charts" / "chart_readers.svg").exists())
        self.assertIn("Other", (out / "charts" / "chart_readers.svg").read_text(encoding="utf-8"))

    def test_markdown_points_at_chart_files_and_images(self):
        gal = {"ladder": [{"file": "img/ladder_1.jpg", "caption": "Stage 1: scan wear", "stage": 1, "name": "scan wear"}] * 3, "examples": []}
        out = self.build([("Tesseract", sample_rows())], gallery=gal)
        md = (out / "README.md").read_text(encoding="utf-8")
        self.assertIn("](charts/chart_difficulty.svg)", md)
        self.assertIn("](img/ladder_1.jpg)", md)


class TestGallery(unittest.TestCase):
    def make_set(self, root, name, labels):
        d = Path(root) / name / "train"
        d.mkdir(parents=True)
        for stem, style, stage in labels:
            (d / f"{stem}.json").write_text(json.dumps({"style": {"page_style": style}, "stage": {"stage": stage, "name": f"n{stage}"},
                                                         "difficulty": {"class": "medium"}}), encoding="utf-8")
            Image.new("RGB", (200, 300), "white").save(d / f"{stem}.png")
            Image.new("RGB", (200, 300), "white").save(d / f"{stem}_target.png")
        return Path(root) / name

    def test_picks_ladder_and_examples(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            a = self.make_set(root, "A", [("doc_1", "printed", 3), ("doc_2", "hybrid", 3), ("doc_3", "handwritten", 4)])
            c = self.make_set(root, "C", [(f"doc_9_s{k}", "printed", k) for k in range(1, 6)])
            g = dashboard.build_gallery({"A": a, "C": c}, out)
            self.assertEqual([x["stage"] for x in g["ladder"]], [0, 1, 2, 3, 4, 5])
            self.assertEqual(len(g["examples"]), 3)
            for item in g["ladder"] + g["examples"]:
                im = Image.open(Path(out) / item["file"])
                self.assertEqual(im.width, 520)
            self.assertEqual(dashboard.load_gallery(out)["ladder"][1]["name"], "n1")

    def test_same_pick_every_time(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as o1, tempfile.TemporaryDirectory() as o2:
            a = self.make_set(root, "A", [("doc_1", "printed", 3), ("doc_5", "printed", 3)])
            self.assertEqual(dashboard.build_gallery({"A": a}, o1), dashboard.build_gallery({"A": a}, o2))

    def test_missing_gallery_is_fine(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(dashboard.load_gallery(out), {"ladder": [], "examples": []})


if __name__ == "__main__":
    unittest.main()
