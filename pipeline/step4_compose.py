"""STEP 4 - compose: paper, header, footer, body text, overlapping text, stamps, signatures, thumbprints, marks, margin notes from assets/. Every element recorded with a polygon.
"""
import io, math, random
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from .assets import tint, AssetLib
from .step1_entities import generate_entity_graph
from .step2_text import TemplateWriter
from .step3_layout import cluster_lines, wrap_words, faces_css
from .imaging import place, rect_polygon, poly_bbox, transform_box, multiply

INK = {"black": (20, 20, 28), "blueblack": (26, 26, 94), "blue": (23, 51, 143), "red": (190, 25, 30), "purple": (110, 40, 130)}
NOTE_WORDS = ["देखें", "सही", "जाँच", "रद्द", "पुनः", "नोट", "मंजूर", "देखा", "ठीक", "कृपया", "प्रमाणित"]
DIGITS = set("0123456789०१२३४५६७८९")
DEFAULTS = {
    "header_mode": {"banner": 0.6, "letterhead": 0.25, "none": 0.15},
    "footer_mode": {"endorsement": 0.5, "line": 0.2, "none": 0.3},
    "p_overlap_text": 0.45, "p_text_stamp": 0.65, "stamps": {1: 0.35, 2: 0.4, 3: 0.25},
    "marks": [2, 5], "notes": [0, 3], "p_thumb_party": 0.7, "p_thumb_witness": 0.15,
    "mark_types": {"oval": 0.3, "tick": 0.2, "cross": 0.12, "underline": 0.2, "strike": 0.06, "arrow": 0.12},
    "note_fonts": "'Kalam','Amita','Noto Sans Devanagari'",
}


def _wc(rng, d):
    return rng.choices(list(d), weights=list(d.values()))[0]


def _rgb(name_or_rgb):
    return INK[name_or_rgb] if isinstance(name_or_rgb, str) else name_or_rgb


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


class Ctx:
    def __init__(self, base, rec, lib, cfg, rng, renderer, W, H):
        self.base, self.rec, self.lib, self.cfg, self.rng, self.r, self.W, self.H = base, rec, lib, cfg, rng, renderer, W, H
        self.els, self.extra_words, self.extra_lines = [], [], []
        page = rec["page"]
        self.fs, self.ink, self.family = page["font_size"], page["ink"], page["font"]
        if page.get("ext"): self.fs = min(self.fs, 30.0)      # v2: header, footer, stamps and notes keep a sane size when the body is set in very large type
        self.body = rec["slots"]["body"]            # x0,y0,x1,y1
        self.cx0, self.cx1 = self.body[0], self.body[2]
        self.face = f"'{self.family}','Noto Serif Devanagari','Noto Sans Devanagari'"
        self.faces = faces_css(page["ext"]["faces"]) if page.get("ext") else ""     # "" for v1 configs: snippet HTML is then identical to before

    def add(self, type_, poly, scored=False, **kw):
        self.els.append({"type": type_, "bbox": [round(v, 1) for v in poly_bbox(poly)], "poly": poly, "scored": scored, **kw})

    def snippet_place(self, inner, size, color, cx, cy, angle=0.0, opacity=1.0, kind="text", scored=False, font=None, weight=400,
                      extra_css="", width=None, **kw):
        im, words = self.r.snippet(inner, font or self.face, size, _hex(color), extra_css=extra_css, width=width, weight=weight, faces=self.faces)
        poly = place(self.base, im, cx, cy, width=im.width, angle=angle, opacity=opacity)
        ws = []
        for w in words:
            wp = transform_box(w["bbox"], im.width / 2, im.height / 2, cx, cy, angle)
            dp = transform_box(w["dom_bbox"], im.width / 2, im.height / 2, cx, cy, angle)       # content-area box: used only to order words into lines
            ws.append({"text": w["text"], "bbox": [round(v, 1) for v in poly_bbox(wp)], "poly": wp, "kind": kind, "scored": scored,
                       "dom_bbox": [round(v, 1) for v in poly_bbox(dp)]})
        self.extra_words += ws
        self.add(kind, poly, scored, words=len(ws), **kw)
        return im, ws, poly


