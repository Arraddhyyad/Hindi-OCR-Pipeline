"""STEP 3 - layout: render the text with headless Chrome on a fixed-size page, fit font size / line height so text fills 90-96.5% of the usable area, record word and line boxes.
"""
import html as _html, json, tempfile
from dataclasses import dataclass, field
from pathlib import Path
from playwright.sync_api import sync_playwright

import os
CHROME = os.environ.get("CHROME_PATH") or (("/opt/pw-browsers/chromium") if os.path.exists("/opt/pw-browsers/chromium") else None)   # None = Playwright's own Chromium


@dataclass
class PageStyle:
    width: int
    height: int
    margin_l: int = 110
    margin_r: int = 110
    margin_t: int = 60
    margin_b: int = 50
    header_h: int = 220          # reserved for header artwork (stage 2)
    footer_h: int = 200          # reserved for footer artwork (stage 2)
    sig_h: int = 130             # signature row with printed labels
    font_family: str = "Noto Serif Devanagari"
    font_file: str | None = None
    font_weight: int = 400
    ink: str = "#111111"
    align: str = "justify"
    line_height: float = 1.75
    lh_max: float = 2.15
    fs_min: float = 15.0
    fs_max: float = 40.0
    fill_lo: float = 0.90
    fill_hi: float = 0.965
    para_gap: float = 0.55       # in em
    ext: dict | None = None      # v2 extensions (font files, ...). None for v1 configs and then absent from the saved plan


@dataclass
class PageResult:
    status: str                   # ok | overflow | underfilled
    png: bytes | None
    words: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    slots: dict = field(default_factory=dict)
    font_size: float = 0.0
    line_height: float = 0.0
    fill: float = 0.0
    n_words: int = 0
    n_lines: int = 0
    font_status: list | None = None   # only filled for v2 pages: [{family, weight, status}] from document.fonts


def _esc(s):
    return _html.escape(s, quote=False)


FONT_BASE = None   # folder that the relative font paths in `ext` are resolved against (the config's assets_dir); set by PageRunner


def faces_css(faces) -> str:
    """@font-face rules for bundled font files: one rule per file, so each weight maps to its own file."""
    base = Path(FONT_BASE) if FONT_BASE else Path(__file__).resolve().parents[1] / "assets"
    return "".join(f"@font-face{{font-family:'{f['family']}';src:url('file://{(base / f['file']).resolve()}');font-weight:{f['weight']}}}" for f in faces or [])


