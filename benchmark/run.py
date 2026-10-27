"""Score one OCR backend on one or more generated datasets and group the results.

  python -m benchmark.run --set A=/path/setA_standard/dataset --set B=/path/setB_hard/dataset \
      --backend tesseract --out runs_benchmark/tess [--clean] [--limit 20]

Each dataset folder has train/ val/ test/ with doc_*.png (or .jpg), doc_*_target.png (clean copy) and doc_*.json (answer key).
Predictions are saved one file per image, so a re-run only does the missing pages."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from .metrics import char_errors, corpus_rate, rate, word_errors
from .normalize import normalize
from .ocr_backends import get_backend


def find_pages(dataset_dir):
    """Yield (stem, label_path, image_path, clean_path or None) for every page in train/val/test."""
    for split in ("train", "val", "test"):
        d = Path(dataset_dir) / split
        if not d.is_dir():
            continue
        for lab in sorted(d.glob("doc_*.json")):
            if lab.stem.endswith("_target"):
                continue
            img = next((p for p in (lab.with_suffix(".png"), lab.with_suffix(".jpg")) if p.exists()), None)
            clean = d / (lab.stem + "_target.png")
            if img:
                yield lab.stem, lab, img, (clean if clean.exists() else None)


def tags(label):
    """The groups a page can be reported under. Missing keys (older labels) become 'n/a'."""
    st = label.get("stage")
    return {
        "difficulty": (label.get("difficulty") or {}).get("class", "n/a"),
        "stage": str(st.get("stage") if isinstance(st, dict) else st if st is not None else "n/a"),
        "style": (label.get("style") or {}).get("page_style", "n/a"),
    }


def read_cached(backend, image, cache_file):
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    text = backend.read(image)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8")
    return text


def score_page(ref, hyp, digits="latin"):
    ref, hyp = normalize(ref, digits), normalize(hyp, digits)
    ce, cn = char_errors(ref, hyp)
    we, wn = word_errors(ref, hyp)
    return ce, cn, we, wn


def summarize(rows, key):
    """Group result rows by `key` and report corpus CER / WER and page counts."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["set"], r[key])].append(r)
    out = []
    for (s, g), rs in sorted(groups.items()):
        out.append({"set": s, key: g, "pages": len(rs),
                    "CER": corpus_rate([(r["char_err"], r["char_len"]) for r in rs]),
                    "WER": corpus_rate([(r["word_err"], r["word_len"]) for r in rs])})
    return out


def write_report(rows, out_dir, backend_name):
    out_dir = Path(out_dir)
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        cols = ["set", "page", "image_kind", "difficulty", "stage", "style", "char_err", "char_len", "word_err", "word_len", "CER", "WER"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 4) if isinstance(r[c], float) else r[c]) for c in cols})
    lines = [f"# Benchmark: {backend_name}", ""]
    for kind in sorted({r["image_kind"] for r in rows}):
        sub = [r for r in rows if r["image_kind"] == kind]
        lines += [f"## Images: {kind} ({len(sub)} pages)", ""]
        for key in ("difficulty", "stage", "style"):
            lines += [f"### By {key}", "", f"| set | {key} | pages | CER | WER |", "|---|---|---|---|---|"]
            for s in summarize(sub, key):
                lines.append(f"| {s['set']} | {s[key]} | {s['pages']} | {s['CER']*100:.1f}% | {s['WER']*100:.1f}% |")
            lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", required=True, metavar="NAME=DATASET_DIR")
    ap.add_argument("--backend", default="tesseract")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clean", action="store_true", help="also score the clean (undamaged) copy of each page")
    ap.add_argument("--limit", type=int, help="first N pages per set (quick test)")
    ap.add_argument("--digits", default="latin", choices=["latin", "keep"])
    ap.add_argument("--noise", type=float, default=0.1, help="fake_noisy only")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = []
    for spec in a.set:
        name, _, path = spec.partition("=")
        for i, p in enumerate(find_pages(path)):
            if a.limit and i >= a.limit:
                break
            pages.append((name, *p))
    answers = {}
    for _, stem, lab, img, clean in pages:
        t = json.loads(lab.read_text(encoding="utf-8")).get("transcript", "")
        answers[str(img)] = t
        if clean:
            answers[str(clean)] = t
    kw = {"rate": a.noise} if a.backend == "fake_noisy" else {}
    backend = get_backend(a.backend, answers, **kw)

    rows = []
    for n, (name, stem, lab, img, clean) in enumerate(pages, 1):
        label = json.loads(lab.read_text(encoding="utf-8"))
        ref = label.get("transcript", "")
        for kind, path in (("damaged", img), ("clean", clean if a.clean else None)):
            if path is None:
                continue
            hyp = read_cached(backend, path, out / "preds" / backend.name / name / (path.stem + ".txt"))
            ce, cn, we, wn = score_page(ref, hyp, a.digits)
            rows.append({"set": name, "page": stem, "image_kind": kind, **tags(label),
                         "char_err": ce, "char_len": cn, "word_err": we, "word_len": wn,
                         "CER": rate(ce, cn), "WER": rate(we, wn)})
        if n % 10 == 0:
            print(f"{n}/{len(pages)} pages", flush=True)
    write_report(rows, out, backend.name)
    print(f"done: {len(rows)} scores -> {out/'summary.md'}")


if __name__ == "__main__":
    main()
