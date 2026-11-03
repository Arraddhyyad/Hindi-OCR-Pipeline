"""Realism ops for typed pages (v3). Pixel-level, applied inside the degradation stage before the scan geometry, so polygons need no update.

  op_tape         cellotape across a fold, a tear or the text: clear tape adds a shiny highlight and haze over the words, aged tape
                  yellows and flattens them. The tape polygon is recorded as an element (type "tape") so the benchmark can see it.
  op_stain_assets real stain photos (coffee rings, tea patches, drops) multiplied onto the page.
"""
import math
import cv2
import numpy as np
from PIL import Image
from .assets import white_to_alpha, crop_to_alpha
from .imaging import place, rect_polygon, poly_bbox


def _paste_layer(img, layer: Image.Image, cx, cy, width, angle):
    """Resize (keep aspect), rotate about the centre, return (rgb float, alpha float, x0, y0, polygon) cropped to the page."""
    tw = max(4, int(width)); th = max(4, int(layer.height * tw / layer.width))
    im = layer.resize((tw, th), Image.LANCZOS)
    if angle: im = im.rotate(angle, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    x0, y0 = int(round(cx - im.width / 2)), int(round(cy - im.height / 2))
    return im, x0, y0, rect_polygon(cx, cy, tw, th, angle)


def _window(img, im, x0, y0):
    H, W = img.shape[:2]; w, h = im.size
    sx0, sy0 = max(0, -x0), max(0, -y0); dx0, dy0 = max(0, x0), max(0, y0)
    cw, ch = min(w - sx0, W - dx0), min(h - sy0, H - dy0)
    if cw <= 0 or ch <= 0: return None
    a = np.asarray(im.crop((sx0, sy0, sx0 + cw, sy0 + ch))).astype(np.float32) / 255.0
    return a, (slice(dy0, dy0 + ch), slice(dx0, dx0 + cw))


def _anchor(st, rng, W, H):
    """Where the tape goes: along a fold line (most often), otherwise across the page. Returns centre x, y and whether it is vertical."""
    folds = getattr(st, "fold_lines", None) or []
    if folds and rng.random() < 0.7:
        kind, pos = rng.choice(folds)
        if kind == "h": return rng.uniform(0.15, 0.85) * W, pos + rng.uniform(-6, 6), False, rng.uniform(-3, 3)
        return pos + rng.uniform(-6, 6), rng.uniform(0.15, 0.85) * H, True, rng.uniform(-3, 3)
    vertical = rng.random() < 0.4
    return rng.uniform(0.15, 0.85) * W, rng.uniform(0.15, 0.85) * H, vertical, rng.uniform(-12, 12)


def op_tape(st, rng, nrng, sev, lib):
    items = lib.get("tape")
    if not items: return
    H, W = st.img.shape[:2]
    for _ in range(1 if rng.random() < 0.65 else 2):
        clear = [x for x in items if x.background == "black"]; aged = [x for x in items if x.background != "black"]
        a = rng.choice(clear if clear and (not aged or rng.random() < 0.45) else aged); layer = a.load()
        cx, cy, vertical, jitter = _anchor(st, rng, W, H)
        long_px = (H if vertical else W) * rng.uniform(0.22, 0.55) if layer.width / layer.height > 3 else W * rng.uniform(0.28, 0.5)
        if layer.width / layer.height > 3: long_px = min(long_px, 0.8 * (H if vertical else W))
        angle = (90 if vertical else 0) + jitter + rng.uniform(-1.5, 1.5)
        if rng.random() < 0.5 and a.background == "alpha": layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
        im, x0, y0, poly = _paste_layer(st.img, layer, cx, cy, long_px, -angle)
        win = _window(st.img, im, x0, y0)
        if win is None: continue
        arr, sl = win; reg = st.img[sl]
        if a.background == "black":                      # clear tape: highlight + haze, the page shows through
            hl, sil = arr[..., 0:1], arr[..., 3:4]
            hl = np.clip(hl * 1.35, 0, 1) ** 1.15 * sil
            haze = sil * rng.uniform(0.10, 0.22)         # glue/film dulls the print slightly
            lifted = reg * (1 - haze) + haze * np.array([0.93, 0.92, 0.88], np.float32)
            glare = rng.uniform(0.75, 1.0) * sev ** 0.3
            st.img[sl] = 1 - (1 - lifted) * (1 - hl * glare)
            kind = "clear"
        else:                                            # aged tape: yellow-brown film over the page, flattens contrast of the words
            al = arr[..., 3:4]; col = arr[..., :3]
            amt = rng.uniform(0.55, 0.85)
            lum = reg.mean(axis=2, keepdims=True)
            flat = reg * 0.7 + 0.3 * np.clip(lum + 0.25, 0, 1)         # words under old tape lose contrast
            under = reg * (1 - al) + flat * al
            st.img[sl] = under * (1 - al * amt) + under * col * al * amt * 1.12
            kind = "aged"
        st.img = np.clip(st.img, 0, 1)
        el = {"type": "tape", "bbox": [round(v, 1) for v in poly_bbox(poly)], "poly": poly, "scored": False, "asset": a.name, "tape_kind": kind}
        st.items.append(el); st.elements.append(el)
        st.log.append({"op": "tape", "asset": a.name, "kind": kind, "vertical": vertical})


def op_stain_assets(st, rng, nrng, sev, lib):
    H, W = st.img.shape[:2]
    pool = [a for a in lib.get("stains_and_damage") if a.name.startswith("stain_")]
    if not pool: return
    for _ in range(rng.randint(1, 2 if sev < 1.2 else 3)):
        a = rng.choice(pool)
        if a.background == "white": im = crop_to_alpha(white_to_alpha(Image.open(a.path)), thr=30, trim=0.0)
        else: im = a.load()
        w = W * rng.uniform(0.18, 0.6)
        cx, cy = rng.uniform(0.1, 0.9) * W, rng.uniform(0.1, 0.9) * H
        poly = place(st.img, im, cx, cy, width=w, angle=rng.uniform(0, 360), opacity=rng.uniform(0.45, 0.9) * min(1.0, 0.6 + 0.4 * sev), flip=rng.random() < 0.5)
        el = {"type": "stain_asset", "bbox": [round(v, 1) for v in poly_bbox(poly)], "poly": poly, "scored": False, "asset": a.name}
        st.items.append(el); st.elements.append(el)
        st.log.append({"op": "stain_asset", "asset": a.name})