def build_html(paras, st: PageStyle, hand=None) -> str:
    from .handwriting import word_params as word_params_
    face = ""
    if st.font_file:
        face = f"@font-face{{font-family:'{st.font_family}';src:url('file://{Path(st.font_file).resolve()}');font-weight:100 900}}"
    if st.ext:
        face += faces_css(st.ext.get("faces"))
    body = []
    gaps, hcount = [], [0]
    if hand and st.ext and st.ext.get("hand"):          # extra space before each hand word: laid out here so the fit already accounts for it
        h_ = st.ext["hand"]; gaps = [q["gap"] for q in word_params_(h_["seed"], len(hand), h_["jitter"], 1.0, h_.get("messy", 1.0))]
    for i, p in enumerate(paras):
        if hand:   # v2: words written by hand get class hw (inline-block so they can be tilted and shifted by the browser)
            toks = []
            for wi, w in enumerate(p["text"].replace("\n", " ").split()):
                if (i, wi) in hand:
                    g_ = gaps[hcount[0]]; hcount[0] += 1
                    toks.append(f'<span class="w hw" style="margin-left:{g_:.3f}em">{_esc(w)}</span>')
                else:
                    toks.append(f'<span class="w">{_esc(w)}</span>')
            words = " ".join(toks)
        else:
            words = " ".join(f'<span class="w">{_esc(w)}</span>' for w in p["text"].replace("\n", " ").split())
        body.append(f'<p class="p {p["kind"]}" data-i="{i}" data-kind="{p["kind"]}">{words}</p>')
    cw = st.width - st.margin_l - st.margin_r
    hand_css = ""
    if hand and st.ext and st.ext.get("hand"):
        h = st.ext["hand"]
        hand_css = f".hw{{display:inline-block;font-family:'{h['family']}','Noto Sans Devanagari',serif;font-weight:{h['weight']};color:{h['ink']};transform-origin:50% 50%;text-shadow:0 0 {h.get('spread', 0)}px currentColor}}\n"
        if h["mode"] == "handwritten":      # handwriting: wider word gaps, and the title underline drawn per word (a parent underline would only show in the gaps)
            hand_css += ".p{word-spacing:.16em}.title{text-decoration:none}.title .hw{text-decoration:underline;text-underline-offset:.2em}\n"
    top = st.margin_t + st.header_h
    sig_top = st.height - st.margin_b - st.footer_h - st.sig_h
    labels = ["विक्रेता", "क्रेता", "साक्षी (1)", "साक्षी (2)"]
    sig = "".join(f'<div class="sg"><div class="sl"></div><span class="w sigl">{l}</span></div>' for l in labels)
    return f"""<!doctype html><meta charset="utf-8"><style>
{face}
:root{{--fs:24px;--lh:{st.line_height};--gap:.55em}}
html,body{{margin:0;padding:0;background:#fff}}
body{{width:{st.width}px;height:{st.height}px;position:relative;overflow:hidden;
 font-family:'{st.font_family}','Noto Serif Devanagari','Noto Sans Devanagari','FreeSerif',serif;font-weight:{st.font_weight};color:{st.ink};
 font-kerning:normal;text-rendering:geometricPrecision}}
#body{{position:absolute;left:{st.margin_l}px;top:{top}px;width:{cw}px}}
.p{{margin:0 0 var(--gap) 0;font-size:var(--fs);line-height:var(--lh);text-align:{st.align};text-justify:inter-word;hyphens:none;word-spacing:0}}
.p:last-child{{margin-bottom:0}}
.title{{text-align:center;font-weight:700;font-size:1.65em;text-decoration:underline;text-underline-offset:.2em;margin-bottom:calc(var(--gap)*1.3)}}
#sig{{position:absolute;left:{st.margin_l}px;top:{sig_top}px;width:{cw}px;height:{st.sig_h}px;display:flex;justify-content:space-between;align-items:flex-end;gap:36px}}
.sg{{flex:1;text-align:center;font-size:calc(var(--fs)*.85)}}
.sl{{border-top:2px solid {st.ink};height:0;margin-bottom:6px}}
{hand_css}</style><div id="body">{''.join(body)}</div><div id="sig">{sig}</div>"""



# Tight glyph extent per word: the DOM box is the font's content area (ascent+descent), which is much taller than the ink for
# fonts like Gargi/Sarai and overlaps neighbouring lines. canvas.measureText gives the shaped word's real ink ascent/descent.
_TIGHT_JS = """(el, r) => {
  const cs = getComputedStyle(el); const c = (window.__cv = window.__cv || document.createElement('canvas')).getContext('2d');
  c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily; const m = c.measureText(el.textContent);
  const base = r.top + m.fontBoundingBoxAscent;
  return [base - m.actualBoundingBoxAscent, base + m.actualBoundingBoxDescent];
}"""

_MEASURE = """([fs, lh, gap]) => {
  const r = document.documentElement.style;
  r.setProperty('--fs', fs + 'px'); r.setProperty('--lh', lh); r.setProperty('--gap', gap + 'em');
  const b = document.getElementById('body'); const top = b.getBoundingClientRect().top;
  const ws = b.querySelectorAll('.w'); const last = ws[ws.length - 1].getBoundingClientRect();
  return last.bottom - top;
}"""

