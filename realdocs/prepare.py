"""Turn downloaded files into page images, screen out blanks, and pick a spread of about 50."""
import csv
from pathlib import Path

import numpy as np
from PIL import Image

from .sources import load_sources

COLS = ["page_id", "source_id", "page_no", "width", "height", "ink", "path"]
MIN_INK, MAX_INK = 0.015, 0.40   # share of dark pixels: below = blank page, above = a photo or a black scan


def ink_share(img):
    g = np.asarray(img.convert("L"))
    return float((g < 140).mean())


def devanagari_share(text):
    """Share of letters that are Devanagari (0 to 1). Digits, punctuation and spaces are ignored."""
    letters = [c for c in text if c.isalpha()]
    return sum("\u0900" <= c <= "\u097f" for c in letters) / len(letters) if letters else 0.0


def hindi_share_of_page(img_path):
    """Quick Tesseract read of a page, then the Devanagari share of what it found."""
    import subprocess
    r = subprocess.run(["tesseract", str(img_path), "-", "-l", "hin+eng", "--psm", "3"], capture_output=True, timeout=300)
    return devanagari_share(r.stdout.decode("utf-8", "replace"))


def pages_from_pdf(path, per_item=3, dpi=200):
    """Yield (page_no, PIL image) for up to `per_item` pages spread through the PDF (skipping the first and last page)."""
    import pymupdf
    doc = pymupdf.open(path)
    n = len(doc)
    if n == 0:
        return
    lo, hi = (1, n - 2) if n > 4 else (0, n - 1)
    idx = sorted({round(lo + i * (hi - lo) / max(per_item - 1, 1)) for i in range(per_item)}) if per_item > 1 else [lo]
    for i in idx:
        pix = doc[i].get_pixmap(dpi=dpi)
        yield i + 1, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def prepare(work_dir, per_item=3, dpi=200, max_side=2600, min_hindi=0.5, reader=None, candidates=6, log=print):
    """Render every raw file into images/<page_id>.jpg and write pages.csv. Returns the number of pages kept.
    Pages whose text is less than `min_hindi` Devanagari are dropped (set 0 to switch the check off).
    From a PDF, `candidates` pages spread through the book are tried and the first `per_item` Hindi ones are kept.
    `reader(path) -> share` can be swapped in for tests."""
    reader = reader or hindi_share_of_page
    work = Path(work_dir)
    out = work / "images"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in load_sources(work / "sources.csv"):
        p = Path(s["local_path"])
        if not p.exists():
            log(f"missing file: {p}")
            continue
        items = pages_from_pdf(p, candidates if min_hindi > 0 else per_item, dpi) if p.suffix.lower() == ".pdf" else [(1, Image.open(p).convert("RGB"))]
        kept = 0
        for page_no, img in items:
            if kept >= per_item:
                break
            ink = ink_share(img)
            if not (MIN_INK <= ink <= MAX_INK):
                log(f"drop {s['id']} p{page_no}: ink {ink:.3f}")
                continue
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side))
            pid = f"{s['id']}_p{page_no:03d}"
            dest = out / (pid + ".jpg")
            img.save(dest, quality=92)
            if min_hindi > 0:
                share = reader(dest)
                if share < min_hindi:
                    dest.unlink()
                    log(f"drop {pid}: only {share:.0%} Devanagari")
                    continue
            kept += 1
            rows.append({"page_id": pid, "source_id": s["id"], "page_no": page_no, "width": img.width,
                         "height": img.height, "ink": round(ink, 4), "path": str(dest)})
    with open(work / "pages.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    contact_sheet(rows, work / "contact_sheet.jpg")
    return len(rows)


def contact_sheet(rows, dest, cols=8, cell=220):
    """One picture of every candidate page, so you can screen them by eye before picking."""
    if not rows:
        return
    n = len(rows)
    sheet = Image.new("RGB", (cols * cell, ((n + cols - 1) // cols) * cell), "white")
    for i, r in enumerate(rows):
        im = Image.open(r["path"])
        im.thumbnail((cell - 6, cell - 6))
        sheet.paste(im, ((i % cols) * cell + 3, (i // cols) * cell + 3))
    sheet.save(dest, quality=80)


def pick(work_dir, n=50, drop=()):
    """Choose n pages round-robin across sources, so no single book dominates. `drop` = page ids to leave out
    (the ones you rejected on the contact sheet). Writes selected.csv."""
    work = Path(work_dir)
    with open(work / "pages.csv", newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["page_id"] not in set(drop)]
    by = {}
    for r in rows:
        by.setdefault(r["source_id"], []).append(r)
    chosen, k = [], 0
    while len(chosen) < n and any(by.values()):
        for sid in sorted(by):
            if by[sid] and len(chosen) < n:
                chosen.append(by[sid].pop(0))
        k += 1
    with open(work / "selected.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(chosen)
    return chosen
