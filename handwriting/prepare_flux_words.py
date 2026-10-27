"""Build a small LoRA training set from the word-level Hindi handwriting zip.

Reads the zip directly (nothing is extracted). Words from the same page share one
writer, so we pick a few writers and a few words from each, paste every word onto a
plain white square, and write one caption file per image.

Run:
  python3 handwriting/prepare_flux_words.py ~/Downloads/Word_Level_Hindi_Training_Set.zip \
      --out flux_data/words_pilot --writers 4 --per-writer 10 --size 512
Output: <out>/*.png, <out>/*.txt (captions), <out>/manifest.csv
"""
import argparse, csv, io, os, random, re, zipfile
import numpy as np
from collections import defaultdict
from PIL import Image, ImageFilter


def flatten(im):
    """Remove the grey paper tint and uneven light so only ink is left on white.
    The paper colour is estimated by erasing the dark strokes (max filter) and blurring."""
    pad = 16
    arr = np.pad(np.asarray(im, dtype=np.float32), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    big = Image.fromarray(arr.astype(np.uint8))
    bg = big.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(10))
    bg = np.asarray(bg, dtype=np.float32)[pad:-pad, pad:-pad]
    r = np.asarray(im, dtype=np.float32) / np.maximum(bg, 1.0)
    r = np.clip((r - 0.45) / 0.5, 0, 1)
    return Image.fromarray((r * 255).astype(np.uint8))

DEV = re.compile(r"^[ऀ-ॿ]+$")
LINE = re.compile(r"^(image/\S+?\.jpg)\s*(.*)$")

ap = argparse.ArgumentParser()
ap.add_argument("zip")
ap.add_argument("--out", default="flux_data/words_pilot")
ap.add_argument("--writers", type=int, default=4)
ap.add_argument("--per-writer", type=int, default=10)
ap.add_argument("--size", type=int, default=512)
ap.add_argument("--trigger", default="HWDV1")
ap.add_argument("--min-chars", type=int, default=3)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--raw", action="store_true", help="keep the original grey paper instead of flattening")
a = ap.parse_args()

z = zipfile.ZipFile(os.path.expanduser(a.zip))
label_name = next(n for n in z.namelist() if n.endswith(".txt"))
root = label_name.rsplit("/", 1)[0]
by_writer = defaultdict(list)
for raw in z.read(label_name).decode("utf8", "replace").splitlines():
    m = LINE.match(raw.strip())
    if not m:
        continue
    path, text = m.group(1), m.group(2).strip()
    if len(text) < a.min_chars or not DEV.match(text):
        continue
    writer = os.path.basename(path).split("_")[0]
    by_writer[writer].append((path, text))

rng = random.Random(a.seed)
eligible = sorted(w for w, v in by_writer.items() if len(v) >= a.per_writer)
chosen = rng.sample(eligible, min(a.writers, len(eligible)))
print(f"{len(by_writer)} writers have usable words; {len(eligible)} have >= {a.per_writer}; using {chosen}")

os.makedirs(a.out, exist_ok=True)
rows, S = [], a.size
for w in chosen:
    for path, text in rng.sample(by_writer[w], a.per_writer):
        im = Image.open(io.BytesIO(z.read(f"{root}/{path}"))).convert("RGB")
        if not a.raw:
            im = flatten(im)
        k = min(0.9 * S / im.width, 0.5 * S / im.height)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        canvas = Image.new("RGB", (S, S), (255, 255, 255))
        canvas.paste(im, ((S - im.width) // 2, (S - im.height) // 2))
        stem = os.path.splitext(os.path.basename(path))[0]
        canvas.save(os.path.join(a.out, f"{stem}.png"))
        open(os.path.join(a.out, f"{stem}.txt"), "w", encoding="utf8").write(
            f"{a.trigger} handwritten Hindi word on white paper: {text}")
        rows.append((f"{stem}.png", w, text))
with open(os.path.join(a.out, "manifest.csv"), "w", encoding="utf8", newline="") as f:
    csv.writer(f).writerows([("file", "writer", "text")] + rows)
print(f"wrote {len(rows)} images to {a.out}")
