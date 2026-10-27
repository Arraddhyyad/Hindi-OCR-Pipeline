"""Run:  python -m unittest tests.test_benchmark -v     (no OCR tool needed)"""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from benchmark.metrics import char_errors, corpus_rate, edit_distance, grapheme_errors, median, rate, word_errors
from benchmark.graphemes import graphemes
from benchmark.facts import fact_hits
from benchmark.normalize import normalize
from benchmark import run as bench_run
from benchmark import ocr_backends


class TestNormalize(unittest.TestCase):
    def test_same_look_different_codes_match(self):
        a = "क़"          # क + nukta
        b = "क़"           # precomposed क़ (NFC decomposes it to the same sequence)
        self.assertEqual(normalize(a), normalize(b))

    def test_zero_width_removed(self):
        self.assertEqual(normalize("क‍ष"), "कष")

    def test_digits_and_spaces(self):
        self.assertEqual(normalize(" ४५०  रुपये\n"), "450 रुपये")
        self.assertEqual(normalize("४५०", digits="keep"), "४५०")


class TestMetrics(unittest.TestCase):
    def test_distance(self):
        self.assertEqual(edit_distance("kitten", "sitting"), 3)
        self.assertEqual(edit_distance("", "abc"), 3)
        self.assertEqual(edit_distance(["a", "b"], ["a", "c"]), 1)

    def test_cer_wer(self):
        self.assertEqual(char_errors("नमस्ते", "नमस्ते"), (0, 6))
        e, n = char_errors("abcd", "abxd")
        self.assertEqual(rate(e, n), 0.25)
        self.assertEqual(word_errors("a b c d", "a b d"), (1, 4))

    def test_corpus_weights_long_pages(self):
        # a long perfect page and a short bad page: pooled rate is not the mean of the two rates
        self.assertAlmostEqual(corpus_rate([(0, 900), (50, 100)]), 0.05)

    def test_empty_reference(self):
        self.assertEqual(rate(0, 0), 0.0)
        self.assertEqual(rate(3, 0), 1.0)


class TestGraphemes(unittest.TestCase):
    def test_conjunct_and_matra_are_one_letter(self):
        self.assertEqual(graphemes("क्षेत्र"), ["क्षे", "त्र"])
        self.assertEqual(graphemes("हिंदी"), ["हिं", "दी"])
        self.assertEqual(graphemes("ab c"), ["a", "b", " ", "c"])

    def test_one_wrong_matra_is_one_letter_error(self):
        # same word, one vowel sign different: 1 error in letters, but counted as 1 of 3 here, not 2 characters
        e, n = grapheme_errors("किताब", "कीताब")
        self.assertEqual((e, n), (1, 3))
        ce, cn = char_errors("किताब", "कीताब")
        self.assertEqual((ce, cn), (1, 5))


class TestMedianAndFailed(unittest.TestCase):
    def test_median(self):
        self.assertEqual(median([0.1, 0.9, 0.2]), 0.2)
        self.assertEqual(median([0.1, 0.3]), 0.2)
        self.assertEqual(median([]), 0.0)


class TestFacts(unittest.TestCase):
    FACTS = ["२ सितंबर १९७५", "अमरपुर", "१८,५०,०००/-", "शांति गुप्ता"]

    def test_all_found_even_with_other_digit_style(self):
        hyp = "दिनांक 2 सितंबर 1975 ग्राम अमरपुर रुपये 18,50,000/- श्रीमती शांति गुप्ता"
        h = fact_hits(self.FACTS, hyp)
        self.assertEqual((h["n"], h["exact"], h["num_n"], h["num_exact"]), (4, 4, 2, 2))

    def test_missing_fact_not_counted(self):
        h = fact_hits(self.FACTS, "ग्राम अमरपुर")
        self.assertEqual((h["exact"], h["num_exact"]), (1, 0))

    def test_empty(self):
        self.assertEqual(fact_hits([], "x")["n"], 0)
        self.assertEqual(fact_hits(None, "x")["n"], 0)

    def test_close_catches_small_slip(self):
        from benchmark import facts
        if facts._fuzz is None:
            self.skipTest("rapidfuzz not installed")
        h = fact_hits(["शांति गुप्ता"], "श्रीमती शांती गुप्ता ने")      # one vowel sign different
        self.assertEqual((h["exact"], h["close"]), (0, 1))


