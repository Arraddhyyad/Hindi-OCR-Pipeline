"""Run:  python -m unittest tests.test_realdocs -v     (no network, no OCR tool needed: downloads are faked)"""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf
from PIL import Image, ImageDraw

from benchmark import run as bench_run
from realdocs import annotate, prepare, review, sources

TSV = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
       "5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t91.5\tनमस्ते\n"
       "5\t1\t1\t1\t1\t2\t50\t20\t40\t12\t88\tदुनिया\n"
       "5\t1\t1\t1\t2\t1\t10\t50\t30\t12\t-1\t \n"
       "5\t1\t1\t1\t2\t2\t10\t50\t30\t12\t70\tबैनामा\n")


def make_pdf(path, pages=6):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        for k in range(30):
            p.insert_text((50, 60 + 20 * k), "x" * 40 + f" {i}", fontsize=11)
    doc.save(path)


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)


class TestSources(Base):
    def test_open_license_rules(self):
        ok = sources.open_license
        self.assertTrue(ok("https://creativecommons.org/publicdomain/mark/1.0/"))
        self.assertTrue(ok("", "NOT_IN_COPYRIGHT"))
        self.assertTrue(ok("", "", "CC BY-SA 4.0"))
        self.assertTrue(ok("", "", "Public domain"))
        self.assertFalse(ok("", "", ""))
        self.assertFalse(ok("https://creativecommons.org/licenses/by-nc/4.0/"))
        self.assertFalse(ok("", "", "All rights reserved"))

    def test_looks_hindi(self):
        self.assertTrue(sources.looks_hindi("File:बैनामा 1952.jpg"))
        self.assertTrue(sources.looks_hindi("A deed in Hindi, 1930"))
        self.assertFalse(sources.looks_hindi("Deed, 1649, Massachusetts, ink on paper - Concord Museum"))

    def test_one_failed_download_does_not_stop_the_run(self):
        def dl(url, dest):
            raise RuntimeError("HTTP 403")
        with mock.patch.object(sources, "ia_search", lambda q, rows=50: [{"identifier": "a"}]), \
             mock.patch.object(sources, "ia_item", lambda i: ("T", "https://creativecommons.org/publicdomain/zero/1.0/", "", "f.pdf", "")), \
             mock.patch.object(sources, "commons_search", lambda q, limit=30: []), \
             mock.patch.object(sources, "_download", dl):
            st = sources.fetch(["q"], self.tmp / "w", pause=0, log=lambda *_: None)
        self.assertEqual((st["downloaded"], st["failed"]), (0, 1))

    def test_pick_pdf(self):
        files = [{"name": "a.pdf", "size": "90000000"}, {"name": "b.pdf", "size": "5000000"}, {"name": "c.txt", "size": "1"}]
        self.assertEqual(sources.ia_pick_pdf(files, max_mb=60), "b.pdf")
        self.assertIsNone(sources.ia_pick_pdf([{"name": "x.txt"}]))

    def test_fetch_skips_closed_licence_and_is_safe_to_rerun(self):
        pdf = self.tmp / "src.pdf"
        make_pdf(pdf)

        def item(i):
            lic = "https://creativecommons.org/publicdomain/zero/1.0/" if i == "open1" else ""
            return ("T " + i, lic, "", "f.pdf", "")

        def dl(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pdf.read_bytes())
            return "sha"

        with mock.patch.object(sources, "ia_search", lambda q, rows=50: [{"identifier": "open1"}, {"identifier": "closed1"}]), \
             mock.patch.object(sources, "ia_item", item), \
             mock.patch.object(sources, "commons_search", lambda q, limit=30: []), \
             mock.patch.object(sources, "_download", dl):
            work = self.tmp / "w"
            st = sources.fetch(["q"], work, pause=0, log=lambda *_: None)
            self.assertEqual((st["downloaded"], st["skipped_licence"]), (1, 1))
            self.assertEqual([r["id"] for r in sources.load_sources(work / "sources.csv")], ["ia_open1"])
            self.assertIn("licence not clearly open", (work / "skipped.csv").read_text(encoding="utf-8"))
            again = sources.fetch(["q"], work, pause=0, log=lambda *_: None)
            self.assertEqual(again["downloaded"], 0)
            self.assertEqual(again["skipped_known"], 1)


class TestPrepare(Base):
    def test_prepare_drops_blank_and_pick_is_round_robin(self):
        work = self.tmp / "w"
        (work / "raw").mkdir(parents=True)
        rows = []
        for sid in ("ia_a", "ia_b"):
            make_pdf(work / "raw" / (sid + ".pdf"))
            rows.append({k: "" for k in sources.FIELDS} | {"id": sid, "local_path": str(work / "raw" / (sid + ".pdf"))})
        blank = work / "raw" / "wc_blank.png"
        Image.new("RGB", (600, 800), "white").save(blank)
        rows.append({k: "" for k in sources.FIELDS} | {"id": "wc_blank", "local_path": str(blank)})
        sources.save_sources(work / "sources.csv", rows)
        self.assertEqual(prepare.prepare(work, per_item=3, dpi=60, log=lambda *_: None), 6)
        self.assertTrue((work / "contact_sheet.jpg").exists())
        chosen = prepare.pick(work, n=4)
        self.assertEqual([c["source_id"] for c in chosen], ["ia_a", "ia_b", "ia_a", "ia_b"])
        rejected = chosen[0]["page_id"]
        again = prepare.pick(work, n=6, drop=[rejected])
        self.assertEqual(len(again), 5)
        self.assertNotIn(rejected, [c["page_id"] for c in again])


