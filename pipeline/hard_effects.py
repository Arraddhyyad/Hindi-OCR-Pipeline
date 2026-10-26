"""Hard-page effects (v2 only, switched on by compose.hard in the config; nothing here is imported otherwise).

Stage 2, messier handwriting. Works on the clean text layer (dark ink on white) before it is multiplied onto the paper, so the ink mask is exact.
  pen pressure    each word lighter or darker, with a slow fade along the word
  word bend       each word bent a little by a smooth warp, so no two copies of a word look alike (shifts of 1-2 px, word boxes stay valid)
  smudge          wet ink dragged sideways on a few words
  strike-through  a wavy pen line over a few words (the word stays in the transcript, flagged `struck`)
All randomness comes from the Random / numpy generators built here from the page seed, so a page is reproducible.
"""
import math, random
import numpy as np, cv2
from PIL import Image, ImageDraw


def _smooth(h, w, sig, rng):
    n = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), sig)
    return n / (np.abs(n).max() + 1e-6)


def _box(b, pad, W, H):
    return max(0, int(b[0] - pad)), max(0, int(b[1] - pad)), min(W, int(b[2] + pad)), min(H, int(b[3] + pad))


def messy_text(clean, rec, rnd: random.Random, hc: dict, ink_rgb):
    """clean: float32 (H,W,3) in 0..1, white background. Returns (new clean array, struck word indices into rec['words'])."""
    H, W = clean.shape[:2]; rng = np.random.default_rng(rnd.randrange(2**31))
    idx = [i for i, w in enumerate(rec["words"]) if w.get("kind") == "body"]
    fs = rec["page"]["font_size"]; sc = min(1.0, fs / 30.0)          # effect sizes were tuned on ~30 px text
    out = clean.copy()
    # pen pressure
    for i in idx:
        x0, y0, x1, y1 = _box(rec["words"][i]["bbox"], 2, W, H)
        if x1 - x0 < 3 or y1 - y0 < 3: continue
        g = rnd.uniform(*hc["pressure"]); ramp = np.linspace(rnd.uniform(.8, 1.1), rnd.uniform(.7, 1.1), x1 - x0)[None, :, None]
        G = np.clip(g * ramp, 0.35, 1.15)
        reg = out[y0:y1, x0:x1]; out[y0:y1, x0:x1] = np.clip(1 - (1 - reg) * G, 0, 1)
    # word bend
    for i in idx:
        x0, y0, x1, y1 = _box(rec["words"][i]["bbox"], 4, W, H); h_, w_ = y1 - y0, x1 - x0
        if h_ < 8 or w_ < 8: continue
        dx = _smooth(h_, w_, 6, rng) * rnd.uniform(1.0, 2.6) * sc; dy = _smooth(h_, w_, 6, rng) * rnd.uniform(0.8, 2.2) * sc
        X, Y = np.meshgrid(np.arange(w_, dtype=np.float32), np.arange(h_, dtype=np.float32))
        out[y0:y1, x0:x1] = cv2.remap(out[y0:y1, x0:x1], X + dx, Y + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # smudges
    n_sm = max(3, int(len(idx) * hc["smudge"]))
    for i in rnd.sample(idx, min(n_sm, len(idx))):
        x0, y0, x1, y1 = _box(rec["words"][i]["bbox"], 3, W, H); x1 = min(W, x1 + int(rnd.uniform(14, 34) * sc))
        if x1 - x0 < 4: continue
        k = np.full((1, max(3, int(rnd.uniform(15, 31) * sc))), 1.0, np.float32); k /= k.shape[1]
        crop = out[y0:y1, x0:x1]; bl = cv2.filter2D(crop, -1, k)
        ramp = np.linspace(0.2, 1.0, x1 - x0)[None, :, None]
        out[y0:y1, x0:x1] = crop + (bl - crop) * 0.8 * ramp
    # second pen: one block of consecutive words written with a different pen (black or dark grey)
    if hc.get("second_pen"):
        n2 = int(len(idx) * hc["second_pen"]); st0 = rnd.randrange(0, max(1, len(idx) - n2)); col = np.asarray(rnd.choice([(20, 20, 28), (70, 70, 80), (35, 35, 40)]), np.float32) / 255.0
        for i in idx[st0:st0 + n2]:
            x0, y0, x1, y1 = _box(rec["words"][i]["bbox"], 3, W, H); reg = out[y0:y1, x0:x1]
            dens = np.clip(1 - reg.min(axis=2, keepdims=True), 0, 1); out[y0:y1, x0:x1] = 1 - dens * (1 - col)
    # strike-through: wavy pen line, multiplied onto the text layer
    cand = [i for i in idx if len(rec["words"][i]["text"]) >= 3]
    struck = sorted(rnd.sample(cand, min(len(cand), max(2, int(len(idx) * hc["strike"])))))
    ss = 3; layer = Image.new("L", (W * ss, H * ss), 0); d = ImageDraw.Draw(layer)
    for i in struck:
        b = rec["words"][i]["bbox"]; midy = (b[1] + b[3]) / 2
        for t in range(rnd.choice([1, 2])):
            pts = []; x = b[0] - 3; yy = midy + rnd.uniform(-3, 3) * sc + t * 5 * sc
            while x < b[2] + 4:
                pts.append(((x) * ss, (yy + rnd.uniform(-2.2, 2.2) * sc) * ss)); x += rnd.uniform(5, 9)
            d.line(pts, fill=235, width=max(2, int(round(fs * 0.09 * ss))), joint="curve")
    a = np.asarray(layer.resize((W, H), Image.LANCZOS)).astype(np.float32)[..., None] / 255.0
    ink = np.asarray(ink_rgb, np.float32) / 255.0
    out = out * (1 - a * (1 - ink))
    return out, struck


def add_corrections(c, struck, rnd: random.Random, share=0.7):
    """A new word written above about `share` of the struck words (same hand, same page ink). It is a scored word of kind 'correction'
    and is read right after the word it replaces, so the transcript reads: ~~old~~ new."""
    from .step3_layout import wrap_words
    words = c.rec["words"]; pool = [w["text"] for w in words if w.get("kind") == "body" and len(w["text"]) >= 3]
    from .step4_compose import _rgb_from_hex
    for i in struck:
        if rnd.random() > share: continue
        sw = words[i]; b = sw["bbox"]; txt = rnd.choice([t for t in pool if t != sw["text"]] or pool)
        n0 = len(c.extra_words)
        c.snippet_place(wrap_words(txt), c.fs * 0.9, _rgb_from_hex(c.ink), (b[0] + b[2]) / 2, b[1] - (b[3] - b[1]) * 0.30,
                        angle=rnd.uniform(-5, 5), opacity=rnd.uniform(0.8, 0.95), kind="correction", scored=True)
        for w in c.extra_words[n0:]:
            w["dom_bbox"] = list(sw.get("dom_bbox", sw["bbox"])); w["sort_x"] = sw["bbox"][0] + 0.5 * (sw["bbox"][2] - sw["bbox"][0]) + 0.01 * (w["bbox"][0] - b[0])


def add_signatures_over_text(c, rnd: random.Random):
    """A signature scrawled across the body text (a second signer, or an initial in the wrong place). Recorded as an element so the damage step
    counts the words it covers as occluded."""
    n = rnd.choice(c.cfg["hard"].get("sig_over", [1, 2])); lines = [l for l in c.rec["lines"] if l["para"] >= 0]
    from .assets import tint
    from .imaging import place
    from .step4_compose import INK
    for _ in range(n):
        a = c.lib.pick("signatures", rnd)
        if a is None or not lines: break
        l = rnd.choice(lines); im = tint(a.load(), INK[rnd.choice(["black", "blueblack", "blue"])])
        w = c.W * rnd.uniform(0.16, 0.26); cx = rnd.uniform(c.cx0 + w / 2, c.cx1 - w / 2); cy = (l["bbox"][1] + l["bbox"][3]) / 2
        poly = place(c.base, im, cx, cy, width=w, angle=rnd.uniform(-12, 12), opacity=rnd.uniform(0.8, 0.95), flip=rnd.random() < 0.4)
        c.add("signature", poly, False, asset=a.name, slot=-1)


# ---------------------------------------------------------------- stage 4: local damage (called from step5 on hard pages only; pixel effects, no geometry change)
def _paper_ink(img):
    u8 = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    g = cv2.cvtColor(u8, cv2.COLOR_RGB2GRAY).astype(np.float32); paper_g = cv2.medianBlur(cv2.cvtColor(u8, cv2.COLOR_RGB2GRAY), 31).astype(np.float32)
    paper = cv2.medianBlur(u8, 31).astype(np.float32) / 255.0
    return np.clip((paper_g - g) / 255.0 * 3.0, 0, 1)[..., None], paper


def ink_fade(st, rnd: random.Random, nrng, sev):
    """Ink that has faded out in soft patches (not a global fade: some lines stay dark next to unreadable ones)."""
    a = st.img; H, W = a.shape[:2]; s = min(1.0, sev / 1.7); m, paper = _paper_ink(a); k = W / 1240.0
    fade = np.zeros((H, W), np.float32)
    for _ in range(max(4, int(round(H * W / 280000)))):
        cx, cy = rnd.randint(int(W * .06), int(W * .94)), rnd.randint(int(H * .12), int(H * .85))
        cv2.ellipse(fade, (cx, cy), (int(rnd.randint(50, 140) * k), int(rnd.randint(25, 60) * k)), rnd.randint(0, 180), 0, 360, 1.0, -1)
    fade = cv2.GaussianBlur(fade, (0, 0), 22 * k) * np.clip(0.6 + 0.8 * _smooth(H, W, 25, nrng), 0, 1)
    fade = np.clip(fade * 1.1, 0, 0.72 * s)[..., None]
    st.img[:] = a + (paper - a) * fade * m
    st.log.append({"op": "ink_fade"})


def show_through(st, rnd: random.Random, sev):
    """The writing on the other side of the paper shows through (stronger than the generic bleed-through op, and mirrored like a real reverse)."""
    a = st.img; s = min(1.0, sev / 1.7)
    back = cv2.GaussianBlur(a[:, ::-1].copy(), (0, 0), 2.5)
    bm = 1 - cv2.cvtColor((np.clip(back, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    st.img[:] = a * (1 - np.clip(bm * 0.35, 0, 0.22 * s)[..., None] * 0.9)
    st.log.append({"op": "show_through"})


def cracked_ink(st, rnd: random.Random, sev):
    """Ink flaked off along the real fold lines (same lines op_folds drew)."""
    folds = getattr(st, "fold_lines", None)
    if not folds: return
    a = st.img; H, W = a.shape[:2]; s = min(1.0, sev / 1.7); m, paper = _paper_ink(a)
    keep = np.zeros((H, W), np.float32)
    for kind, pos in folds:
        L = W if kind == "h" else H
        for i in range(int(L / 3)):
            t = i * 3 + rnd.uniform(-1, 1); off = pos + rnd.uniform(-2.5, 2.5)
            x, y = (int(t), int(off)) if kind == "h" else (int(off), int(t))
            if rnd.random() < 0.55: keep[max(0, y - 3):y + 4, max(0, x - 3):x + 4] = 1.0
    keep = cv2.GaussianBlur(keep, (0, 0), 0.8)[..., None] * 0.85 * s
    st.img[:] = a + (paper - a) * np.clip(keep, 0, 1) * m
    st.log.append({"op": "cracked_ink"})


def photocopy_look(st, rnd: random.Random, sev):
    """Photocopy: harder contrast and faint horizontal banding (seeded; replaces the unrepeatable BadPhotoCopy for hard pages)."""
    a = st.img; H = a.shape[0]; s = min(1.0, sev / 1.7)
    a = np.clip((a - 0.05 * s) * (1 + 0.08 * s), 0, 1); ph = rnd.uniform(0, 6.28)
    band = 1 - 0.05 * s * np.sin(np.arange(H) * 0.9 + ph)[:, None, None] * (0.5 + 0.5 * np.sin(np.arange(H) * 0.013 + ph)[:, None, None])
    st.img[:] = a * band
    st.log.append({"op": "photocopy_look"})


# ---------------------------------------------------------------- stage 5: phone photo (hard pages, only sometimes; called from step5)
def phone_photo(st, rnd: random.Random, nrng, sev):
    """The page photographed on a desk with a phone: paper curl, camera angle (keystone), a hand shadow, a thumb at one edge, soft focus on one side
    and sensor grain. The geometry parts move the word polygons and the clean target with the pixels (via step5's own warp helper); the thumb is
    recorded as an element, so the words it covers count as occluded."""
    from .step5_degrade import _warp_both, op_perspective, _add_element
    H, W = st.img.shape[:2]; k = W / 1240.0
    # curl: x shifted by a function of y, then y shifted by a function of x. Each shift is exact, so the polygons follow it exactly.
    A = rnd.uniform(6, 14) * k; lam = rnd.uniform(0.9, 2.2) * H; ph = rnd.uniform(0, 6.28)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    mx = xx - A * np.sin(2 * math.pi * yy / lam + ph)
    wx = lambda im, bg: cv2.remap(im, mx, yy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in bg))
    _warp_both(st, wx, lambda p: np.stack([p[:, 0] + A * np.sin(2 * math.pi * p[:, 1] / lam + ph), p[:, 1]], 1))
    B = rnd.uniform(3, 8) * k; lam2 = rnd.uniform(0.9, 2.2) * W; ph2 = rnd.uniform(0, 6.28)
    my = yy - B * np.sin(2 * math.pi * xx / lam2 + ph2)
    wy = lambda im, bg: cv2.remap(im, xx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in bg))
    _warp_both(st, wy, lambda p: np.stack([p[:, 0], p[:, 1] + B * np.sin(2 * math.pi * p[:, 0] / lam2 + ph2)], 1))
    op_perspective(st, rnd, nrng, sev * 1.5)                                  # camera angle
    st.log.pop()                                                              # (its own log line; this op logs once below)
    a = st.img; H, W = a.shape[:2]
    # a soft hand shadow from one side
    side = rnd.choice([0, 1]); pts = np.array([[W * (0.0 if side == 0 else 1.0), rnd.uniform(0.1, 0.5) * H], [W * rnd.uniform(0.35, 0.6) if side == 0 else W * rnd.uniform(0.4, 0.65), rnd.uniform(0.3, 0.6) * H],
                                              [W * (0.0 if side == 0 else 1.0), rnd.uniform(0.7, 1.0) * H]], np.int32)
    m = np.zeros((H, W), np.float32); cv2.fillPoly(m, [pts], 1.0); m = cv2.GaussianBlur(m, (0, 0), 38 * k)
    a = a * (1 - 0.30 * m)[..., None]
    # a thumb holding the page at one edge
    tx = W * (0.05 if rnd.random() < 0.5 else 0.95); ty = H * rnd.uniform(0.55, 0.85); ax = (int(100 * k), int(190 * k)); ang = rnd.uniform(-20, 20)
    th = np.zeros((H, W), np.float32); cv2.ellipse(th, (int(tx), int(ty)), ax, ang, 0, 360, 1.0, -1); th = cv2.GaussianBlur(th, (0, 0), 8 * k)
    skin = np.array([0.80, 0.58, 0.46], np.float32) * (0.75 + 0.25 * _smooth(H, W, 40, nrng)[..., None])
    a = a * (1 - th[..., None] * 0.95) + skin * th[..., None] * 0.95
    poly = cv2.boxPoints(((float(tx), float(ty)), (2.0 * ax[0], 2.0 * ax[1]), float(ang))).astype(float).tolist()      # 4-point box around the thumb (every element is a 4-point polygon)
    # soft focus on one side, then sensor grain
    Xg = np.arange(W, dtype=np.float32)[None, :]; fm = np.clip((Xg / W - 0.55) * 2, 0, 1)[..., None] if side == 0 else np.clip((0.45 - Xg / W) * 2, 0, 1)[..., None]
    a = a * (1 - fm) + cv2.GaussianBlur(a, (0, 0), 1.6) * fm
    a = a + nrng.standard_normal(a.shape).astype(np.float32) * 0.010
    st.img = np.clip(a, 0, 1).astype(np.float32)
    _add_element(st, "finger", [[round(x, 1), round(y, 1)] for x, y in poly])
    st.log.append({"op": "phone_photo"})