_BOXES = """() => {
  const out = []; document.querySelectorAll('.w').forEach(el => {
    const r = el.getBoundingClientRect(); const p = el.closest('.p'); const tj = (%s)(el, r);
    out.push({t: el.textContent, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom, ty0: tj[0], ty1: tj[1],
              para: p ? +p.dataset.i : -1, kind: p ? p.dataset.kind : 'sig_label'});
  }); return out; }""" % _TIGHT_JS

# v2 hand pages: like _BOXES, plus the ink's own horizontal extent (script fonts overhang the advance width) from canvas measureText
_BOXES_HAND = """() => {
  const out = []; document.querySelectorAll('.w').forEach(el => {
    const r = el.getBoundingClientRect(); const p = el.closest('.p'); const tj = (%s)(el, r);
    const cs = getComputedStyle(el); const c = (window.__cv = window.__cv || document.createElement('canvas')).getContext('2d');
    c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily; const m = c.measureText(el.textContent);
    out.push({t: el.textContent, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom, ty0: tj[0], ty1: tj[1],
              hx0: r.left - m.actualBoundingBoxLeft, hx1: r.left + m.actualBoundingBoxRight, hand: el.classList.contains('hw'),
              para: p ? +p.dataset.i : -1, kind: p ? p.dataset.kind : 'sig_label'});
  }); return out; }""" % _TIGHT_JS

_APPLY_HAND = """(list) => { const ws = document.querySelectorAll('.w');
  for (const [i, dy, ang, sc, al, sk] of list) { const e = ws[i]; e.style.transform = `translate(0px,${dy}px) rotate(${ang}deg) scale(${sc}) skewX(${sk}deg)`; e.style.opacity = al; } }"""

_SIG = """() => [...document.querySelectorAll('.sl')].map(e => {const r=e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];})"""


