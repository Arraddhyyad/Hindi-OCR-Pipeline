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


# ================================================================== stage 8: scan of a scan  /  stage 9: low resolution
SCAN_VARIANTS = {"photocopy": 0.28, "fax": 0.14, "halftone": 0.18, "flatbed_rescan": 0.22, "phone_photo": 0.18}


def _grey(st):
    g = st.img.mean(axis=2, keepdims=True)
    st.img = np.repeat(g, 3, axis=2).astype(np.float32)


def _levels(a, lo, hi):
    return np.clip((a - lo) / max(1e-3, hi - lo), 0, 1)


def _scan_photocopy(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; _grey(st)
    st.img = _levels(st.img, rng.uniform(0.12, 0.3), rng.uniform(0.7, 0.88)) ** rng.uniform(0.9, 1.4)      # harder contrast, paper goes white
    n = nrng.random((H, W)) < rng.uniform(0.0004, 0.002) * sev                                              # toner speckle
    st.img[cv2.dilate(n.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0] *= 0.15
    for _ in range(rng.randint(1, 3)):                                                                        # lamp streaks: faint vertical lines
        x = rng.randrange(W); wd = rng.randint(1, 3); st.img[:, x:x + wd] *= rng.uniform(0.80, 0.95) if rng.random() < 0.6 else 1.0
    band = rng.randint(8, 34)                                                                                 # dark copier edge on one or two sides
    for side in rng.sample(["l", "r", "t", "b"], rng.randint(1, 2)):
        ramp = np.clip(1 - np.arange(band * 2) / (band * 2), 0, 1) ** 1.5 * rng.uniform(0.5, 0.95)
        if side == "l": st.img[:, :band * 2] *= (1 - ramp)[None, :, None]
        if side == "r": st.img[:, -band * 2:] *= (1 - ramp[::-1])[None, :, None]
        if side == "t": st.img[:band * 2] *= (1 - ramp)[:, None, None]
        if side == "b": st.img[-band * 2:] *= (1 - ramp[::-1])[:, None, None]


def _scan_fax(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; _grey(st)
    small = cv2.resize(st.img[..., 0], (W, max(8, int(H * rng.uniform(0.62, 0.85)))), interpolation=cv2.INTER_AREA)    # fax has about half the vertical resolution
    g = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    local = cv2.GaussianBlur(g, (0, 0), 25)
    bw = (g < local * rng.uniform(0.90, 0.97)).astype(np.float32)                                         # 1-bit: ink where darker than the local paper level
    out = 1 - bw
    for _ in range(rng.randint(2, 7)):                                                                        # scan-line dropouts
        y = rng.randrange(H); out[y:y + rng.randint(1, 2)] = rng.choice([0.0, 1.0]) if rng.random() < 0.3 else out[y:y + 1]
    st.img = np.repeat(out[..., None], 3, axis=2).astype(np.float32)


def _scan_halftone(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; _grey(st); g = st.img[..., 0]
    pitch = rng.uniform(3.2, 5.5); th = math.radians(rng.choice([15, 45, 75]))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = (xx * math.cos(th) + yy * math.sin(th)) * 2 * math.pi / pitch; v = (-xx * math.sin(th) + yy * math.cos(th)) * 2 * math.pi / pitch
    screen = 0.5 + 0.25 * (np.cos(u) + np.cos(v))
    ht = 1 / (1 + np.exp(-(g - screen) * 14))                                                              # soft threshold: dots grow with darkness
    out = cv2.GaussianBlur(ht.astype(np.float32), (0, 0), 0.7)
    f = rng.uniform(0.62, 0.8); small = cv2.resize(out, (int(W * f), int(H * f)), interpolation=cv2.INTER_LINEAR)       # the rescan beats against the dots: moire
    out = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    st.img = np.repeat(out[..., None], 3, axis=2).astype(np.float32)


def _scan_flatbed(st, rng, nrng, sev):
    from .step5_degrade import op_rotate
    H, W = st.img.shape[:2]
    st.img = np.clip(st.img * np.array([rng.uniform(0.96, 1.02), rng.uniform(0.96, 1.02), rng.uniform(0.9, 1.0)], np.float32), 0, 1)   # colour cast
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]; side = rng.choice([0, 1])                          # lid not fully closed: brightness falls off toward one side
    st.img *= 1 - (x if side else 1 - x) ** 2.2 * rng.uniform(0.15, 0.4)
    st.img = cv2.GaussianBlur(st.img, (0, 0), rng.uniform(0.5, 0.9)); op_rotate(st, rng, nrng, 0.6 + 0.4 * sev); st.log.pop()
    st.img = np.clip(st.img + nrng.standard_normal(st.img.shape).astype(np.float32) * 0.008, 0, 1)


def op_scan_of_scan(st, rng, nrng, sev, variant=None):
    """A page that has already been scanned is copied, faxed, screen-printed or photographed again, then scanned once more."""
    variant = variant or rng.choices(list(SCAN_VARIANTS), weights=list(SCAN_VARIANTS.values()))[0]
    if variant == "phone_photo":
        from . import hard_effects; hard_effects.phone_photo(st, rng, nrng, sev)
    elif variant == "photocopy": _scan_photocopy(st, rng, nrng, sev)
    elif variant == "fax": _scan_fax(st, rng, nrng, sev)
    elif variant == "halftone": _scan_halftone(st, rng, nrng, sev)
    else: _scan_flatbed(st, rng, nrng, sev)
    st.log.append({"op": "scan_of_scan", "variant": variant})
    return variant


def op_low_dpi(st, rng, nrng, sev, dpi=None):
    """Low resolution scan. The page canvas is about 150 dpi (A4 = 1240 px wide). The image really shrinks, and polygons and the clean target shrink with it."""
    dpi = dpi or rng.choices([72, 100, 120], weights=[0.35, 0.4, 0.25])[0]
    H, W = st.img.shape[:2]; f = dpi / 150.0
    nw, nh = max(64, int(round(W * f))), max(64, int(round(H * f)))
    st.img = cv2.resize(st.img, (nw, nh), interpolation=cv2.INTER_AREA)
    if st.clean is not None: st.clean = cv2.resize(st.clean, (nw, nh), interpolation=cv2.INTER_AREA)
    sx, sy = nw / W, nh / H
    st.map_points(lambda p: p * np.array([sx, sy], np.float32))
    st.log.append({"op": "low_dpi", "dpi": dpi, "size": [nw, nh]})
    return dpi
