"""Rank the writers in the ICDAR word-level Hindi set by how slanted and joined their handwriting is.

Reads the zip directly (nothing is extracted). For each writer (page ID) we sample some words,
measure the lean of the strokes and how connected the letters are, then list the writers whose
hand is closest to the style we want. A picture of each top writer's words is saved so you can
check by eye.

Setup (once, inside the .venv-flux environment):  pip install scipy
Run:
  python handwriting/rank_writers_by_slant.py ~/Downloads/Word_Level*Training*.zip --out flux_data/slant_report
Outputs in the --out folder:
  writers.csv    every writer with its measurements
  top_writers.png  one row of words per top writer (look at this!)
  and it prints a ready-made --writer-ids list for prepare_flux_edit_pairs.py
"""
import argparse, csv, io, math, os, random, re, zipfile
from collections import defaultdict
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

try:
    from scipy import ndimage
except ImportError:
    ndimage = None

DEV = re.compile(r"^[ऀ-ॿ]+$")
LINE = re.compile(r"^(image/\S+?\.jpg)\s*(.*)$")

ap = argparse.ArgumentParser()
ap.add_argument("zip")
ap.add_argument("--out", default="flux_data/slant_report")
ap.add_argument("--per-writer", type=int, default=12, help="words measured per writer")
ap.add_argument("--min-chars", type=int, default=3)
ap.add_argument("--target-slant", type=float, default=20.0,
                help="wanted lean in degrees, positive = leaning right (the notebook page measures roughly 15-25)")
ap.add_argument("--top", type=int, default=20)
ap.add_argument("--max-writers", type=int, default=0, help="0 = all writers (takes several minutes)")
ap.add_argument("--seed", type=int, default=7)
a = ap.parse_args()

H = 64
ANGLES = np.deg2rad(np.arange(-35, 36, 2.5))


def to_ink(im):
    """Grey word crop -> boolean ink mask of height H (paper tint and light removed)."""
    g = im.convert("L")
    g = g.resize((max(8, round(g.width * H / g.height)), H), Image.LANCZOS)
    pad = 8
    arr = np.pad(np.asarray(g, dtype=np.float32), pad, mode="edge")
    bg = Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
    bg = np.asarray(bg, dtype=np.float32)[pad:-pad, pad:-pad]
    r = np.asarray(g, dtype=np.float32) / np.maximum(bg, 1.0)
    return r < 0.72


def slant_deg(ink):
    """Lean of the strokes. Shear the ink at many angles; the angle that makes the vertical
    strokes line up best (sharpest column profile) is the slant. Positive = leaning right."""
    h, w = ink.shape
    rows = np.arange(h) - h / 2
    cols = np.arange(w)
    best, best_t = -1.0, 0.0
    for t in ANGLES:
        sh = np.round(np.tan(t) * rows).astype(int)
        idx = (cols[None, :] + sh[:, None] + h)       # offset keeps indices >= 0
        prof = np.bincount(idx[ink], minlength=w + 2 * h + 2)
        score = float((prof.astype(np.float64) ** 2).sum())
        if score > best:
            best, best_t = score, t
    return math.degrees(best_t)


def pieces_per_char(ink, nchars):
    if ndimage is None:
        return float("nan")
    _, n = ndimage.label(ink, structure=np.ones((3, 3)))
    return n / max(nchars, 1)


z = zipfile.ZipFile(os.path.expanduser(a.zip))
label_name = next(n for n in z.namelist() if n.endswith(".txt"))
root = label_name.rsplit("/", 1)[0]
by_writer = defaultdict(list)
for raw in z.read(label_name).decode("utf8", "replace").splitlines():
    m = LINE.match(raw.strip())
    if not m:
        continue
    path, text = m.group(1), m.group(2).strip()
    if len(text) >= a.min_chars and DEV.match(text):
        by_writer[os.path.basename(path).split("_")[0]].append((path, text))

rng = random.Random(a.seed)
writers = sorted(w for w, v in by_writer.items() if len(v) >= a.per_writer)
if a.max_writers:
    writers = rng.sample(writers, min(a.max_writers, len(writers)))
print(f"{len(by_writer)} writers; measuring {len(writers)} with >= {a.per_writer} usable words")

os.makedirs(a.out, exist_ok=True)
rows = []
for k, w in enumerate(writers):
    sample = rng.sample(by_writer[w], a.per_writer)
    sl, pp, dens = [], [], []
    for path, text in sample:
        im = Image.open(io.BytesIO(z.read(f"{root}/{path}")))
        ink = to_ink(im)
        if ink.sum() < 30:
            continue
        sl.append(slant_deg(ink)); pp.append(pieces_per_char(ink, len(text))); dens.append(ink.mean())
    if len(sl) < max(4, a.per_writer // 2):
        continue
    rows.append(dict(writer=w, words=len(by_writer[w]), slant=float(np.median(sl)),
                     slant_spread=float(np.std(sl)), pieces_per_char=float(np.nanmedian(pp)),
                     ink=float(np.mean(dens)), sample=[p for p, _ in sample]))
    if (k + 1) % 200 == 0:
        print(f"  {k + 1}/{len(writers)}")

for r in rows:
    r["distance"] = abs(r["slant"] - a.target_slant) + 6 * r["slant_spread"] / 10
rows.sort(key=lambda r: r["distance"])

with open(os.path.join(a.out, "writers.csv"), "w", encoding="utf8", newline="") as f:
    cw = csv.writer(f)
    cw.writerow(["writer", "words", "slant_deg", "slant_spread", "pieces_per_char", "ink_fraction", "distance_to_target"])
    for r in rows:
        cw.writerow([r["writer"], r["words"], f"{r['slant']:.1f}", f"{r['slant_spread']:.1f}",
                     f"{r['pieces_per_char']:.2f}", f"{r['ink']:.3f}", f"{r['distance']:.1f}"])

top = rows[:a.top]
cellw, cellh, per_row = 200, 90, 6
sheet = Image.new("RGB", (cellw * per_row + 150, cellh * len(top)), "white")
dr = ImageDraw.Draw(sheet)
for i, r in enumerate(top):
    dr.text((6, i * cellh + 8), f"{r['writer']}\nslant {r['slant']:+.0f} deg\npieces/char {r['pieces_per_char']:.1f}", fill="black")
    for j, p in enumerate(r["sample"][:per_row]):
        im = Image.open(io.BytesIO(z.read(f"{root}/{p}"))).convert("RGB")
        im.thumbnail((cellw - 8, cellh - 8))
        sheet.paste(im, (150 + j * cellw + 4, i * cellh + 4))
sheet.save(os.path.join(a.out, "top_writers.png"))

sl_all = np.array([r["slant"] for r in rows])
print(f"\nmeasured {len(rows)} writers. Slant across all writers: median {np.median(sl_all):+.1f} deg, "
      f"10th-90th percentile {np.percentile(sl_all, 10):+.1f} to {np.percentile(sl_all, 90):+.1f}")
print(f"{int((sl_all >= a.target_slant - 5).sum())} writers lean at least {a.target_slant - 5:.0f} deg to the right")
print("\nclosest to the target style:")
for r in top[:10]:
    print(f"  {r['writer']}: slant {r['slant']:+.1f}, spread {r['slant_spread']:.1f}, pieces/char {r['pieces_per_char']:.2f}")
print("\nuse them in the pair script with:\n  --writer-ids " + ",".join(r["writer"] for r in top[:5]))
print(f"\nlook at {os.path.join(a.out, 'top_writers.png')} before you trust the ranking")