class Renderer:
    def __init__(self, tmp_dir: str | None = None):
        self._pw = sync_playwright().start()
        self._br = self._pw.chromium.launch(executable_path=CHROME, args=["--font-render-hinting=none"])
        self._tmp = Path(tmp_dir or tempfile.mkdtemp(prefix="docgen_"))
        self._tmp.mkdir(parents=True, exist_ok=True)

    def snippet(self, inner_html: str, font_css: str, size: float, color: str, extra_css: str = "", width: int | None = None,
                weight: int = 400, faces: str = ""):
        """Render a typed Hindi fragment on a transparent background. Returns (RGBA PIL image, word boxes relative to it)."""
        import io
        from PIL import Image
        pg = self._br.new_page(viewport={"width": 2400, "height": 1400}, device_scale_factor=1)
        try:
            w = f"width:{width}px;" if width else "display:inline-block;white-space:nowrap;"
            f = self._tmp / "snippet.html"
            f.write_text(f"""<!doctype html><meta charset="utf-8"><style>{faces}html,body{{margin:0;background:transparent}}
#s{{position:absolute;left:8px;top:8px;{w}font-family:{font_css};font-size:{size}px;font-weight:{weight};color:{color};line-height:1.45;{extra_css}}}
</style><div id="s">{inner_html}</div>""", encoding="utf-8")
            pg.goto(f"file://{f}")
            pg.evaluate("document.fonts.ready.then(()=>1)")
            r = pg.evaluate("(() => {const r=document.getElementById('s').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]})()")
            raw = pg.evaluate("(() => [...document.querySelectorAll('.w')].map(e=>{const b=e.getBoundingClientRect(); const tj=(" + _TIGHT_JS + ")(e,b); return {t:e.textContent,x0:b.left,y0:b.top,x1:b.right,y1:b.bottom,ty0:tj[0],ty1:tj[1]}}))()")
            png = pg.screenshot(omit_background=True, clip={"x": r[0], "y": r[1], "width": max(1, r[2]), "height": max(1, r[3])})
            im = Image.open(io.BytesIO(png)).convert("RGBA")
            words = [{"text": q["t"], "bbox": [round(q["x0"] - r[0], 1), round(q["ty0"] - r[1] - 1, 1), round(q["x1"] - r[0], 1), round(q["ty1"] - r[1] + 1, 1)],
                      "dom_bbox": [round(q["x0"] - r[0], 1), round(q["y0"] - r[1], 1), round(q["x1"] - r[0], 1), round(q["y1"] - r[1], 1)]} for q in raw]
            return im, words
        finally:
            pg.close()

    def close(self):
        self._br.close(); self._pw.stop()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def fit_and_render(self, paras, st: PageStyle, fs_hint: float | None = None, hand=None) -> PageResult:
        pg = self._br.new_page(viewport={"width": st.width, "height": st.height}, device_scale_factor=1)
        try:
            f = self._tmp / "page.html"
            f.write_text(build_html(paras, st, hand), encoding="utf-8")
            pg.goto(f"file://{f}")
            pg.evaluate("document.fonts.ready.then(()=>1)")
            avail = st.height - st.margin_t - st.header_h - st.margin_b - st.footer_h - st.sig_h - 24

            def m(fs, lh, gap): return pg.evaluate(_MEASURE, [fs, lh, gap])

            lh, gap = st.line_height, st.para_gap
            if m(st.fs_min, lh, gap) > avail * st.fill_hi:
                return PageResult("overflow", None, fill=m(st.fs_min, lh, gap) / avail)
            lo, hi = st.fs_min, st.fs_max                      # largest fs that still fits
            for _ in range(14):
                mid = (lo + hi) / 2
                if m(mid, lh, gap) <= avail * st.fill_hi: lo = mid
                else: hi = mid
            fs = round(lo * 4) / 4
            while m(fs, lh, gap) > avail * st.fill_hi: fs -= 0.25
            fill = m(fs, lh, gap) / avail
            if fill < st.fill_lo:                              # stretch line height and gaps
                a, b = lh, st.lh_max
                for _ in range(12):
                    mid = (a + b) / 2
                    if m(fs, mid, gap * mid / lh) <= avail * st.fill_hi: a = mid
                    else: b = mid
                lh, gap = a, gap * a / st.line_height
                fill = m(fs, lh, gap) / avail
            status = "ok" if fill >= st.fill_lo else "underfilled"
            m(fs, lh, gap)
            sig = pg.evaluate(_SIG)
            if hand:                                           # v2 hand words: jitter applied after measuring, polygons from the same numbers
                from .handwriting import word_params, word_poly, line_params
                raw = pg.evaluate(_BOXES_HAND)
                hidx = [k for k, r in enumerate(raw) if r["hand"]]
                hd = st.ext["hand"]; mess = hd.get("messy", 1.0)
                prm = dict(zip(hidx, word_params(hd["seed"], len(hidx), hd["jitter"], fs, mess)))
                for k, p_ in prm.items():                     # one wobble and tilt per written line on top of the per-word jitter
                    ldy, lang = line_params(f"{hd['seed']}|line|{raw[k]['para']}|{round(raw[k]['y0'] / 4)}", hd["jitter"], fs, mess)
                    p_["dy"] += ldy; p_["angle"] += lang
                pg.evaluate(_APPLY_HAND, [[k, p_["dy"], p_["angle"], p_["scale"], p_["alpha"], p_["skew"]] for k, p_ in prm.items()])
                png = pg.screenshot(clip={"x": 0, "y": 0, "width": st.width, "height": st.height})
                words = []
                for k, r in enumerate(raw):
                    w = {"text": r["t"], "bbox": [round(r["x0"], 1), round(r["ty0"] - 1, 1), round(r["x1"], 1), round(r["ty1"] + 1, 1)],
                         "dom_bbox": [round(r["x0"], 1), round(r["y0"], 1), round(r["x1"], 1), round(r["y1"], 1)], "para": r["para"], "kind": r["kind"]}
                    if r["hand"]:
                        poly = word_poly([r["hx0"], r["ty0"] - 1, r["hx1"], r["ty1"] + 1], w["dom_bbox"], prm[k])
                        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
                        w.update(poly=poly, bbox=[round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)], hand=True)
                    words.append(w)
            else:
                raw = pg.evaluate(_BOXES)
                png = pg.screenshot(clip={"x": 0, "y": 0, "width": st.width, "height": st.height})
                words = [{"text": r["t"], "bbox": [round(r["x0"], 1), round(r["ty0"] - 1, 1), round(r["x1"], 1), round(r["ty1"] + 1, 1)],
                          "dom_bbox": [round(r["x0"], 1), round(r["y0"], 1), round(r["x1"], 1), round(r["y1"], 1)],
                          "para": r["para"], "kind": r["kind"]} for r in raw]
            lines = cluster_lines(words, fs * lh * 0.4)
            slots = {
                "header": [0, st.margin_t, st.width, st.margin_t + st.header_h],
                "footer": [0, st.height - st.margin_b - st.footer_h, st.width, st.height - st.margin_b],
                "signature": [[round(s[0], 1), round(s[1] - 95, 1), round(s[2], 1), round(s[1] - 4, 1)] for s in sig],
                "body": [st.margin_l, st.margin_t + st.header_h, st.width - st.margin_r, st.margin_t + st.header_h + avail],
            }
            fstat = pg.evaluate("[...document.fonts].map(f=>({family:f.family.replace(/['\\\"]/g,''),weight:f.weight,status:f.status}))") if st.ext else None
            return PageResult(status, png, words, lines, slots, fs, round(lh, 3), round(fill, 3), len(words), len(lines), fstat)
        finally:
            pg.close()


