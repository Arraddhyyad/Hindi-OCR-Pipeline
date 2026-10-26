"""Asset library. Reads assets/manifest.csv and prepares each file for multiply compositing.

Prepared form is always RGBA where RGB is the ink colour and A is ink density:
  alpha assets : used as is, cropped to the opaque bounding box
  white assets : white is removed (colour un-mixing), so any ink on white paper works
"""
import csv, random
from pathlib import Path
import numpy as np
from PIL import Image


def white_to_alpha(im: Image.Image) -> Image.Image:
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    alpha = np.clip(1 - a.min(axis=2) / 255.0, 0, 1)
    rgb = (a - (1 - alpha)[..., None] * 255) / np.maximum(alpha, 1e-3)[..., None]
    out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def crop_to_alpha(im: Image.Image, thr: int = 40, pad: int = 4, trim: float = 0.004) -> Image.Image:
    """Crop to where the ink is. Faint specks on a large canvas are ignored by trimming the outer `trim` of ink mass."""
    a = (np.asarray(im.split()[3]) > thr).astype(np.float64)
    if a.sum() == 0:
        return im
    def span(proj):
        c = np.cumsum(proj) / proj.sum()
        return int(np.searchsorted(c, trim)), int(np.searchsorted(c, 1 - trim))
    x0, x1 = span(a.sum(0)); y0, y1 = span(a.sum(1))
    return im.crop((max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad + 1), min(im.height, y1 + pad + 1)))


def tint(im: Image.Image, color) -> Image.Image:
    arr = np.asarray(im).copy()
    arr[..., :3] = color
    return Image.fromarray(arr, "RGBA")


class Asset:
    def __init__(self, root: Path, row: dict):
        self.path, self.category, self.background = root / row["file"], row["category"], row["background"]
        self.name = Path(row["file"]).stem
        self._img = None

    def load(self) -> Image.Image:
        if self._img is None:
            im = Image.open(self.path)
            if self.category in ("paper", "torn_edges", "creases"):
                self._img = im.convert("RGB")
            elif self.background == "alpha":
                self._img = crop_to_alpha(im.convert("RGBA"))
            else:
                self._img = crop_to_alpha(white_to_alpha(im))
        return self._img


class AssetLib:
    def __init__(self, root, skip=()):
        self.root = Path(root)
        rows = [r for r in csv.DictReader(open(self.root / "manifest.csv", encoding="utf-8")) if Path(r["file"]).stem not in set(skip)]
        self.by_cat = {}
        for r in rows:
            self.by_cat.setdefault(r["category"], []).append(Asset(self.root, r))

    def get(self, cat):
        return self.by_cat.get(cat, [])

    def pick(self, cat, rng: random.Random):
        items = self.get(cat)
        return rng.choice(items) if items else None
