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


def crop_surround(im: Image.Image, margin: float = 0.012) -> Image.Image:
    """Photos of paper often include a plain grey/white surround. Crop to the paper (colour differs from the border strip)."""
    a = np.asarray(im.convert("RGB")).astype(np.float32); h, w = a.shape[:2]
    strip = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    bg = np.median(strip, axis=0); d = np.abs(a - bg).max(axis=2)
    m = d > 22
    cols, rows = m.mean(axis=0) > 0.5, m.mean(axis=1) > 0.5
    if not cols.any() or not rows.any():
        return im
    x0, x1 = np.where(cols)[0][[0, -1]]; y0, y1 = np.where(rows)[0][[0, -1]]
    mx, my = int(w * margin), int(h * margin)
    x0, x1, y0, y1 = x0 + mx, x1 - mx, y0 + my, y1 - my
    if (x1 - x0) * (y1 - y0) < 0.5 * w * h:
        return im
    return im.crop((x0, y0, x1, y1))


def tape_from_black(im: Image.Image) -> Image.Image:
    """Clear tape photographed on black: R=specular highlight (0..255), A=tape silhouette (rough filled outline)."""
    import cv2
    g = np.asarray(im.convert("L"))
    core = (g > 28).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
    if n > 1:
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])); core = (lab == k).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    sil = cv2.GaussianBlur(core.astype(np.float32), (0, 0), 1.5)
    ys, xs = np.where(core > 0)
    out = np.dstack([g, g, g, (sil * 255).astype(np.uint8)])
    return Image.fromarray(out, "RGBA").crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def clean_alpha_blob(im: Image.Image) -> Image.Image:
    """Keep only the largest connected opaque blob of a cut-out (removes stray residue left by background removal)."""
    import cv2
    a = np.asarray(im).copy()
    core = (a[..., 3] > 110).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core)
    if n <= 2:
        return im
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    keep = cv2.dilate((lab == k).astype(np.uint8), np.ones((9, 9), np.uint8))
    a[..., 3] = (a[..., 3] * keep).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


class Asset:
    def __init__(self, root: Path, row: dict):
        self.path, self.category, self.background = root / row["file"], row["category"], row["background"]
        self.name = Path(row["file"]).stem
        self.era = row.get("era") or ""
        self.notes = row.get("notes") or ""
        self._img = None

    def load(self) -> Image.Image:
        if self._img is None:
            im = Image.open(self.path)
            if self.category == "tape" and self.background == "black":
                self._img = tape_from_black(im)
            elif self.category == "tape" and self.background == "alpha":
                self._img = clean_alpha_blob(crop_to_alpha(im.convert("RGBA"), thr=20, trim=0.0))
            elif self.category == "paper" and self.era:
                self._img = crop_surround(im.convert("RGB"))
            elif self.category in ("paper", "torn_edges", "creases"):
                self._img = im.convert("RGB")
            elif self.background == "alpha":
                self._img = crop_to_alpha(im.convert("RGBA"))
            else:
                self._img = crop_to_alpha(white_to_alpha(im))
        return self._img


class AssetLib:
    """eras: None = only the original assets (rows with an empty `era`). A list such as ["", "v3"] also includes the newer batches,
    so older configs keep producing exactly the same pages."""
    def __init__(self, root, skip=(), eras=None):
        self.root = Path(root)
        allowed = {""} if eras is None else {("" if e in ("", "legacy") else e) for e in eras}
        rows = [r for r in csv.DictReader(open(self.root / "manifest.csv", encoding="utf-8"))
                if Path(r["file"]).stem not in set(skip) and (r.get("era") or "") in allowed]
        self.by_cat = {}
        for r in rows:
            self.by_cat.setdefault(r["category"], []).append(Asset(self.root, r))

    def get(self, cat):
        return self.by_cat.get(cat, [])

    def pick(self, cat, rng: random.Random):
        items = self.get(cat)
        return rng.choice(items) if items else None
