"""STEP 5 - degradation (always last): stains, blots, folds, torn edge, scan/camera effects. Geometry ops move all stored polygons with the pixels.
"""
import io, math, random
import cv2
import numpy as np
from PIL import Image, ImageDraw
from .assets import white_to_alpha, crop_to_alpha, tint
from .imaging import place, poly_bbox, rect_polygon

SEV = {"light": 0.6, "medium": 1.0, "heavy": 1.5}
INKS = {"black": (20, 20, 28), "blueblack": (26, 26, 94), "blue": (23, 51, 143)}
OCCLUDERS = ("stamp", "stamp_text", "ink_blot", "signature", "thumbprint", "overlap_text", "mark_", "margin_note", "stain", "finger")


class State:
    def __init__(self, img, clean, items):
        self.img, self.clean, self.items, self.log = img, clean, items, []
        self.scan_bg = (0.05, 0.05, 0.05)
        self.elements = []            # new elements created by this stage (blots, stains)

    @property
    def size(self):
        return self.img.shape[1], self.img.shape[0]

    def map_points(self, fn):
        for it in self.items:
            p = np.asarray(it["poly"], np.float32).reshape(-1, 2)
            it["poly"] = np.round(fn(p), 1).tolist()
            it["bbox"] = [round(v, 1) for v in poly_bbox(it["poly"])]


# ------------------------------------------------------------------ helpers
def _rect(b):
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]


def _noise_field(rng_np, H, W, scale):
    h, w = max(2, int(H / scale)), max(2, int(W / scale))
    return cv2.resize(rng_np.standard_normal((h, w)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)


def _add_element(st, type_, poly, **kw):
    el = {"type": type_, "bbox": [round(v, 1) for v in poly_bbox(poly)], "poly": poly, "scored": False, **kw}
    st.items.append(el); st.elements.append(el)


# ------------------------------------------------------------------ paper / ink damage
def op_stain(st, rng, nrng, sev):
    H, W = st.img.shape[:2]
    for _ in range(rng.randint(1, 2 if sev < 1.2 else 3)):
        if rng.random() < 0.5:                                    # soft irregular stain
            f = _noise_field(nrng, H, W, rng.uniform(80, 160)); f = (f - f.mean()) / (f.std() + 1e-6)
            m = np.clip((f - rng.uniform(0.9, 1.5)) * 0.8, 0, 1); m = cv2.GaussianBlur(m, (0, 0), 6)
            tone = np.array([0.80, 0.68, 0.50], np.float32); amt = rng.uniform(0.18, 0.32) * sev
        else:                                                      # coffee ring
            cx, cy, r = rng.uniform(0.15, 0.85) * W, rng.uniform(0.15, 0.85) * H, rng.uniform(50, 130)
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) + 18 * _noise_field(nrng, H, W, 30)
            m = np.exp(-((d - r) / 5.0) ** 2) * 0.9 + (d < r) * 0.15; m = np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.5), 0, 1)
            tone = np.array([0.72, 0.55, 0.36], np.float32); amt = rng.uniform(0.25, 0.45) * sev
        st.img *= 1 - m[..., None] * amt * (1 - tone)
    st.log.append({"op": "stain"})


def _blot_assets(lib):
    out = []
    for a in lib.get("blots"):
        out.append(a.load())
    return out