# ------------------------------------------------------------------ paper
def make_paper(lib, W, H, rng, nrng):
    a = lib.pick("paper", rng)
    if a is None:
        n = nrng.normal(0, 0.012, (H, W, 1)).astype(np.float32)
        return np.clip(np.array([0.93, 0.90, 0.82], np.float32) + n, 0, 1), "procedural"
    im = a.load()
    s = max(W / im.width, H / im.height) * rng.uniform(1.0, 1.3)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    if rng.random() < 0.5: im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if rng.random() < 0.5: im = im.transpose(Image.FLIP_TOP_BOTTOM)
    x, y = rng.randint(0, im.width - W), rng.randint(0, im.height - H)
    arr = np.asarray(im.crop((x, y, x + W, y + H))).astype(np.float32) / 255.0
    lum = arr.mean(axis=2, keepdims=True)
    sat = cfg_sat if (cfg_sat := 0.55) else 1.0                      # keep 55% of the texture's colour variation
    arr = lum + (arr - lum) * sat
    arr *= np.array([rng.uniform(0.97, 1.03) for _ in range(3)], np.float32)
    return np.clip(arr * 1.06, 0, 1), a.name


# ------------------------------------------------------------------ header / footer
def add_header(c: Ctx):
    cfg, rng, rec, g = c.cfg, c.rng, c.rec, c.rec["entities"]
    slot = rec["slots"]["header"]; top, zone_h = slot[1], slot[3] - slot[1]
    mode = _wc(rng, cfg["header_mode"]); info = {"mode": mode}
    cw = c.cx1 - c.cx0
    if mode == "banner" and c.lib.get("headers"):
        a = rng.choice(c.lib.get("headers")); im = a.load()
        w = cw * rng.uniform(0.55, 0.95); h = im.height * w / im.width
        text_h = c.fs * 1.45 + 14
        if h > zone_h - text_h - 8:
            h = zone_h - text_h - 8; w = h * im.width / im.height
        cx = (c.cx0 + c.cx1) / 2 + rng.uniform(-25, 25); cy = top + 6 + h / 2
        poly = place(c.base, im, cx, cy, width=w, angle=rng.uniform(-0.7, 0.7), opacity=rng.uniform(0.85, 1.0))
        c.add("header_banner", poly, False, asset=a.name)
        y_text = top + 6 + h + 8; info["asset"] = a.name
        reg = g["registration"]
        inner = (f'<div style="display:flex;justify-content:space-between"><span>{wrap_words("पंजीकरण संख्या: " + reg["no"] + "/" + reg["year"])}</span>'
                 f'<span>{wrap_words("दिनांक: " + g["date"])}</span></div>')
        _, ws, _ = c.snippet_place(inner, c.fs * 0.85, _rgb_from_hex(c.ink), (c.cx0 + c.cx1) / 2, y_text + c.fs * 0.5, kind="header_text",
                                   scored=True, width=int(cw))
    elif mode == "letterhead":
        inner = (f'<div style="text-align:center">{wrap_words("उत्तर प्रदेश शासन")}</div>'
                 f'<div style="text-align:center;font-weight:700;font-size:1.45em;border-bottom:2px solid {c.ink};padding-bottom:6px">'
                 f'{wrap_words("उप-निबंधक कार्यालय, " + g["district"])}</div>')
        c.snippet_place(inner, c.fs * 1.0, _rgb_from_hex(c.ink), (c.cx0 + c.cx1) / 2, top + zone_h * 0.4, kind="header_text", scored=True, width=int(cw))
    return info


