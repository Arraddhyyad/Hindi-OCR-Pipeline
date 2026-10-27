"""Run:  python -m unittest tests.test_benchmark -v     (no OCR tool needed)"""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from benchmark.metrics import char_errors, corpus_rate, edit_distance, rate, word_errors
from benchmark.normalize import normalize
from benchmark import run as bench_run


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


if __name__ == "__main__":
    unittest.main()