def make_dataset(root, n=6):
    """Tiny fake dataset: blank images + labels with the same keys the real generator writes."""
    d = Path(root) / "dataset" / "train"
    d.mkdir(parents=True)
    classes = ["easy", "medium", "hard"]
    for i in range(n):
        stem = f"doc_{i:07d}"
        Image.new("RGB", (40, 40), "white").save(d / f"{stem}.png")
        Image.new("RGB", (40, 40), "white").save(d / f"{stem}_target.png")
        (d / f"{stem}.json").write_text(json.dumps({
            "transcript": "यह विक्रय पत्र आज दिनांक २ सितंबर १९७५ को लिखा गया " * 3,
            "facts": ["२ सितंबर १९७५", "विक्रय पत्र"],
            "difficulty": {"class": classes[i % 3], "score": 0.1},
            "stage": {"stage": 1 + i % 5},
            "style": {"page_style": "printed" if i % 2 else "handwritten"},
        }, ensure_ascii=False), encoding="utf-8")
    return Path(root) / "dataset"


class TestEndToEnd(unittest.TestCase):
    def run_bench(self, backend, extra=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ds = make_dataset(tmp.name)
        out = Path(tmp.name) / "out"
        bench_run.main(["--set", f"T={ds}", "--backend", backend, "--out", str(out), *extra])
        import csv
        with open(out / "results.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return out, rows

    def test_perfect_gives_zero_error(self):
        out, rows = self.run_bench("fake_perfect")
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(float(r["CER"]) == 0 for r in rows))
        self.assertIn("By difficulty", (out / "summary.md").read_text(encoding="utf-8"))

    def test_noisy_gives_some_error_and_groups(self):
        out, rows = self.run_bench("fake_noisy", ["--noise", "0.2"])
        cer = [float(r["CER"]) for r in rows]
        self.assertTrue(0.05 < sum(cer) / len(cer) < 0.35)
        self.assertEqual({r["difficulty"] for r in rows}, {"easy", "medium", "hard"})

    def test_clean_flag_adds_second_kind(self):
        _, rows = self.run_bench("fake_perfect", ["--clean"])
        self.assertEqual({r["image_kind"] for r in rows}, {"damaged", "clean"})
        self.assertEqual(len(rows), 12)

    def test_cached_predictions_reused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ds = make_dataset(tmp.name, 2)
        out = Path(tmp.name) / "out"
        args = ["--set", f"T={ds}", "--backend", "fake_perfect", "--out", str(out)]
        bench_run.main(args)
        f = next((out / "preds").rglob("*.txt"))
        f.write_text("EDITED", encoding="utf-8")      # a re-run must read this file, not call the OCR again
        bench_run.main(args)
        self.assertIn("EDITED", f.read_text(encoding="utf-8"))


class TestTesseractDecoding(unittest.TestCase):
    def test_utf8_output_is_decoded_not_cp1252(self):
        """Regression: on Windows, text=True used cp1252 and crashed on Devanagari output."""
        import subprocess
        from unittest import mock
        out_bytes = "यह विक्रय पत्र\n".encode("utf-8")
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=out_bytes, stderr=b"")
        with mock.patch("subprocess.run", return_value=fake) as m:
            text = ocr_backends.Tesseract().read("page.png")
        self.assertEqual(text.strip(), "यह विक्रय पत्र")
        self.assertNotIn("text", m.call_args.kwargs)    # must not ask subprocess to decode for us

    def test_failure_raises_with_message(self):
        import subprocess
        from unittest import mock
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"Error: no hin model")
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(RuntimeError):
                ocr_backends.Tesseract().read("page.png")


