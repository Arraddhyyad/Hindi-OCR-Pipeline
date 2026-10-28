"""Score one OCR backend on one or more generated datasets and group the results.

  python -m benchmark.run --set A=/path/setA_standard/dataset --set B=/path/setB_hard/dataset \
      --backend tesseract --out runs_benchmark/tess [--clean] [--limit 20 | --spread 10]

Each dataset folder has train/ val/ test/ with doc_*.png (or .jpg), doc_*_target.png (clean copy) and doc_*.json (answer key).
Predictions are saved one file per image, so a re-run only does the missing pages.
Scores are explained in docs/SCORING.md."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from .facts import fact_hits
from .metrics import CATASTROPHIC, char_errors, corpus_rate, edit_ops, grapheme_errors, median, rate, word_errors
from .normalize import normalize
from .ocr_backends import get_backend

FACT_KEYS = ("n", "exact", "close", "num_n", "num_exact", "num_close")


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


def pick_spread(items, n):
    """n items spread evenly through the list (same pick every run). Fairer than 'the first n'."""
    if not n or n >= len(items):
        return list(items)
    if n == 1:
        return [items[0]]
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    return [items[i] for i in idx]


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
    if text is None:
        raise RuntimeError(f"{backend.name} returned nothing for {image}")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8")
    return text


def score_page(ref, hyp, digits="latin"):
    """(char errors, char len, word errors, word len, grapheme errors, grapheme len, substitutions, deletions, insertions)."""
    ref, hyp = normalize(ref, digits), normalize(hyp, digits)
    sub, dele, ins = edit_ops(ref, hyp)
    cn = len(ref)
    we, wn = word_errors(ref, hyp)
    ge, gn = grapheme_errors(ref, hyp)
    return sub + dele + ins, cn, we, wn, ge, gn, sub, dele, ins


def summarize(rows, key):
    """Group result rows by `key`. CER/WER/gCER are pooled over pages; medCER and the failed-read share are per page."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["set"], r[key])].append(r)
    out = []
    for (s, g), rs in sorted(groups.items()):
        fsum = {k: sum(r["fact_" + k] for r in rs) for k in FACT_KEYS}
        out.append({
            "set": s, key: g, "pages": len(rs),
            "CER": corpus_rate([(r["char_err"], r["char_len"]) for r in rs]),
            # CER = missed + extra. missed: key letters the reader got wrong or lost. extra: text the reader added that is not in the key.
            "missed": corpus_rate([(r["c_sub"] + r["c_del"], r["char_len"]) for r in rs]),
            "extra": corpus_rate([(r["c_ins"], r["char_len"]) for r in rs]),
            "medCER": median([r["CER"] for r in rs]),
            "failed": sum(r["CER"] > CATASTROPHIC for r in rs) / len(rs),
            "gCER": corpus_rate([(r["g_err"], r["g_len"]) for r in rs]),
            "WER": corpus_rate([(r["word_err"], r["word_len"]) for r in rs]),
            "facts": rate(fsum["exact"], fsum["n"]) if fsum["n"] else None,
            "facts_close": rate(fsum["close"], fsum["n"]) if fsum["n"] else None,
            "numbers": rate(fsum["num_exact"], fsum["num_n"]) if fsum["num_n"] else None,
        })
    return out


def _pct(v):
    return "n/a" if v is None else f"{v*100:.1f}%"


CSV_COLS = ["set", "page", "image_kind", "difficulty", "stage", "style", "char_err", "char_len", "word_err", "word_len",
            "g_err", "g_len", "c_sub", "c_del", "c_ins", "CER", "WER", "gCER"] + ["fact_" + k for k in FACT_KEYS]