def op_blots(st, rng, nrng, sev, lib):
    H, W = st.img.shape[:2]
    words = [it for it in st.items if it.get("kind") == "body"]
    n = rng.randint(3, 8) if sev < 1.2 else rng.randint(6, 16)
    assets = _blot_assets(lib); made = 0
    for i in range(n):
        col = rng.choice(["black", "blueblack", "blue"]); k = INKS[col]
        if words and rng.random() < 0.55:
            b = rng.choice(words)["bbox"]; cx, cy = rng.uniform(b[0], b[2]), rng.uniform(b[1], b[3])
        else:
            cx, cy = rng.uniform(0.05, 0.95) * W, rng.uniform(0.05, 0.95) * H
        if assets and rng.random() < 0.35:
            im = tint(rng.choice(assets), k); wpx = rng.uniform(14, 80 if sev < 1.2 else 130)
            poly = place(st.img, im, cx, cy, width=wpx, angle=rng.uniform(0, 360), opacity=rng.uniform(0.55, 0.95), flip=rng.random() < .5)
        else:                                                      # small drop with short tail
            r = rng.uniform(1.4, 5.5 * sev); ss = 4; sz = int(r * 2 * ss + 24 * ss)
            im = Image.new("L", (sz, sz), 0); d = ImageDraw.Draw(im)
            c = sz / 2; d.ellipse([c - r * ss, c - r * ss, c + r * ss, c + r * ss], fill=255)
            if rng.random() < 0.4:
                tx, ty = c + rng.uniform(-10, 10) * ss, c + rng.uniform(-10, 10) * ss; d.line([(c, c), (tx, ty)], fill=200, width=max(1, int(ss * r * 0.35)))
            a = np.asarray(im.resize((sz // ss, sz // ss), Image.LANCZOS))
            rgba = np.dstack([np.full(a.shape + (3,), k, np.uint8), a]); im = Image.fromarray(rgba, "RGBA")
            poly = place(st.img, im, cx, cy, width=im.width, opacity=rng.uniform(0.5, 0.9))
        _add_element(st, "ink_blot", poly, colour=col); made += 1
    st.log.append({"op": "ink_blots", "n": made})


_crease_cache = {}


def _crease_profile(lib, vertical: bool):
    key = vertical
    if key in _crease_cache:
        return _crease_cache[key]
    prof = None
    items = lib.get("creases")
    if items:
        g = np.asarray(items[0].load().convert("L")).astype(np.float32) / 255.0
        if vertical: g = g.T                                    # crease at x~512 becomes a row
        # the horizontal crease sits near row 255 in the supplied photo; locate it from the strongest ridge
        rows = np.abs(cv2.Laplacian(cv2.GaussianBlur(g, (0, 0), 1.0), cv2.CV_32F)).mean(axis=1)
        y = int(np.argmax(rows[:int(g.shape[0] * 0.7)]))
        band = g[max(0, y - 45):y + 45]
        ref = np.median(np.concatenate([g[:max(1, y - 120)].ravel(), g[y + 120:].ravel()])) if y > 130 else np.median(g)
        prof = np.clip(band / (ref + 1e-6), 0.5, 1.6)
    _crease_cache[key] = prof
    return prof


def op_folds(st, rng, nrng, sev, lib):
    H, W = st.img.shape[:2]
    pattern = rng.choices(["h2", "h1", "cross", "v1", "h2v"], [.3, .15, .25, .1, .2])[0]
    folds = []
    if pattern in ("h2", "h2v"): folds += [("h", H * (1 / 3 + rng.uniform(-.03, .03))), ("h", H * (2 / 3 + rng.uniform(-.03, .03)))]
    if pattern == "h1": folds += [("h", H * rng.uniform(.4, .6))]
    if pattern in ("cross",): folds += [("h", H * rng.uniform(.4, .6)), ("v", W * rng.uniform(.42, .58))]
    if pattern in ("v1", "h2v"): folds += [("v", W * rng.uniform(.42, .58))]
    for kind, pos in folds:
        vert = kind == "v"; L = H if vert else W; T = W if vert else H
        pos = int(pos); half = 30
        # broad soft shading plus the fine ridge detail from the supplied crease photo
        coord = np.arange(T, dtype=np.float32); shade = np.clip(1 - np.abs(coord - pos) / (22 * sev + 8), 0, 1) ** 1.6
        line = 1 - (0.10 + 0.10 * sev) * shade
        prof = _crease_profile(lib, vert)
        if prof is not None:
            ph = prof.shape[0]; strip = cv2.resize(prof, (L, ph), interpolation=cv2.INTER_LINEAR)
            strip = 1 + (strip - 1) * rng.uniform(1.2, 2.2) * sev
            amap = np.ones((T, L), np.float32); y0 = max(0, pos - ph // 2); y1 = min(T, y0 + ph)
            amap[y0:y1] = strip[:y1 - y0]
            m2 = amap if not vert else amap
            fold_map = (line[:, None] * m2)
        else:
            fold_map = np.repeat(line[:, None], L, axis=1)
        fold_map = fold_map.T if vert else fold_map             # -> H x W
        fold_map = np.clip(fold_map, 0.45, 1.25)
        # one side of the fold catches slightly more light
        side = (np.arange(T)[:, None] > pos).astype(np.float32) * rng.uniform(-0.03, 0.03)
        side = side.T if vert else side
        st.img *= (fold_map + (side if side.shape == fold_map.shape else 0))[..., None] if side.shape == fold_map.shape else fold_map[..., None]
        wear = fold_map < 0.97
    st.fold_lines = folds                                       # kept so later damage (cracked ink on hard pages) can follow the real folds
    st.log.append({"op": "folds", "pattern": pattern, "n": len(folds)})


_torn_cache = {}


def _tear_profile(lib, rng, nrng, length):
    """1-D tear contour (depth lost, in px) per position along the edge. From the torn-edge photo when available."""
    items = lib.get("torn_edges")
    if items:
        a = rng.choice(items)
        if a.name not in _torn_cache:
            rgb = np.asarray(a.load()).astype(np.float32) / 255.0
            mask = (rgb.mean(axis=2) > 0.12).astype(np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            last = np.array([np.max(np.where(r)[0]) if r.any() else 0 for r in mask], np.float32)
            last = cv2.medianBlur(last.reshape(-1, 1), 5).ravel() if False else np.convolve(np.pad(last, 2, mode="edge"), np.ones(5) / 5, "valid")
            _torn_cache[a.name] = last - last.min()
        prof = _torn_cache[a.name]
        s = rng.uniform(0.25, 0.55); n = max(8, int(len(prof) * s))
        p1 = cv2.resize(prof.reshape(-1, 1), (1, n)).ravel() * s
        reps = int(math.ceil(length / n)) + 1
        full = np.concatenate([p1[::-1] if k % 2 else p1 for k in range(reps)])
        off = rng.randint(0, n - 1); prof = full[off:off + length]
    else:
        prof = np.cumsum(nrng.integers(-3, 4, length)).astype(np.float32); prof -= prof.min()
        prof = np.clip(prof, 0, 60)
    fine = cv2.GaussianBlur(nrng.standard_normal(length).astype(np.float32).reshape(-1, 1), (0, 0), 1.2).ravel() * 3
    return np.maximum(prof + fine, 0)


def _void_bg(st, rng, nrng, lib, M):
    H, W = M.shape
    kind = rng.choices(["dark", "light", "paper"], [.45, .25, .30])[0]
    if kind == "paper" and lib.get("paper"):
        im = rng.choice(lib.get("paper")).load().resize((W, H), Image.LANCZOS)
        bg = np.asarray(im).astype(np.float32) / 255.0 * rng.uniform(0.62, 0.85)
    else:
        v = rng.uniform(0.04, 0.2) if kind != "light" else rng.uniform(0.86, 0.97)
        bg = np.ones((H, W, 3), np.float32) * np.array([v, v * rng.uniform(.96, 1.0), v * rng.uniform(.92, 1.0)], np.float32)
    sh = cv2.GaussianBlur(M, (0, 0), rng.uniform(8, 16))
    bg *= (1 - 0.45 * np.clip(sh, 0, 1) * (1 - M))[..., None]       # contact shadow next to the paper
    return bg, kind


def op_tear(st, rng, nrng, sev, lib):
    H, W = st.img.shape[:2]
    all_sides = ("left", "right", "top", "bottom")
    sides = [rng.choice(all_sides)]
    if rng.random() < 0.25 * sev: sides.append(rng.choice([s for s in all_sides if s != sides[0]]))
    M = np.ones((H, W), np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for side in sides:
        horizontal = side in ("top", "bottom")
        length, depth_total = (W, H) if horizontal else (H, W)
        prof = _tear_profile(lib, rng, nrng, length)
        base = rng.uniform(0.004, 0.012 * sev + 0.008) * depth_total          # how far in the tear sits
        cut = base + prof                                                      # lost depth along the edge
        if side == "right":    M *= (xx < (W - cut[:, None])).astype(np.float32)
        elif side == "left":   M *= (xx >= cut[:, None]).astype(np.float32)
        elif side == "bottom": M *= (yy < (H - cut[None, :])).astype(np.float32)
        else:                  M *= (yy >= cut[None, :]).astype(np.float32)
    used = sides
    dist = cv2.distanceTransform(M.astype(np.uint8), cv2.DIST_L2, 3)
    rim = np.clip(1 - dist / 6.0, 0, 1) * M * (0.6 + 0.4 * np.clip(_noise_field(nrng, H, W, 3), -1, 1) )   # pale fibrous rim
    paper_light = np.clip(st.img * 0.35 + 0.72, 0, 1)
    st.img = st.img * (1 - 0.7 * rim[..., None]) + paper_light * 0.7 * rim[..., None]
    bg, kind = _void_bg(st, rng, nrng, lib, M)
    Ms = cv2.GaussianBlur(M, (0, 0), 0.8)[..., None]
    st.img = st.img * Ms + bg * (1 - Ms)
    for it in st.items:
        b = it["bbox"]; x0, y0, x1, y1 = [int(max(0, v)) for v in (b[0], b[1], b[2], b[3])]
        sub = M[y0:max(y0 + 1, min(H, y1)), x0:max(x0 + 1, min(W, x1))]
        it["torn_visible"] = round(float(sub.mean()), 2) if sub.size else 0.0
    st.log.append({"op": "torn_edge", "sides": used, "background": kind, "paper_lost_pct": round(100 * (1 - float(M.mean())), 1)})


# ------------------------------------------------------------------ ink / scan photometric
def op_ink_thickness(st, rng, nrng, sev):
    k = np.ones((2, 2), np.uint8); mode = rng.choice(["erode", "dilate"])
    f = cv2.erode if mode == "erode" else cv2.dilate
    st.img = f(st.img, k, iterations=1)
    st.log.append({"op": "ink_" + mode})


def _aug(st, name, seed=0, **kw):
    """Augraphy op on pixels only. Seeds the global RNGs (Augraphy uses them) so pages stay reproducible; fails soft."""
    import augraphy
    cls = getattr(augraphy, name)
    bgr = cv2.cvtColor((np.clip(st.img, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    state = (random.getstate(), np.random.get_state()); random.seed(seed); np.random.seed(seed % (2**32))
    try:
        out = cls(p=1.0, **kw)(bgr)
        out = out[0] if isinstance(out, tuple) else out
        if isinstance(out, dict): out = out["output"]
        if out.shape[:2] != bgr.shape[:2]: raise ValueError("augraphy changed the image size")
        st.img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        st.log.append({"op": "augraphy." + name})
    except Exception as e:
        st.log.append({"op": "augraphy." + name + ".FAILED", "error": repr(e)[:80]})
    finally:
        random.setstate(state[0]); np.random.set_state(state[1])


def op_lighting(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; a = rng.uniform(0, 2 * math.pi)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = ((xx / W - .5) * math.cos(a) + (yy / H - .5) * math.sin(a))
    st.img *= (1 + g * rng.uniform(0.12, 0.3) * sev)[..., None]
    if rng.random() < 0.5:
        r = np.sqrt(((xx / W - .5) ** 2 + (yy / H - .5) ** 2)); st.img *= (1 - r ** 2 * rng.uniform(.3, .9) * sev)[..., None]
    st.log.append({"op": "lighting_gradient"})


def op_shadow(st, rng, nrng, sev):
    H, W = st.img.shape[:2]
    pts = np.array([[rng.uniform(0, W), 0], [rng.uniform(0, W), 0], [rng.uniform(0, W), H], [rng.uniform(0, W), H]], np.int32)
    m = np.zeros((H, W), np.float32); cv2.fillPoly(m, [pts], 1.0); m = cv2.GaussianBlur(m, (0, 0), rng.uniform(40, 110))
    st.img *= (1 - m * rng.uniform(0.08, 0.25) * sev)[..., None]
    st.log.append({"op": "shadow_band"})


def op_blur(st, rng, nrng, sev):
    s = rng.uniform(0.5, 1.1) * sev; st.img = cv2.GaussianBlur(st.img, (0, 0), s); st.log.append({"op": "blur", "sigma": round(s, 2)})


def op_noise(st, rng, nrng, sev):
    s = rng.uniform(0.012, 0.03) * sev
    n = nrng.normal(0, s, st.img.shape[:2]).astype(np.float32)[..., None] + nrng.normal(0, s * 0.4, st.img.shape).astype(np.float32)
    st.img = np.clip(st.img + n, 0, 1); st.log.append({"op": "noise", "sigma": round(s, 3)})


def op_resample(st, rng, nrng, sev):
    f = max(0.45, 1 - rng.uniform(0.1, 0.35) * sev); H, W = st.img.shape[:2]
    small = cv2.resize(st.img, (int(W * f), int(H * f)), interpolation=cv2.INTER_AREA)
    st.img = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR); st.log.append({"op": "resample", "factor": round(f, 2)})


def op_contrast(st, rng, nrng, sev):
    c, b = 1 - rng.uniform(0.08, 0.28) * sev, rng.uniform(0.0, 0.1) * sev
    st.img = np.clip((st.img - 0.5) * c + 0.5 + b, 0, 1); st.log.append({"op": "low_contrast", "c": round(c, 2)})


def op_specks(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; n = int(rng.uniform(80, 260) * sev)
    m = np.zeros((H, W), np.float32)
    for _ in range(n): cv2.circle(m, (rng.randrange(W), rng.randrange(H)), rng.choice([0, 0, 1, 1, 2]), rng.uniform(.3, 1), -1)
    st.img *= (1 - 0.6 * cv2.GaussianBlur(m, (0, 0), 0.7))[..., None]; st.log.append({"op": "dust_specks", "n": n})


def op_jpeg(st, rng, nrng, sev):
    q = int(np.clip(rng.uniform(55, 88) - 18 * (sev - 0.6), 25, 90))
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor((np.clip(st.img, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
    st.img = cv2.cvtColor(cv2.imdecode(buf, 1), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0; st.log.append({"op": "jpeg", "quality": q})
    return q


# ------------------------------------------------------------------ geometric scan ops (move pixels AND polygons)
def _warp_both(st, fn_img, fn_pts):
    st.img = fn_img(st.img, st.scan_bg)
    if st.clean is not None: st.clean = fn_img(st.clean, (0.96, 0.96, 0.96))
    st.map_points(fn_pts)


def op_rotate(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; ang = rng.uniform(-1, 1) * rng.uniform(0.8, 2.2) * sev * (1.7 if sev > 1.2 else 1.0)
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0); c, s = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(H * s + W * c), int(H * c + W * s); M[0, 2] += nw / 2 - W / 2; M[1, 2] += nh / 2 - H / 2
    warp = lambda im, bg: cv2.warpAffine(im, M, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in bg))
    _warp_both(st, warp, lambda p: p @ M[:, :2].T + M[:, 2]); st.log.append({"op": "rotate", "deg": round(ang, 2)})


def op_perspective(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; a = rng.uniform(0.006, 0.025) * sev
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = src + np.float32([[rng.uniform(-a, a) * W, rng.uniform(-a, a) * H] for _ in range(4)])
    Hm = cv2.getPerspectiveTransform(src, dst)
    warp = lambda im, bg: cv2.warpPerspective(im, Hm, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in bg))
    _warp_both(st, warp, lambda p: cv2.perspectiveTransform(p.reshape(-1, 1, 2).astype(np.float32), Hm).reshape(-1, 2))
    st.log.append({"op": "perspective", "amount": round(a, 4)})


def op_bend(st, rng, nrng, sev):
    H, W = st.img.shape[:2]; A = rng.uniform(2.5, 9) * sev; lam = rng.uniform(0.9, 2.6) * H; ph = rng.uniform(0, 2 * math.pi)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32); mapx = xx - A * np.sin(2 * math.pi * yy / lam + ph); mapy = yy
    warp = lambda im, bg: cv2.remap(im, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in bg))
    _warp_both(st, warp, lambda p: np.stack([p[:, 0] + A * np.sin(2 * math.pi * p[:, 1] / lam + ph), p[:, 1]], 1))
    st.log.append({"op": "page_bend", "amp_px": round(A, 1)})


# ------------------------------------------------------------------ plan and run
P = {  # probability per severity (light, medium, heavy)
    "stain": (.25, .4, .6), "blots": (.7, .9, 1.0), "ink_thickness": (.25, .35, .4), "ink_mottling": (.2, .3, .4), "low_ink_lines": (.1, .2, .35),
    "bleed_through": (.1, .2, .35), "bad_photocopy": (0, .08, .2), "lighting": (.5, .65, .8), "shadow": (.2, .3, .45), "specks": (.4, .6, .8),
    "perspective": (.3, .45, .6), "bend": (.25, .4, .55), "contrast": (.2, .3, .45), "subtle_noise": (.3, .4, .5),
}


def degrade_page(composed: Image.Image, rec: dict, lib, cfg: dict, rng: random.Random, paired: bool = True):
    dcfg = cfg.get("degrade", {})
    weights = dcfg.get("severity", {"light": 0.3, "medium": 0.45, "heavy": 0.25})
    sev_name = rng.choices(list(weights), weights=list(weights.values()))[0]; sev = SEV[sev_name]; si = list(SEV).index(sev_name)
    nrng = np.random.default_rng(rng.randrange(2**31))
    img = np.asarray(composed.convert("RGB")).astype(np.float32) / 255.0
    items = []
    for key in ("words_all", "elements", "lines"):
        for it in rec.get(key, []):
            it.setdefault("poly", _rect(it["bbox"])); items.append(it)
    st = State(img, img.copy() if paired else None, items)
    v = rng.choice([0.04, 0.96, 0.5]); st.scan_bg = (v, v, v)
    use_aug = dcfg.get("use_augraphy", True)
    has = lambda k: rng.random() < P[k][si]

    # --- paper and ink damage (before the page is scanned)
    if has("ink_thickness"): op_ink_thickness(st, rng, nrng, sev)
    if use_aug and has("ink_mottling"): _aug(st, "InkMottling", seed=rng.randrange(2**31))
    if use_aug and has("low_ink_lines"): _aug(st, "LowInkRandomLines", seed=rng.randrange(2**31))
    if has("stain"): op_stain(st, rng, nrng, sev)
    if has("blots"): op_blots(st, rng, nrng, sev, lib)
    op_folds(st, rng, nrng, sev, lib)                      # always
    if use_aug and has("bleed_through"): _aug(st, "BleedThrough", seed=rng.randrange(2**31))
    op_tear(st, rng, nrng, sev, lib)                       # always
    # --- scanning / photographing
    op_rotate(st, rng, nrng, sev)
    if has("perspective"): op_perspective(st, rng, nrng, sev)
    if has("bend"): op_bend(st, rng, nrng, sev)
    if has("lighting"): op_lighting(st, rng, nrng, sev)
    if has("shadow"): op_shadow(st, rng, nrng, sev)
    if has("specks"): op_specks(st, rng, nrng, sev)
    if has("contrast"): op_contrast(st, rng, nrng, sev)
    if use_aug and has("bad_photocopy"): _aug(st, "BadPhotoCopy", seed=rng.randrange(2**31))
    if rng.random() < 0.6: op_resample(st, rng, nrng, sev)
    if rng.random() < 0.7: op_blur(st, rng, nrng, sev)
    op_noise(st, rng, nrng, sev)
    if use_aug and has("subtle_noise"): _aug(st, "SubtleNoise", seed=rng.randrange(2**31))
    q = op_jpeg(st, rng, nrng, sev)

    # --- bookkeeping: visibility and occlusion
    W, H = st.size
    for it in st.items:
        b = it["bbox"]; area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        iw = max(0, min(b[2], W) - max(b[0], 0)); ih = max(0, min(b[3], H) - max(b[1], 0))
        it["visible"] = round(min(1.0, iw * ih / area) * it.get("torn_visible", 1.0), 2)
    occ = [e for e in st.items if str(e.get("type", "")).startswith(OCCLUDERS)]
    for it in st.items:
        if it.get("kind") in ("body", "title", "sig_label", "header_text", "footer_text", "correction") and it.get("scored"):
            b = it["bbox"]; area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1])); mx = 0.0
            for e in occ:
                e_b = e["bbox"]; ix = max(0, min(b[2], e_b[2]) - max(b[0], e_b[0])); iy = max(0, min(b[3], e_b[3]) - max(b[1], e_b[1]))
                mx = max(mx, ix * iy / area)
            it["occluded"] = round(min(1.0, mx), 2)
    out = Image.fromarray((np.clip(st.img, 0, 1) * 255).astype(np.uint8))
    target = Image.fromarray((np.clip(st.clean, 0, 1) * 255).astype(np.uint8)) if st.clean is not None else None
    meta = {"severity": sev_name, "ops": st.log, "final_size": [W, H], "jpeg_quality": q, "scan_background": round(st.scan_bg[0], 2)}
    return out, target, st.items, st.elements, meta


# ================================================================== staged degradation (v2, optional; the functions above are untouched)
# One recipe per page (which damages exist and their random details are drawn once from per-op random streams that do not depend on the
# stage). Stage k then switches on the damages whose group is <= k and scales their strength. So stage k+1 contains everything of stage k.
STAGE_SEV = {1: 0.45, 2: 0.7, 3: 1.0, 4: 1.3, 5: 1.7}          # strength passed to the ops (compare the old SEV: light 0.6, medium 1.0, heavy 1.5)
STAGE_NAMES = {1: "scan wear", 2: "paper ageing", 3: "ink damage", 4: "geometry and physical", 5: "severe"}
STAGE_SEVERITY = {1: "light", 2: "light", 3: "medium", 4: "heavy", 5: "heavy"}   # keeps the old severity field meaningful in staged mode
# op -> (group, probability that it is present at stage 5). Always-on ops have probability 1. A damage with group g first can appear at stage g
# and its chance climbs linearly to the stage-5 value, so presence is monotonic in the stage (one uniform draw per op, compared to the ramp).
GROUP = {"ink_thickness": (2, .4), "ink_mottling": (3, .4), "low_ink_lines": (3, .35), "stain": (2, .6), "blots": (3, 1.0), "folds": (1, 1.0),
         "bleed_through": (3, .35), "tear": (1, 1.0), "rotate": (1, 1.0), "perspective": (4, .6), "bend": (4, .55), "lighting": (1, .8),
         "shadow": (2, .45), "specks": (1, .8), "contrast": (1, .45), "bad_photocopy": (3, .2), "resample": (1, .6), "blur": (1, .7),
         "noise": (1, 1.0), "subtle_noise": (1, .5), "jpeg": (1, 1.0)}


def _present(u, op, k):
    g, p5 = GROUP[op]
    if k < g: return False
    return u < p5 * (k - g + 1) / (6 - g)


def measure(final_rgb: np.ndarray, target_rgb, items) -> dict:
    """Numbers that describe how hard the page is to read, taken from the pixels of the body text (not from the recipe):
    text_contrast (97th percentile ink depth inside the body-word polygons), contrast_ratio and sharpness_ratio versus the clean aligned target,
    occluded_frac (share of body words that are covered or cut off)."""
    def stats(img):
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY); paper = cv2.medianBlur(g, 31); diff = paper.astype(np.int16) - g.astype(np.int16)
        m = np.zeros(g.shape, np.uint8)
        for w in items:
            if w.get("kind") == "body" and w.get("scored"): cv2.fillPoly(m, [np.round(np.asarray(w["poly"])).astype(np.int32)], 1)
        sel = m > 0
        if sel.sum() < 100: return None
        lap = cv2.Laplacian(g, cv2.CV_32F)
        return float(np.percentile(diff[sel], 97)), float(lap[sel].var())
    body = [w for w in items if w.get("kind") == "body" and w.get("scored")]
    out = {"occluded_frac": round(sum(1 for w in body if w.get("occluded", 0) > 0.05 or w.get("visible", 1) < 0.99) / max(1, len(body)), 3)}
    a = stats(final_rgb)
    if a: out["text_contrast"] = round(a[0], 1)
    if a and target_rgb is not None:
        b = stats(target_rgb)
        if b and b[0] > 0 and b[1] > 0: out["contrast_ratio"] = round(a[0] / b[0], 3); out["sharpness_ratio"] = round(a[1] / b[1], 3)
    return out


def degrade_page_staged(composed: Image.Image, rec: dict, lib, cfg: dict, key: str, stage: int, paired: bool = True):
    """Same return shape as degrade_page. `key` identifies the page (its seed) so every op has its own private random stream."""
    dcfg = cfg.get("degrade", {}); sev = STAGE_SEV[stage]
    R = lambda name: random.Random(f"{key}|{name}")
    N = lambda name: np.random.default_rng(R(name + "|np").randrange(2**31))
    img = np.asarray(composed.convert("RGB")).astype(np.float32) / 255.0
    items = []
    for k_ in ("words_all", "elements", "lines"):
        for it in rec.get(k_, []):
            it.setdefault("poly", _rect(it["bbox"])); items.append(it)
    st = State(img, img.copy() if paired else None, items)
    v = R("scan_bg").choice([0.04, 0.96, 0.5]); st.scan_bg = (v, v, v)
    use_aug = dcfg.get("use_augraphy", True)
    hd = dcfg.get("hard") if ((rec.get("page") or {}).get("ext") or {}).get("hard") else None    # v2 hard pages only (config degrade.hard); None otherwise
    def on(op):
        u = R(op + "|on").random()
        if hd and op in (hd.get("p5") or {}):                       # hard pages: own stage-5 chance for some ops (same ramp over the stages)
            g = GROUP[op][0]; return stage >= g and u < hd["p5"][op] * (stage - g + 1) / (6 - g)
        return _present(u, op, stage)
    gsev = sev * hd.get("soft_scale", 1.0) if hd else sev           # blur and resolution loss are gentler on small-type hard pages, so the text stays recoverable
    seed_of = lambda op: R(op + "|seed").randrange(2**31)

    if on("ink_thickness"): op_ink_thickness(st, R("ink_thickness"), N("ink_thickness"), sev)
    if use_aug and on("ink_mottling"): _aug(st, "InkMottling", seed=seed_of("ink_mottling"))
    if use_aug and on("low_ink_lines"): _aug(st, "LowInkRandomLines", seed=seed_of("low_ink_lines"))
    if on("stain"): op_stain(st, R("stain"), N("stain"), sev)
    if on("blots"): op_blots(st, R("blots"), N("blots"), sev, lib)
    if hd:
        from . import hard_effects
        hard_effects.ink_fade(st, R("hard_fade"), N("hard_fade"), sev); hard_effects.show_through(st, R("hard_st"), sev)
    op_folds(st, R("folds"), N("folds"), sev, lib)                       # always on, strength follows the stage
    if hd: hard_effects.cracked_ink(st, R("hard_crack"), sev)
    if use_aug and on("bleed_through"): _aug(st, "BleedThrough", seed=seed_of("bleed_through"))
    op_tear(st, R("tear"), N("tear"), sev, lib)                          # always on
    op_rotate(st, R("rotate"), N("rotate"), sev)
    if on("perspective"): op_perspective(st, R("perspective"), N("perspective"), sev)
    if on("bend"): op_bend(st, R("bend"), N("bend"), sev)
    if on("lighting"): op_lighting(st, R("lighting"), N("lighting"), sev)
    if on("shadow"): op_shadow(st, R("shadow"), N("shadow"), sev)
    if hd and (hd.get("photo") or {}).get("p", 0) > 0 and R("hard_photo|on").random() < hd["photo"]["p"]:      # hard pages, sometimes: shot with a phone
        hard_effects.phone_photo(st, R("hard_photo"), N("hard_photo"), sev)
    if on("specks"): op_specks(st, R("specks"), N("specks"), sev)
    if on("contrast"): op_contrast(st, R("contrast"), N("contrast"), sev)
    if hd: hard_effects.photocopy_look(st, R("hard_copy"), sev)
    if use_aug and on("bad_photocopy"): _aug(st, "BadPhotoCopy", seed=seed_of("bad_photocopy"))
    if on("resample"): op_resample(st, R("resample"), N("resample"), gsev)
    if on("blur"): op_blur(st, R("blur"), N("blur"), gsev)
    op_noise(st, R("noise"), N("noise"), sev)
    if use_aug and on("subtle_noise"): _aug(st, "SubtleNoise", seed=seed_of("subtle_noise"))
    q = op_jpeg(st, R("jpeg"), N("jpeg"), sev)

    W, H = st.size
    for it in st.items:
        b = it["bbox"]; area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        iw = max(0, min(b[2], W) - max(b[0], 0)); ih = max(0, min(b[3], H) - max(b[1], 0))
        it["visible"] = round(min(1.0, iw * ih / area) * it.get("torn_visible", 1.0), 2)
    occ = [e for e in st.items if str(e.get("type", "")).startswith(OCCLUDERS)]
    for it in st.items:
        if it.get("kind") in ("body", "title", "sig_label", "header_text", "footer_text", "correction") and it.get("scored"):
            b = it["bbox"]; area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1])); mx = 0.0
            for e in occ:
                e_b = e["bbox"]; ix = max(0, min(b[2], e_b[2]) - max(b[0], e_b[0])); iy = max(0, min(b[3], e_b[3]) - max(b[1], e_b[1]))
                mx = max(mx, ix * iy / area)
            it["occluded"] = round(min(1.0, mx), 2)
    out = Image.fromarray((np.clip(st.img, 0, 1) * 255).astype(np.uint8))
    target = Image.fromarray((np.clip(st.clean, 0, 1) * 255).astype(np.uint8)) if st.clean is not None else None
    meas = measure(np.asarray(out), np.asarray(target) if target is not None else None, st.items)
    meta = {"severity": STAGE_SEVERITY[stage], "stage": stage, "stage_name": STAGE_NAMES[stage], "ops": st.log, "final_size": [W, H],
            "jpeg_quality": q, "scan_background": round(st.scan_bg[0], 2), "measure": meas}
    gr = dcfg.get("guardrails")
    if gr:                      # measure and log only (limits are provisional until the calibration run); nothing is rejected here
        lim = {"min_text_contrast": lambda v: meas.get("text_contrast", 1e9) < v, "max_occluded_frac": lambda v: meas["occluded_frac"] > v,
               "min_sharpness_ratio": lambda v: meas.get("sharpness_ratio", 1e9) < v}
        meta["guardrail"] = {"provisional": bool(gr.get("provisional", True)), "enforced": bool(gr.get("enforce")),
                             "would_reject": [k for k, f in lim.items() if k in gr and f(gr[k])]}
    return out, target, st.items, st.elements, meta
