"""Compositing helpers. Everything is multiply-blended ink on paper, like printing."""
import math
import numpy as np
from PIL import Image


def multiply(base: np.ndarray, rgba: Image.Image, x0: int, y0: int, opacity: float = 1.0):
    """base: float32 HxWx3 in 0..1, modified in place. rgba placed with its top-left at (x0, y0)."""
    H, W = base.shape[:2]
    w, h = rgba.size
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw, ch = min(w - sx0, W - dx0), min(h - sy0, H - dy0)
    if cw <= 0 or ch <= 0:
        return
    a = np.asarray(rgba.crop((sx0, sy0, sx0 + cw, sy0 + ch))).astype(np.float32) / 255.0
    alpha = a[..., 3:4] * opacity
    base[dy0:dy0 + ch, dx0:dx0 + cw] *= 1 - alpha * (1 - a[..., :3])


def place(base, asset: Image.Image, cx: float, cy: float, width: float | None = None, height: float | None = None,
          angle: float = 0.0, opacity: float = 1.0, flip: bool = False, stretch: tuple | None = None):
    """Resize (keep aspect unless stretch=(w,h)), flip, rotate CCW by angle degrees about the centre, multiply onto base.
    Returns the rotated rectangle as a polygon in page coordinates."""
    if stretch:
        tw, th = stretch
    elif width:
        tw, th = width, asset.height * width / asset.width
    else:
        tw, th = height * asset.width / asset.height, height
    tw, th = max(2, int(round(tw))), max(2, int(round(th)))
    im = asset.resize((tw, th), Image.LANCZOS)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if angle:
        im = im.rotate(angle, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    multiply(base, im, int(round(cx - im.width / 2)), int(round(cy - im.height / 2)), opacity)
    return rect_polygon(cx, cy, tw, th, angle)


def rect_polygon(cx, cy, w, h, angle=0.0):
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append([round(cx + dx * c + dy * s, 1), round(cy - dx * s + dy * c, 1)])
    return pts


def poly_bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def transform_box(box, cx, cy, ox, oy, angle=0.0):
    """Map a box given in a snippet's own frame (centre cx,cy in snippet coordinates) to page coordinates placed with
    the snippet centre at (ox, oy) and rotated CCW by angle."""
    x0, y0, x1, y1 = box
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    pts = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        dx, dy = x - cx, y - cy
        pts.append([round(ox + dx * c + dy * s, 1), round(oy - dx * s + dy * c, 1)])
    return pts