def write_report(rows, out_dir, backend_name):
    out_dir = Path(out_dir)
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 4) if isinstance(r[c], float) else r[c]) for c in CSV_COLS})
    lines = [f"# Benchmark: {backend_name}", "",
             "CER, gCER, WER: pooled error rates (letters, Devanagari letter clusters, words). medCER: median page. "
             f"Failed: share of pages with CER above {CATASTROPHIC:.0%}. Facts: names, dates and amounts found word for word "
             "(close: with small slips). Numbers: the numeric facts only. CER = missed + extra: missed is key letters the reader got wrong "
             "or lost, extra is text the reader added that is not in the key (stamps, notes, stray marks). See docs/SCORING.md.", ""]
    head = "| set | {k} | pages | CER | missed | extra | medCER | failed | gCER | WER | facts | facts close | numbers |"
    for kind in sorted({r["image_kind"] for r in rows}):
        sub = [r for r in rows if r["image_kind"] == kind]
        lines += [f"## Images: {kind} ({len(sub)} pages)", ""]
        for key in ("difficulty", "stage", "style"):
            lines += [f"### By {key}", "", head.format(k=key), "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for s in summarize(sub, key):
                lines.append(f"| {s['set']} | {s[key]} | {s['pages']} | {_pct(s['CER'])} | {_pct(s['missed'])} | {_pct(s['extra'])} | {_pct(s['medCER'])} | "
                             f"{_pct(s['failed'])} | {_pct(s['gCER'])} | {_pct(s['WER'])} | {_pct(s['facts'])} | "
                             f"{_pct(s['facts_close'])} | {_pct(s['numbers'])} |")
            lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", required=True, metavar="NAME=DATASET_DIR")
    ap.add_argument("--backend", default="tesseract", help="tesseract, easyocr, qwen_vl, fake_perfect, fake_noisy")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clean", action="store_true", help="also score the clean (undamaged) copy of each page")
    ap.add_argument("--limit", type=int, help="first N pages per set (quick test)")
    ap.add_argument("--spread", type=int, help="N pages per set, spread evenly through the set (fair sample for slow readers)")
    ap.add_argument("--digits", default="latin", choices=["latin", "keep"])
    ap.add_argument("--noise", type=float, default=0.1, help="fake_noisy only")
    ap.add_argument("--model", help="qwen_vl only: Hugging Face model id")
    ap.add_argument("--max-new-tokens", type=int, default=3500, help="qwen_vl only")
    ap.add_argument("--load-4bit", action="store_true", help="qwen_vl only: load in 4-bit (for bigger models on a small GPU)")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = []
    for spec in a.set:
        name, _, path = spec.partition("=")
        found = list(find_pages(path))
        found = found[:a.limit] if a.limit else pick_spread(found, a.spread)
        pages += [(name, *p) for p in found]
    answers = {}
    for _, stem, lab, img, clean in pages:
        t = json.loads(lab.read_text(encoding="utf-8")).get("transcript", "")
        answers[str(img)] = t
        if clean:
            answers[str(clean)] = t
    kw = {}
    if a.backend == "fake_noisy":
        kw = {"rate": a.noise}
    elif a.backend == "qwen_vl":
        kw = {"model_id": a.model, "max_new_tokens": a.max_new_tokens, "load_4bit": a.load_4bit}
    backend = get_backend(a.backend, answers, **kw)

    rows = []
    for n, (name, stem, lab, img, clean) in enumerate(pages, 1):
        label = json.loads(lab.read_text(encoding="utf-8"))
        ref = label.get("transcript", "")
        for kind, path in (("damaged", img), ("clean", clean if a.clean else None)):
            if path is None:
                continue
            hyp = read_cached(backend, path, out / "preds" / backend.name / name / (path.stem + ".txt"))
            ce, cn, we, wn, ge, gn, c_sub, c_del, c_ins = score_page(ref, hyp, a.digits)
            fh = fact_hits(label.get("facts"), hyp, a.digits)
            rows.append({"set": name, "page": stem, "image_kind": kind, **tags(label),
                         "char_err": ce, "char_len": cn, "word_err": we, "word_len": wn, "g_err": ge, "g_len": gn,
                         "c_sub": c_sub, "c_del": c_del, "c_ins": c_ins,
                         "CER": rate(ce, cn), "WER": rate(we, wn), "gCER": rate(ge, gn),
                         **{"fact_" + k: fh[k] for k in FACT_KEYS}})
        if n % 10 == 0:
            print(f"{n}/{len(pages)} pages", flush=True)
    write_report(rows, out, backend.name)
    print(f"done: {len(rows)} scores -> {out/'summary.md'}")


if __name__ == "__main__":
    main()