class TestReportColumns(unittest.TestCase):
    def test_new_columns_and_values(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ds = make_dataset(tmp.name)
        out = Path(tmp.name) / "out"
        bench_run.main(["--set", f"T={ds}", "--backend", "fake_perfect", "--out", str(out)])
        md = (out / "summary.md").read_text(encoding="utf-8")
        for col in ("medCER", "failed", "gCER", "facts close", "numbers"):
            self.assertIn(col, md)
        import csv
        with open(out / "results.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(all(float(r["gCER"]) == 0 and r["fact_n"] == "2" and r["fact_exact"] == "2" for r in rows))

    def test_failed_share_counts_pages_above_half(self):
        rows = [{"set": "T", "k": "x", "CER": c, "char_err": 0, "char_len": 1, "g_err": 0, "g_len": 1,
                 "word_err": 0, "word_len": 1, **{"fact_" + k: 0 for k in bench_run.FACT_KEYS}} for c in (0.1, 0.6, 0.9, 0.2)]
        s = bench_run.summarize(rows, "k")[0]
        self.assertEqual(s["failed"], 0.5)
        self.assertAlmostEqual(s["medCER"], 0.4)


class TestSpread(unittest.TestCase):
    def test_spread_is_even_and_stable(self):
        items = list(range(100))
        pick = bench_run.pick_spread(items, 5)
        self.assertEqual(pick, [0, 25, 50, 74, 99])      # first and last page included
        self.assertEqual(pick, bench_run.pick_spread(items, 5))
        self.assertEqual(bench_run.pick_spread(items, 500), items)

    def test_run_with_spread(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ds = make_dataset(tmp.name, 6)
        out = Path(tmp.name) / "out"
        bench_run.main(["--set", f"T={ds}", "--backend", "fake_perfect", "--out", str(out), "--spread", "3"])
        import csv
        with open(out / "results.csv", encoding="utf-8") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 3)


class TestControl(unittest.TestCase):
    def test_control_pages_and_labels(self):
        from benchmark import make_control
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = make_dataset(tmp.name, 3)
        rendered = []

        def fake_render(html_path, png_path, height):
            rendered.append(height)
            html = Path(html_path).read_text(encoding="utf-8")
            self.assertIn("विक्रय पत्र", html)          # the page text is in the page
            Image.new("RGB", (40, 40), "white").save(png_path)

        out = Path(tmp.name) / "ctl"
        font = Path(tmp.name) / "f.ttf"
        font.write_bytes(b"x")
        n = make_control.make_control(src, out, font, 26, render=fake_render)
        self.assertEqual(n, 3)
        label = json.loads((out / "train" / "doc_0000000.json").read_text(encoding="utf-8"))
        self.assertEqual(label["difficulty"]["class"], "control")
        self.assertTrue(label["transcript"].startswith("यह विक्रय"))
        self.assertTrue(all(h > 200 for h in rendered))
        # the control set can be scored like any other set
        res = Path(tmp.name) / "res"
        bench_run.main(["--set", f"P={out}", "--backend", "fake_perfect", "--out", str(res)])
        self.assertIn("control", (res / "summary.md").read_text(encoding="utf-8"))

    def test_rerun_skips_finished_pages(self):
        from benchmark import make_control
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = make_dataset(tmp.name, 3)
        calls = []

        def fake_render(html_path, png_path, height):
            calls.append(1)
            Image.new("RGB", (40, 40), "white").save(png_path)

        font = Path(tmp.name) / "f.ttf"
        font.write_bytes(b"x")
        out = Path(tmp.name) / "ctl"
        make_control.make_control(src, out, font, 26, render=fake_render, limit=2)
        self.assertEqual(len(calls), 2)
        n = make_control.make_control(src, out, font, 26, render=fake_render)
        self.assertEqual((n, len(calls)), (3, 3))        # only the missing page was drawn

    def test_browser_that_writes_the_file_but_never_exits(self):
        """Regression: headless Edge on Windows wrote the screenshot and then hung."""
        import sys
        import time
        from benchmark.make_control import run_until_file
        png = Path(tempfile.mkdtemp()) / "shot.png"
        code = f"import time; open(r'{png}', 'wb').write(b'x' * 100); time.sleep(120)"
        t0 = time.time()
        run_until_file([sys.executable, "-c", code], png, wait=30)
        self.assertLess(time.time() - t0, 20)
        self.assertTrue(png.exists())

    def test_browser_that_writes_nothing_raises(self):
        import sys
        from benchmark.make_control import run_until_file
        png = Path(tempfile.mkdtemp()) / "none.png"
        with self.assertRaises(RuntimeError):
            run_until_file([sys.executable, "-c", "pass"], png, wait=10)

    def test_height_grows_with_text(self):
        from benchmark.make_control import page_height
        self.assertGreater(page_height("क" * 3000, 26), page_height("क" * 300, 26))


class TestBackendNames(unittest.TestCase):
    def test_unknown_backend_lists_choices(self):
        with self.assertRaises(ValueError) as cm:
            ocr_backends.get_backend("nope")
        self.assertIn("qwen_vl", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