def _rgb_from_hex(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def add_footer(c: Ctx):
    rng, rec, g = c.rng, c.rec, c.rec["entities"]
    slot = rec["slots"]["footer"]; bot, zone_h = slot[3], slot[3] - slot[1]
    mode = _wc(rng, c.cfg["footer_mode"]); cw = c.cx1 - c.cx0
    if mode == "endorsement":
        reg = g["registration"]
        lines = [f"उप-निबंधक कार्यालय, {g['district']}",
                 f"पंजीकरण संख्या {reg['no']} / {reg['year']}, बही संख्या {reg['book']}, जिल्द संख्या {reg['volume']}, पृष्ठ संख्या {reg['page']}",
                 f"आज दिनांक {g['date']} को प्रस्तुत एवं पंजीकृत किया गया। उप-निबंधक"]
        inner = "".join(f"<div>{wrap_words(l)}</div>" for l in lines)
        size = c.fs * 0.82
        for _ in range(3):
            im, words = c.r.snippet(inner, c.face, size, c.ink, width=int(cw * 0.78), faces=c.faces,
                                    extra_css=f"border:2px solid {c.ink};padding:10px 16px;box-sizing:border-box")
            if im.height <= zone_h - 12: break
            size *= 0.85
        cx = (c.cx0 + c.cx1) / 2 + rng.uniform(-30, 30); cy = bot - im.height / 2 - rng.uniform(2, 14)
        poly = place(c.base, im, cx, cy, width=im.width, angle=rng.uniform(-0.6, 0.6))
        ws = [{"text": w["text"], "bbox": [round(w["bbox"][0] + cx - im.width / 2, 1), round(w["bbox"][1] + cy - im.height / 2, 1),
                round(w["bbox"][2] + cx - im.width / 2, 1), round(w["bbox"][3] + cy - im.height / 2, 1)], "kind": "footer_text", "scored": True,
                "dom_bbox": [round(w["dom_bbox"][0] + cx - im.width / 2, 1), round(w["dom_bbox"][1] + cy - im.height / 2, 1),
                             round(w["dom_bbox"][2] + cx - im.width / 2, 1), round(w["dom_bbox"][3] + cy - im.height / 2, 1)]} for w in words]
        c.extra_words += ws; c.add("footer_endorsement", poly, False, words=len(ws))
    elif mode == "line":
        d = Image.new("RGBA", (int(cw), 4), (*_rgb_from_hex(c.ink), 255))
        poly = place(c.base, d, (c.cx0 + c.cx1) / 2, bot - 30, width=cw * 0.95)
        c.add("footer_rule", poly, False)
    return {"mode": mode}


# ------------------------------------------------------------------ stamps, signatures
def _where(c: Ctx, strategy):
    rng, rec, W, H = c.rng, c.rec, c.W, c.H
    lines = [l for l in rec["lines"] if l["para"] >= 0]
    if strategy == "text" and lines:
        l = rng.choice(lines); return rng.uniform(c.cx0 + 80, c.cx1 - 80), (l["bbox"][1] + l["bbox"][3]) / 2 + rng.uniform(-25, 25)
    if strategy == "sign":
        s = rec["slots"]["signature"]; return rng.uniform(c.cx0 + 100, c.cx1 - 100), s[0][1] - rng.uniform(10, 70)
    if strategy == "footer":
        f = rec["slots"]["footer"]; return rng.uniform(c.cx0 + 100, c.cx1 - 100), (f[1] + f[3]) / 2
    return rng.choice([W * 0.12, W * 0.88]), rng.uniform(H * 0.25, H * 0.8)


def add_stamps(c: Ctx):
    rng, W = c.rng, c.W
    n = _wc(rng, c.cfg["stamps"]); out = []
    for _ in range(n):
        a = c.lib.pick("stamps", rng)
        if a is None: break
        im = a.load(); col = None
        if rng.random() < 0.5:
            col = rng.choice(["blueblack", "blue", "red", "purple", "black"]); im = tint(im, INK[col])
        x, y = _where(c, _wc(rng, {"text": .4, "sign": .25, "footer": .15, "edge": .2}))
        w = W * rng.uniform(0.14, 0.26)
        poly = place(c.base, im, x, y, width=w, angle=rng.uniform(-25, 25), opacity=rng.uniform(0.75, 0.95))
        c.add("stamp", poly, False, asset=a.name, tint=col); out.append(a.name)
    if rng.random() < c.cfg["p_text_stamp"]:
        g = c.rec["entities"]; col = rng.choice(["blueblack", "blue", "purple", "red"]); k = INK[col]
        lines = rng.choice([["पंजीकृत", f"उप-निबंधक कार्यालय, {g['district']}", f"दिनांक {g['date']}"],
                            ["स्टाम्प शुल्क अदा किया गया", f"रुपये {g['stamp_duty']}"], ["प्रमाणित प्रतिलिपि", "अभिलेख कक्ष"]])
        inner = "".join(f"<div>{wrap_words(l)}</div>" for l in lines)
        x, y = _where(c, _wc(rng, {"text": .45, "sign": .2, "footer": .15, "edge": .2}))
        c.snippet_place(inner, c.fs * rng.uniform(0.95, 1.2), k, x, y, angle=rng.uniform(-12, 12), opacity=rng.uniform(0.7, 0.92), kind="stamp_text",
                        weight=700, extra_css=f"border:3px double {_hex(k)};padding:8px 18px;text-align:center")
        out.append("text_stamp")
    return out


def add_signatures(c: Ctx):
    rng, lib = c.rng, c.lib
    for i, s in enumerate(c.rec["slots"]["signature"]):
        party = i < 2
        sw, sh = s[2] - s[0], s[3] - s[1]
        if rng.random() < (0.95 if party else 0.85):
            a = lib.pick("signatures", rng)
            if a:
                im = tint(a.load(), INK[rng.choice(["black", "blueblack", "blue"])])
                w = min(sw * rng.uniform(0.5, 0.85), 85 * im.width / im.height)
                cx, cy = (s[0] + s[2]) / 2 + rng.uniform(-18, 18), s[3] - w * im.height / im.width / 2 + rng.uniform(-2, 10)
                poly = place(c.base, im, cx, cy, width=w, angle=rng.uniform(-7, 7), opacity=rng.uniform(0.85, 1.0), flip=rng.random() < 0.4)
                c.add("signature", poly, False, asset=a.name, slot=i)
        if rng.random() < (c.cfg["p_thumb_party"] if party else c.cfg["p_thumb_witness"]):
            a = lib.pick("thumbprints", rng)
            if a:
                im = tint(a.load(), INK[rng.choice(["blueblack", "purple", "black"])])
                w = rng.uniform(58, 82)
                poly = place(c.base, im, s[2] - rng.uniform(25, 55), s[1] + rng.uniform(18, 45), width=w, angle=rng.uniform(-25, 25), opacity=rng.uniform(0.75, 0.95))
                c.add("thumbprint", poly, False, asset=a.name, slot=i)


# ------------------------------------------------------------------ overlapping text
def add_overlap_text(c: Ctx):
    rng = c.rng
    g2 = generate_entity_graph(rng, c.cfg)
    d2 = TemplateWriter().write(g2, rng, 140)
    text = " ".join(p["text"] for p in d2.paragraphs[1:4])
    col = rng.choice(["blueblack", "black", "purple"]); W, H = c.W, c.H
    wd = int(W * rng.uniform(0.42, 0.68))
    c.snippet_place(wrap_words(text), c.fs * rng.uniform(0.9, 1.1), INK[col], rng.uniform(0.3, 0.7) * W, rng.uniform(0.3, 0.7) * H,
                    angle=rng.uniform(-6, 6), opacity=rng.uniform(0.28, 0.55), kind="overlap_text", width=wd,
                    extra_css="text-align:justify")
    return True


# ------------------------------------------------------------------ marks drawn on word boxes
def _stroke(pts, thick, color, ss=3):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = int(thick * 2 + 4); x0, y0 = min(xs) - pad, min(ys) - pad
    w, h = int(max(xs) - x0 + pad), int(max(ys) - y0 + pad)
    im = Image.new("RGBA", (max(2, w) * ss, max(2, h) * ss), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.line([((x - x0) * ss, (y - y0) * ss) for x, y in pts], fill=(*color, 255), width=max(1, int(thick * ss)), joint="curve")
    return im.resize((max(2, w), max(2, h)), Image.LANCZOS), x0, y0


def add_marks(c: Ctx):
    rng, rec, lib = c.rng, c.rec, c.lib
    words = [w for w in rec["words"] if w["kind"] == "body"]
    digit_words = [w for w in words if DIGITS & set(w["text"])]
    lines = [l for l in rec["lines"] if l["para"] >= 0 and len(l["words"]) >= 3]
    n = rng.randint(*c.cfg["marks"]); used = []
    for _ in range(n):
        t = _wc(rng, c.cfg["mark_types"]); col = rng.choices(["red", "blueblack", "black", "blue"], [.5, .25, .15, .1])[0]; k = INK[col]
        op = rng.uniform(0.85, 1.0)
        if t == "oval" and (digit_words or words) and lib.get("marks"):
            w = rng.choice(digit_words if digit_words and rng.random() < 0.8 else words); b = w["bbox"]
            a = [m for m in lib.get("marks") if m.name.startswith("circle")]
            if not a: continue
            im = tint(a[0].load(), k)
            bw, bh = (b[2] - b[0]) * 1.3 + 26, (b[3] - b[1]) * 1.5 + 8
            poly = place(c.base, im, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, stretch=(bw, bh), angle=rng.uniform(-4, 4), opacity=op, flip=rng.random() < .5)
            c.add("mark_oval", poly, False, colour=col, target=w["text"])
        elif t in ("tick", "cross") and lib.get("marks") and lines:
            a = [m for m in lib.get("marks") if m.name.startswith(t)]
            if not a: continue
            l = rng.choice(lines); b = l["bbox"]
            w = rng.uniform(30, 46)
            x = rng.choice([c.cx0 - rng.uniform(35, 65), c.cx1 + rng.uniform(25, 55), rng.uniform(b[0] + 60, b[2] - 60)])
            poly = place(c.base, tint(a[0].load(), k), x, (b[1] + b[3]) / 2 + rng.uniform(-6, 6), width=w, angle=rng.uniform(-15, 15), opacity=op, flip=rng.random() < .3)
            c.add(f"mark_{t}", poly, False, colour=col)
        elif t == "underline" and lines:
            l = rng.choice(lines); ws = [rec["words"][i] for i in l["words"]]
            j = rng.randint(0, len(ws) - 2); kk = min(len(ws) - 1, j + rng.randint(1, 4))
            x0, x1, yb = ws[j]["bbox"][0], ws[kk]["bbox"][2], ws[j]["bbox"][3] - rng.uniform(1, 5)
            pts = [(x, yb + 2.2 * math.sin(x / rng.uniform(35, 60)) + rng.uniform(-.8, .8)) for x in np.linspace(x0, x1, max(6, int((x1 - x0) / 12)))]
            im, ox, oy = _stroke(pts, rng.uniform(2.2, 3.6), k)
            poly = place(c.base, im, ox + im.width / 2, oy + im.height / 2, width=im.width, opacity=op)
            c.add("mark_underline", poly, False, colour=col)
        elif t == "strike" and words:
            w = rng.choice(words); b = w["bbox"]; yc = (b[1] + b[3]) / 2
            pts = [(b[0] - 3, yc + rng.uniform(-3, 3)), (b[2] + 3, yc + rng.uniform(-3, 3))]
            im, ox, oy = _stroke(pts, rng.uniform(2.0, 3.2), k)
            poly = place(c.base, im, ox + im.width / 2, oy + im.height / 2, width=im.width, opacity=op)
            c.add("mark_strike", poly, False, colour=col, target=w["text"])
        elif t == "arrow" and lines:
            l = rng.choice(lines); b = l["bbox"]; yc = (b[1] + b[3]) / 2; L = rng.uniform(45, 75)
            side = rng.choice([-1, 1]); x1 = (c.cx0 - 6) if side < 0 else (c.cx1 + 6); x0 = x1 - side * L
            pts = [(x0, yc + rng.uniform(-14, 14)), (x1, yc)]
            ang = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
            head = [(x1 - 12 * math.cos(ang - .5), pts[1][1] - 12 * math.sin(ang - .5)), (x1, yc), (x1 - 12 * math.cos(ang + .5), pts[1][1] - 12 * math.sin(ang + .5))]
            im, ox, oy = _stroke(pts + head[:1] + [pts[1]] + head[2:], rng.uniform(2.2, 3.2), k)
            poly = place(c.base, im, ox + im.width / 2, oy + im.height / 2, width=im.width, opacity=op)
            c.add("mark_arrow", poly, False, colour=col)


def add_notes(c: Ctx):
    rng, W = c.rng, c.W
    for _ in range(rng.randint(*c.cfg["notes"])):
        text = rng.choice(NOTE_WORDS) if rng.random() < 0.7 else str(rng.randint(1, 99))
        col = rng.choice(["red", "red", "blueblack"])
        if rng.random() < 0.6:
            x = rng.choice([c.cx0 * 0.5, W - (W - c.cx1) * 0.5]) + rng.uniform(-10, 10); y = rng.uniform(c.body[1] + 40, c.body[3] - 40)
        else:
            x = rng.uniform(c.cx0 + 60, c.cx1 - 60); y = c.body[1] - rng.uniform(8, 26)
        c.snippet_place(wrap_words(text), c.fs * rng.uniform(1.0, 1.35), INK[col], x, y, angle=rng.uniform(-14, 14), opacity=rng.uniform(0.8, 0.95),
                        kind="margin_note", font=c.cfg["note_fonts"], weight=400)


# ------------------------------------------------------------------ entry point
def compose_page(clean_png: bytes, rec: dict, lib: AssetLib, cfg: dict, rng: random.Random, renderer):
    cfg = {**DEFAULTS, **cfg.get("compose", {})}
    clean = Image.open(io.BytesIO(clean_png)).convert("RGB"); W, H = clean.size
    nrng = np.random.default_rng(rng.randrange(2**31))
    base, paper = make_paper(lib, W, H, rng, nrng)
    hard = bool(cfg.get("hard") and ((rec.get("page") or {}).get("ext") or {}).get("hard"))      # v2 hard pages only (otherwise nothing below runs)
    if hard: cfg = {**cfg, **cfg["hard"].get("clutter", {})}                                      # stage 3: more marks, notes, stamps and overlapping text
    c = Ctx(base, rec, lib, cfg, rng, renderer, W, H)
    comp = {"paper": paper}
    comp["header"] = add_header(c)
    comp["footer"] = add_footer(c)
    struck = []
    if hard:
        from . import hard_effects
        hrnd = random.Random(f"hardfx|{rec['seed']}")
        arr, struck = hard_effects.messy_text(np.asarray(clean).astype(np.float32) / 255.0, rec, hrnd, cfg["hard"], _rgb_from_hex(c.ink))
        clean = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    base *= np.asarray(clean).astype(np.float32) / 255.0          # the deed's own text
    if rng.random() < cfg["p_overlap_text"]:
        comp["overlap_text"] = add_overlap_text(c)
    comp["stamps"] = add_stamps(c)
    add_signatures(c)
    add_marks(c)
    add_notes(c)
    if hard: hard_effects.add_corrections(c, struck, random.Random(f"hardfx2|{rec['seed']}"))
    if hard: hard_effects.add_signatures_over_text(c, random.Random(f"hardfx3|{rec['seed']}"))
    img = Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8))
    # all words with scored flags, in one list
    body_words = [{**w, "scored": True} for w in rec["words"]]
    for i in struck: body_words[i]["struck"] = True               # hard pages: the word stays in the transcript and is flagged as struck through
    words_all = body_words + c.extra_words
    scored = [w for w in words_all if w["scored"]]
    dtop = lambda w: w.get("dom_bbox", w["bbox"])[1]
    ordered = sorted(scored, key=lambda w: (round(dtop(w) / (c.fs * 1.2)), w.get("sort_x", w["bbox"][0])))      # sort_x: a correction is read right after the word it replaces
    lines = cluster_lines(ordered, c.fs * 0.6)
    for w in words_all: w.pop("dom_bbox", None); w.pop("sort_x", None)          # only meaningful before geometry changes; do not leave stale values in the record
    out = {"composition": comp, "elements": c.els, "words_all": words_all,
           "transcript_scored": "\n".join(l["text"] for l in lines)}
    if hard:                                                      # same transcript with struck-through words shown as ~~word~~
        out["transcript_marked"] = "\n".join(" ".join(f"~~{ordered[i]['text']}~~" if ordered[i].get("struck") else ordered[i]["text"] for i in l["words"]) for l in lines)
    return img, out
