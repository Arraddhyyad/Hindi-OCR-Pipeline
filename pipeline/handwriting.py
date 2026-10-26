"""Handwriting support (v2 only). Nothing here is imported by the v1 code path.

  hybrid_marks  which words of the printed body are written by hand (names, dates, amounts, numbers from the entity graph)
  word_params   per-word jitter (small rotation, baseline shift, size, ink strength). Per WORD only: per-letter jitter would break Devanagari shaping.
  word_poly     the 4-point polygon of a jittered word, computed from the transform that was really applied in the browser.
"""
import math, random

TRIM = ",.;:।॥)(\"'“”‘’[]"
DIGITS = set("0123456789०१२३४५६७८९")
FACT_KEYS = {  # config name -> function(graph) -> list of strings
    "date": lambda g: [g["date"]], "village": lambda g: [g["village"]], "tehsil": lambda g: [g["tehsil"]], "district": lambda g: [g["district"]],
    "khasra": lambda g: [g["khasra"]], "area": lambda g: [g["area"]], "amount_text": lambda g: [g["amount_text"]],
    "amount_words": lambda g: [g["amount_words"]], "payment": lambda g: [g["payment"]], "stamp_duty": lambda g: [g["stamp_duty"]],
    "seller": lambda g: [g["seller"]["name"]], "buyer": lambda g: [g["buyer"]["name"]],
    "seller_relative": lambda g: [g["seller"]["relative"]], "buyer_relative": lambda g: [g["buyer"]["relative"]],
    "witnesses": lambda g: [w["name"] for w in g["witnesses"]], "boundaries": lambda g: list(g["boundaries"].values()),
}


def _core(tok):
    return tok.strip(TRIM)


def hybrid_marks(paras, graph, keys, digits=True):
    """Set of (paragraph index, word index) to write by hand. A fact matches when its words appear as consecutive words of a paragraph
    (punctuation stuck to a word is ignored when comparing, and is written by hand with it). Digit-bearing words are included when `digits`."""
    facts = [f.split() for k in keys for f in FACT_KEYS[k](graph)]
    out = set()
    for pi, p in enumerate(paras):
        toks = p["text"].replace("\n", " ").split(); core = [_core(t) for t in toks]
        for f in facts:
            n = len(f)
            if not n: continue
            fc = [_core(x) for x in f]
            for s in range(len(toks) - n + 1):
                if core[s:s + n] == fc: out.update((pi, s + j) for j in range(n))
        if digits:
            out.update((pi, wi) for wi, t in enumerate(toks) if DIGITS & set(t))
    return out


def word_params(key, n, jit, fs, messy=1.0):
    """Deterministic per-word jitter for n words. `key` is a string (page seed based) so the stream is private to this feature.
    `messy` (per page, about 0.7-1.8) scales how untidy the writer is. gap = extra space before the word (em), skew = slant change (deg)."""
    rng = random.Random(key); ph = rng.uniform(0, 6.28); out = []; m = messy
    for i in range(n):
        out.append({"angle": max(-2.5 * jit["angle_deg"] * m, min(2.5 * jit["angle_deg"] * m, rng.gauss(0, jit["angle_deg"] * m))),
                    "dy": rng.gauss(0, jit["dy_em"] * m * fs) + 0.5 * jit["dy_em"] * m * fs * math.sin(i * 0.35 + ph),
                    "scale": rng.uniform(1 - jit["scale"] * m, 1 + jit["scale"] * m),
                    "alpha": rng.uniform(*jit["alpha"]),
                    "skew": max(-8.0, min(8.0, rng.gauss(0, jit.get("skew_deg", 0.0) * m))),
                    "gap": rng.uniform(0, jit.get("gap_em", 0.0) * m)})
    return out


def line_params(key, jit, fs, messy=1.0):
    """One baseline wobble and tilt per written line (all words of a line share it)."""
    r = random.Random(key)
    return r.gauss(0, jit.get("line_dy_em", 0.0) * messy * fs), r.gauss(0, jit.get("line_angle_deg", 0.0) * messy)


def word_poly(box, dom_box, p):
    """box = tight ink box [x0,y0,x1,y1]; dom_box = the element's own box (transform origin is its centre).
    Applied transform (CSS): translate(0,dy) rotate(angle) scale(scale) skewX(skew) about the centre. Returns 4 corners TL,TR,BR,BL."""
    cx, cy = (dom_box[0] + dom_box[2]) / 2, (dom_box[1] + dom_box[3]) / 2
    a = math.radians(p["angle"]); ca, sa = math.cos(a), math.sin(a); s = p["scale"]; tk = math.tan(math.radians(p.get("skew", 0.0)))
    pts = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        dx, dy = x - cx, y - cy
        dx = dx + tk * dy
        dx, dy = dx * s, dy * s
        pts.append([round(cx + dx * ca - dy * sa, 1), round(cy + p["dy"] + dx * sa + dy * ca, 1)])
    return pts