class TestAnnotate(Base):
    def test_parse_tsv(self):
        text, words = annotate.parse_tsv(TSV)
        self.assertEqual(text, "नमस्ते दुनिया\nबैनामा")
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0]["box"], [[10, 20], [40, 20], [40, 32], [10, 32]])

    def test_marks_find_coloured_stamp_not_black_text(self):
        im = Image.new("RGB", (800, 1000), (235, 225, 200))
        d = ImageDraw.Draw(im)
        for y in range(100, 900, 30):
            d.rectangle([60, y, 700, y + 8], fill=(20, 20, 20))
        d.ellipse([500, 600, 700, 800], outline=(200, 30, 40), width=14)
        p = self.tmp / "p.jpg"
        im.save(p)
        marks = annotate.propose_marks(p)
        self.assertEqual(len(marks), 1)
        (x0, y0), (x1, y1) = marks[0]["box"][0], marks[0]["box"][2]
        self.assertTrue(480 < x0 < 520 and 580 < y0 < 620 and 690 < x1 < 720)

    def test_annotate_writes_draft_and_never_overwrites(self):
        work = self.tmp / "w"
        (work / "images").mkdir(parents=True)
        Image.new("RGB", (400, 500), "white").save(work / "images" / "p1.jpg")
        with open(work / "selected.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=prepare.COLS)
            w.writeheader()
            w.writerow({"page_id": "p1", "source_id": "s", "page_no": 1, "width": 400, "height": 500, "ink": 0.1,
                        "path": str(work / "images" / "p1.jpg")})
        with mock.patch.object(annotate, "run_tesseract_tsv", lambda *a, **k: TSV):
            annotate.annotate(work, log=lambda *_: None)
            lp = work / "labels" / "p1.json"
            lab = json.loads(lp.read_text(encoding="utf-8"))
            self.assertEqual(lab["status"], "draft")
            self.assertEqual(lab["transcript"], "नमस्ते दुनिया\nबैनामा")
            lab["status"] = "reviewed"
            lp.write_text(json.dumps(lab, ensure_ascii=False), encoding="utf-8")
            annotate.annotate(work, log=lambda *_: None)
            self.assertEqual(json.loads(lp.read_text(encoding="utf-8"))["status"], "reviewed")


class TestReview(Base):
    def draft(self):
        work = self.tmp / "w"
        (work / "images").mkdir(parents=True)
        (work / "labels").mkdir()
        Image.new("RGB", (400, 500), "white").save(work / "images" / "p1.jpg")
        lab = {"page_id": "p1", "source_id": "s", "image": str(work / "images" / "p1.jpg"), "width": 400, "height": 500,
               "source_url": "u", "license": "PD", "status": "draft", "draft_reader": "tesseract_hin+eng",
               "transcript": "गलत पाठ", "words": [], "facts": [],
               "objects": [{"type": "", "box": [[40, 50], [140, 50], [140, 150], [40, 150]]}]}
        (work / "labels" / "p1.json").write_text(json.dumps(lab, ensure_ascii=False), encoding="utf-8")
        return work

    def test_label_studio_round_trip_and_dataset(self):
        work = self.draft()
        self.assertEqual(review.export_tasks(work), 1)
        t = json.loads((work / "ls_tasks.json").read_text(encoding="utf-8"))[0]
        self.assertTrue(t["data"]["image"].endswith("images/p1.jpg"))
        rect = t["predictions"][0]["result"][1]["value"]
        self.assertEqual((round(rect["x"]), round(rect["y"])), (10, 10))
        self.assertEqual(review.build_dataset(work), 0)          # unreviewed pages are kept out
        export = [{"data": {"page_id": "p1"}, "annotations": [{"result": [
            {"type": "textarea", "value": {"text": ["सही पाठ", "दूसरी पंक्ति"]}},
            {"type": "rectanglelabels", "value": {"x": 10, "y": 10, "width": 25, "height": 20, "rectanglelabels": ["stamp"]}}]}]}]
        (work / "exp.json").write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(review.import_export(work, work / "exp.json"), 1)
        self.assertEqual(review.build_dataset(work), 1)
        lab = json.loads((work / "dataset" / "test" / "doc_R0001.json").read_text(encoding="utf-8"))
        self.assertEqual(lab["transcript"], "सही पाठ\nदूसरी पंक्ति")
        self.assertEqual(lab["objects"][0]["type"], "stamp")
        self.assertEqual(lab["objects"][0]["box"][2], [140, 150])

    def test_dataset_is_read_by_the_existing_benchmark(self):
        work = self.draft()
        review.build_dataset(work, include_draft=True)
        self.assertEqual([p[0] for p in bench_run.find_pages(work / "dataset")], ["doc_R0001"])
        out = self.tmp / "res"
        bench_run.main(["--set", f"R={work / 'dataset'}", "--backend", "fake_perfect", "--out", str(out)])
        csvs = list(out.glob("*.csv"))
        self.assertTrue(csvs)
        rows = list(csv.DictReader(open(csvs[0], newline="", encoding="utf-8")))
        self.assertEqual(float(rows[0]["CER"]), 0.0)


if __name__ == "__main__":
    unittest.main()