def cluster_lines(words, tol):
    """Group words into lines using the stable DOM top (`dom_bbox`); the line box is the union of the tight word boxes."""
    lines, cur = [], None
    for i, w in enumerate(words):
        top = w.get("dom_bbox", w["bbox"])[1]
        if cur and cur["para"] == w.get("para", 0) and abs(top - cur["top"]) < tol:
            cur["x0"], cur["x1"] = min(cur["x0"], w["bbox"][0]), max(cur["x1"], w["bbox"][2])
            cur["y0"], cur["y1"] = min(cur["y0"], w["bbox"][1]), max(cur["y1"], w["bbox"][3]); cur["words"].append(i)
        else:
            if cur: lines.append(cur)
            cur = {"para": w.get("para", 0), "top": top, "x0": w["bbox"][0], "y0": w["bbox"][1], "x1": w["bbox"][2], "y1": w["bbox"][3], "words": [i]}
    if cur: lines.append(cur)
    for ln in lines:
        ln.pop("top"); ln["bbox"] = [round(ln.pop(k), 1) for k in ("x0", "y0", "x1", "y1")]
        ln["text"] = " ".join(words[i]["text"] for i in ln["words"])
    return lines


def wrap_words(text: str) -> str:
    return " ".join(f'<span class="w">{_esc(w)}</span>' for w in text.split())


def estimate_words(st: PageStyle, fs: float = 24.0, words_per_em: float = 2.75) -> int:
    """Rough capacity so the writer is asked for about the right length. Calibrated by fit()."""
    cw = st.width - st.margin_l - st.margin_r
    avail = st.height - st.margin_t - st.header_h - st.margin_b - st.footer_h - st.sig_h - 24
    lines = avail / (fs * st.line_height)
    return int(lines * cw / (fs * words_per_em) * 0.93)


def plan_page(cfg, rng, seed=None) -> PageStyle:
    """Sample page size, margins, font and ink colour from the config."""
    wchoice = lambda items: rng.choices(items, weights=[i["p"] for i in items])[0]
    pg, f, ink = cfg["page"], wchoice(cfg["fonts"]), wchoice(cfg["ink"])
    W, H = rng.choice(pg["sizes"])
    r = lambda k: rng.randint(*pg[k]) if isinstance(pg[k], list) else pg[k]
    st = PageStyle(W, H, r("margin_l"), r("margin_r"), r("margin_t"), r("margin_b"), r("header_h"), r("footer_h"), r("sig_h"),
                   font_family=f["family"], font_weight=f["weight"], ink=ink["color"],
                   align=rng.choices(list(cfg["align"]), weights=list(cfg["align"].values()))[0],
                   fill_lo=cfg["fit"]["fill_lo"], fill_hi=cfg["fit"]["fill_hi"])
    if f.get("files") or cfg.get("note_font_files"):        # v2 only: bundled font files, loaded with @font-face (no system install needed)
        faces = [{"family": f["family"], "weight": int(w), "file": fn} for w, fn in sorted((f.get("files") or {}).items())]
        for fam, files in (cfg.get("note_font_files") or {}).items():
            faces += [{"family": fam, "weight": int(w), "file": fn} for w, fn in sorted(files.items())]
        st.ext = {"faces": faces}
    ps = cfg.get("page_style")
    if ps:                                              # v2 only: printed / hybrid / handwritten. Own random stream again.
        import random
        hrng = random.Random(f"page_style|{seed}"); hw = cfg["handwriting"]
        mode = hrng.choices(list(ps), weights=list(ps.values()))[0]
        hf = hrng.choices(hw["fonts"], weights=[x["p"] for x in hw["fonts"]])[0]; hink = hrng.choices(hw["ink"], weights=[x["p"] for x in hw["ink"]])[0]["color"]
        ext = st.ext or {"faces": []}; ext["page_style"] = mode
        if mode != "printed":
            have = {(x["family"], x["weight"]) for x in ext["faces"]}
            ext["faces"] += [{"family": hf["family"], "weight": int(w_), "file": fn} for w_, fn in sorted(hf["files"].items()) if (hf["family"], int(w_)) not in have]
            ext["hand"] = {"family": hf["family"], "weight": hf["weight"], "ink": hink, "jitter": hw["jitter"], "seed": f"hand|{seed}", "mode": mode,
                           "messy": round(hrng.uniform(*hw.get("messy", [1.0, 1.0])), 2), "spread": round(hrng.uniform(*hw.get("ink_spread", [0.0, 0.0])), 2)}
            if mode == "handwritten":
                st.font_family, st.font_weight, st.ink, st.align = hf["family"], hf["weight"], hink, "left"     # handwriting is ragged, never justified
                ext["fs_range"] = hw.get("fs")
        st.ext = ext
    sp = cfg.get("size_plan")
    if sp:                                              # v2 only. Own random stream, so no draw of the original sampling is disturbed
        import random
        srng = random.Random(f"size_plan|{seed}")
        bands = (st.ext or {}).get("fs_range") or sp["fs"]       # handwritten pages bring their own size bands
        band = srng.choices(bands, weights=[b[2] for b in bands])[0]
        lo, hi = band[0], band[1]
        st.ext = {**(st.ext or {}), "fs_target": round(srng.uniform(lo, hi), 1)}
        st.fs_max = max(st.fs_max, max(b[1] for b in bands) + 6)                  # let the fitter reach the large bands
        if sp.get("compact_above") and st.ext["fs_target"] >= sp["compact_above"]:
            st.ext["compact"] = True                                              # short-form deed: a long text cannot be set this large on one page
        lh = band[3] if len(band) > 3 else sp.get("line_height")      # optional 4th item of a band: its own line-height range (dense small-type bands)
        if lh: st.line_height = round(srng.uniform(*lh), 3)
        hd = (cfg.get("handwriting") or {}).get("hard")          # v2 hard pages: a handwritten page in the dense small-type band gets a much untidier hand
        if hd and (st.ext or {}).get("page_style") == "handwritten" and st.ext["fs_target"] <= hd["max_fs"]:
            import random as _r
            hrng2 = _r.Random(f"hard|{seed}"); st.ext["hard"] = True
            st.ext["hand"]["messy"] = round(hrng2.uniform(*hd["messy"]), 2); st.ext["hand"]["spread"] = round(hrng2.uniform(*hd["ink_spread"]), 2)
    return st
