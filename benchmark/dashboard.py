"""Build the results dashboard: one web page and one GitHub-readable page, both made from the scored results.

  python -m benchmark.dashboard --results Tesseract=docs/results/tesseract_v3_results.csv --out docs/dashboard
  python -m benchmark.dashboard --results Tesseract=... --out docs/dashboard \
      --set A=data/benchmark_v1/setA_standard/dataset --set B=... --set C=... --set P=...      (also picks the sample page images)

Output folder:
  index.html      one self-contained page (for GitHub Pages or just double-click)
  README.md       the same content as Markdown, so GitHub shows it when you open the folder
  charts/*.svg    the charts
  img/*.jpg       small sample pages, and gallery.json (their captions)

Several readers: repeat --results (name=file). The first one drives the main charts, the rest are added in a comparison.
Nothing is downloaded and no web service is used, so the page works offline."""
import argparse
import csv
import html
import json
import re
from datetime import date
from pathlib import Path

from .run import FACT_KEYS, find_pages, summarize  # noqa: F401  (FACT_KEYS kept for readers of this file)

BLUE, ORANGE, GREY = "#3b6ea5", "#d98a3d", "#b7bec6"
TEXT = "#7d8590"
SVG_STYLE = (f"<style>text{{font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:{TEXT}}}"
             f".h{{font-weight:600}}.a{{fill:{BLUE}}}.b{{fill:{ORANGE}}}.c{{fill:{GREY}}}"
             f".g{{stroke:{TEXT};stroke-opacity:.25}}</style>")
INT_COLS = ("char_err", "char_len", "word_err", "word_len", "g_err", "g_len", "c_sub", "c_del", "c_ins",
            "fact_n", "fact_exact", "fact_close", "fact_num_n", "fact_num_exact", "fact_num_close")
FLOAT_COLS = ("CER", "WER", "gCER")


# ---------------------------------------------------------------- data

def load_rows(path):
    """Read a results.csv written by benchmark.run into typed rows."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for c in INT_COLS:
                r[c] = int(float(r[c]))
            for c in FLOAT_COLS:
                r[c] = float(r[c])
            rows.append(r)
    return rows


def view(rows):
    """Group a reader's rows once: view[kind][key][(set, value)] -> summary row."""
    out = {}
    for kind in sorted({r["image_kind"] for r in rows}):
        sub = [r for r in rows if r["image_kind"] == kind]
        out[kind] = {k: {(s["set"], s[k]): s for s in summarize(sub, k)} for k in ("difficulty", "stage", "style")}
    out["_pages"] = {kind: len([r for r in rows if r["image_kind"] == kind]) for kind in {r["image_kind"] for r in rows}}
    return out


def get(v, kind, key, set_, value):
    return v.get(kind, {}).get(key, {}).get((set_, value))


def per100(x):
    return None if x is None else x * 100


def fmt(x, unit=""):
    if x is None:
        return "n/a"
    return (f"{x:.1f}" if x < 10 else f"{x:.0f}") + unit


# ---------------------------------------------------------------- charts (hand-written SVG, no libraries)

def _wrap(label, width=14):
    words, lines, cur = label.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return lines[:2] if len(lines) > 2 else lines


def _nice_max(v):
    for m in (10, 20, 25, 40, 50, 60, 80, 100):
        if v <= m:
            return m
    return 100


def grouped_bars(title, cats, series, w=720, h=330):
    """Vertical bars. series = [(name, [values or None per category, in 'per 100'], css class)]."""
    left, top, bottom, right = 44, 44, 52, 14
    ymax = _nice_max(max([v for _, vals, _ in series for v in vals if v is not None] or [1]))
    pw, ph = w - left - right, h - top - bottom
    gw = pw / max(len(cats), 1)
    bw = min(46, gw * 0.8 / max(len(series), 1))
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}">',
         SVG_STYLE, f"<title>{html.escape(title)}</title>"]
    for i in range(5):
        y = top + ph - ph * i / 4
        o.append(f'<line class="g" x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        o.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{ymax * i / 4:g}</text>')
    lx = left
    for name, _, cls in series:
        o.append(f'<rect class="{cls}" x="{lx}" y="12" width="12" height="12" rx="2"/><text x="{lx + 17}" y="22">{html.escape(name)}</text>')
        lx += 30 + 6.5 * len(name)
    for ci, cat in enumerate(cats):
        cx = left + gw * ci + gw / 2
        x0 = cx - bw * len(series) / 2
        for si, (_, vals, cls) in enumerate(series):
            v = vals[ci]
            if v is None:
                continue
            bh = ph * min(v, ymax) / ymax
            x, y = x0 + si * bw, top + ph - bh
            o.append(f'<rect class="{cls}" x="{x + 2:.1f}" y="{y:.1f}" width="{bw - 4:.1f}" height="{max(bh, 0.5):.1f}" rx="2"/>')
            o.append(f'<text x="{x + bw / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle">{fmt(v)}</text>')
        for li, line in enumerate(_wrap(cat)):
            o.append(f'<text x="{cx:.1f}" y="{h - bottom + 18 + 14 * li}" text-anchor="middle">{html.escape(line)}</text>')
    o.append("</svg>")
    return "\n".join(o)


def stacked_rows(title, rows, w=720):
    """Horizontal bars, each split into 'missed' and 'extra'. rows = [(label, missed per 100, extra per 100)]."""
    left, right, rh, top = 230, 60, 34, 36
    h = top + rh * len(rows) + 10
    ymax = _nice_max(max([m + e for _, m, e in rows] or [1]))
    pw = w - left - right
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}">',
         SVG_STYLE, f"<title>{html.escape(title)}</title>",
         f'<rect class="a" x="{left}" y="10" width="12" height="12" rx="2"/><text x="{left + 17}" y="20">missed or wrong</text>',
         f'<rect class="b" x="{left + 130}" y="10" width="12" height="12" rx="2"/><text x="{left + 147}" y="20">extra (not in the answer)</text>']
    for i, (label, m, e) in enumerate(rows):
        y = top + i * rh
        wm, we = pw * m / ymax, pw * e / ymax
        o.append(f'<text x="{left - 10}" y="{y + 18}" text-anchor="end">{html.escape(label)}</text>')
        o.append(f'<rect class="a" x="{left}" y="{y + 4}" width="{max(wm, 0.5):.1f}" height="22" rx="2"/>')
        if e > 0:
            o.append(f'<rect class="b" x="{left + wm:.1f}" y="{y + 4}" width="{we:.1f}" height="22" rx="2"/>')
        o.append(f'<text x="{left + wm + we + 6:.1f}" y="{y + 20}">{fmt(m + e)}</text>')
    o.append("</svg>")
    return "\n".join(o)


# ---------------------------------------------------------------- sample page images

def _caption(label):
    st = label.get("stage") or {}
    style = (label.get("style") or {}).get("page_style", "")
    kind = {"printed": "Printed text", "hybrid": "Printed with handwritten parts", "handwritten": "Handwriting-style text"}.get(style, style)
    diff = (label.get("difficulty") or {}).get("class", "")
    return f"{kind}, damage stage {st.get('stage', '?')} ({st.get('name', '')}), rated {diff}".replace("()", "").replace(" ,", ",")


def _save_small(src, dst, width=520):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=72, optimize=True)


def build_gallery(sets, out_dir):
    """Pick a few sample pages by their labels and save small copies. sets = {'A': dir, 'B': dir, 'C': dir, 'P': dir}.
    A: one printed, one mixed, one handwriting-style page. B: one page. C: one page at every damage stage, with its clean copy.
    P: one control page. Same pick every time."""
    img_dir = Path(out_dir) / "img"
    gallery = {"ladder": [], "examples": []}
    pages = {s: [(stem, json.loads(Path(lab).read_text(encoding="utf-8")), img, clean) for stem, lab, img, clean in find_pages(d)]
             for s, d in sets.items()}

    def add(group, name, src, label):
        _save_small(src, img_dir / name)
        item = {"file": f"img/{name}", "caption": _caption(label), "stage": (label.get("stage") or {}).get("stage"),
                "name": (label.get("stage") or {}).get("name", "")}
        gallery[group].append(item)
        return item

    # damage ladder: the same page at stages 1 to 5, plus its clean copy
    bases = {}
    for stem, lab, img, clean in pages.get("C", []):
        bases.setdefault(stem.rsplit("_s", 1)[0], []).append((lab["stage"]["stage"], stem, lab, img, clean))
    full = [(b, sorted(v, key=lambda t: t[0])) for b, v in sorted(bases.items()) if len(v) >= 3]
    full.sort(key=lambda t: (t[1][0][2]["style"]["page_style"] != "printed", t[0]))
    if full:
        base, items = full[0]
        first = items[0]
        if first[4]:
            _save_small(first[4], img_dir / "ladder_clean.jpg")
            gallery["ladder"].append({"file": "img/ladder_clean.jpg", "caption": "Before any damage (clean copy)", "stage": 0, "name": "clean"})
        for st, stem, lab, img, clean in items:
            item = add("ladder", f"ladder_{st}.jpg", img, lab)
            item["caption"] = f"Stage {st}: {lab['stage'].get('name', '')}"

    def first_with(s, style):
        c = sorted([p for p in pages.get(s, []) if p[1].get("style", {}).get("page_style") == style],
                   key=lambda p: (abs((p[1].get("stage") or {}).get("stage", 3) - 3), p[0]))
        return c[0] if c else None

    for s, style, name in (("A", "printed", "ex_printed.jpg"), ("A", "hybrid", "ex_mixed.jpg"), ("A", "handwritten", "ex_handwritten.jpg")):
        p = first_with(s, style)
        if p:
            add("examples", name, p[2], p[1])
    for s, name in (("B", "ex_setB.jpg"), ("P", "ex_control.jpg")):
        if pages.get(s):
            p = sorted(pages[s], key=lambda t: t[0])[0]
            item = add("examples", name, p[2], p[1])
            item["caption"] = ("Hard handwriting set: " + item["caption"]) if s == "B" else "Printed control: the same text, plain printed, nothing damaged"
    (img_dir / "gallery.json").write_text(json.dumps(gallery, indent=1, ensure_ascii=False), encoding="utf-8")
    return gallery


def load_gallery(out_dir):
    p = Path(out_dir) / "img" / "gallery.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"ladder": [], "examples": []}


# ---------------------------------------------------------------- the story (shared by the web page and the Markdown page)

def story(readers, gallery, today=None):
    """Return the page as a list of blocks. readers = [(name, rows)]."""
    name, rows = readers[0]
    v = view(rows)
    dmg, cln = "damaged", "clean"
    has_clean = cln in v
    n_pages = len({(r["set"], r["page"]) for r in rows})
    blocks = []

    def m(kind, key, s, val):
        r = get(v, kind, key, s, val)
        return None if r is None else per100(r["missed"])

    def e(kind, key, s, val):
        r = get(v, kind, key, s, val)
        return None if r is None else per100(r["extra"])

    def fct(kind, key, s, val, field="facts"):
        r = get(v, kind, key, s, val)
        return None if r is None or r[field] is None else per100(r[field])

    ctl = get(v, dmg, "difficulty", "P", "control")

    # ---- title and short version
    blocks.append(("title", "How well can a computer read our fake Hindi deeds?",
                   f"Reader tested: {name}. {n_pages} pages scored. Page file made {today or date.today().isoformat()}."))
    tiles = []
    if ctl:
        tiles.append((fmt(per100(ctl["missed"])), "Clean printed copy",
                      f"letters wrong or missed out of 100. {fmt(per100(ctl['facts']), '%')} of key facts found."))
    for d, lab in (("easy", "Easy damaged pages"), ("medium", "Medium damaged pages"), ("hard", "Hard damaged pages")):
        r = get(v, dmg, "difficulty", "A", d)
        if r:
            tiles.append((fmt(per100(r["missed"])), lab, f"letters wrong or missed out of 100. {fmt(per100(r['facts']), '%')} of key facts found."))
    if tiles:
        blocks.append(("tiles", tiles))
    blocks.append(("p", "We made fake Hindi sale deeds where we know every name, date and amount. We damaged them step by step, "
                        "then asked a free reading program to read each page and checked its answer against what we know is written."))

    # ---- what stands out (every sentence is computed from the results file)
    notes = []
    a = [m(dmg, "difficulty", "A", d) for d in ("easy", "medium", "hard")]
    if None not in a:
        notes.append(f"**The harder the page, the more the reader misses.** Out of 100 letters it gets wrong or loses {fmt(a[0])} on easy pages, "
                     f"{fmt(a[1])} on medium and {fmt(a[2])} on hard.")
    if has_clean and None not in (m(cln, "difficulty", "A", "hard"), a[2]):
        diff = a[2] - m(cln, "difficulty", "A", "hard")
        notes.append(f"**Damage is a big part of it.** The same hard pages without any damage lose {fmt(m(cln, 'difficulty', 'A', 'hard'))} out of 100, "
                     f"so the damage adds about {fmt(diff)}.")
    ph = m(dmg, "style", "A", "printed"), m(dmg, "style", "A", "handwritten")
    if None not in ph:
        notes.append(f"**Handwriting-style text is harder than printed text.** {fmt(ph[1])} out of 100 lost on handwriting-style pages, "
                     f"against {fmt(ph[0])} on printed ones.")
    b = get(v, dmg, "difficulty", "B", "hard")
    if b:
        verdict = "is close to unreadable for this reader" if b["facts"] is not None and b["facts"] < 0.1 else "is the hardest group for this reader"
        notes.append(f"**Our hardest handwriting set {verdict}.** It finds {fmt(per100(b['facts']), '%')} of the key facts "
                     f"and {fmt(per100(b['failed']), '%')} of the pages count as failed.")
    if ctl and ctl["numbers"] is not None and ctl["facts"] is not None and ctl["numbers"] < ctl["facts"]:
        notes.append(f"**Numbers are the weak spot.** Even on the clean printed copy only {fmt(per100(ctl['numbers']), '%')} of numbers are read exactly, "
                     f"against {fmt(per100(ctl['facts']), '%')} for all facts, because single digits slip.")
    pe = e(cln if has_clean else dmg, "style", "A", "printed")
    pm = m(cln if has_clean else dmg, "style", "A", "printed")
    if pe is not None and pm is not None and pe > 0.5 * pm:
        notes.append(f"**Part of the error is not the reader's fault.** On printed pages, {fmt(pe)} of every {fmt(pe + pm)} counted errors are extra text "
                     "(stamps, notes and header art the reader sees but our answer does not list).")
    if notes:
        blocks.append(("h2", "What stands out"))
        blocks.append(("list", notes))

    # ---- flow
    stage_names = {str(g.get("stage")): g.get("name") for g in gallery.get("ladder", []) if g.get("stage") not in (None, 0)}
    stage_txt = ("From light to severe: " + ", ".join(f"{k} {stage_names[k]}" for k in sorted(stage_names)) + ".") if len(stage_names) >= 3 else \
        "Stage 1 is light scan wear and stage 5 is severe."
    blocks.append(("h2", "What we did, and why"))
    blocks.append(("steps", [
        ("Write fake deeds", "We decide every name, date, place and amount first, then write the deed text from them.",
         "So we always know the right answer for every page."),
        ("Draw the pages", "Each deed is drawn like a real page: fonts, headers, stamps, signatures, thumbprints, margin notes, some handwriting-style text.",
         "Real deeds are messy, and a reader trained or tested on neat pages will not cope with them."),
        ("Damage them in 5 steps", "Folds, tears, blur, ink marks, scan noise, increasing from stage 1 to stage 5. " + stage_txt,
         "We want to know at which point a reader breaks, so the damage grows in steps."),
        ("Label each page easy, medium or hard", "A score from how much of the text is covered, how faint it is, and how much is handwriting or small print.",
         "So we can say how bad a page is without running a reader. The label is a first version and still needs checking against real pages."),
        ("Make a clean printed copy as a control", "The same text in a plain printed font on a white page, nothing damaged.",
         "It shows how good the reader is when the page is fine. Any drop on our pages is then due to the pages, not the reader."),
        ("Let the reader read every page", f"{name} reads each page and we compare its text with the answer, letter by letter and fact by fact.",
         "The same cleaning and the same rules apply to every reader, so results can be compared."),
        ("Group the results", "By how hard the page is, damage stage and kind of text. Also a clean copy of each page, to separate damage from everything else.",
         "To see what makes pages hard, not only how hard they are."),
    ]))

    # ---- sample pages
    if gallery.get("ladder"):
        blocks.append(("h2", "What the pages look like"))
        blocks.append(("p", "The same page, from clean to severe damage."))
        blocks.append(("images", [(g["file"], g["caption"]) for g in gallery["ladder"]]))
    if gallery.get("examples"):
        blocks.append(("p", "Other kinds of page we test on."))
        blocks.append(("images", [(g["file"], g["caption"]) for g in gallery["examples"]]))

    # ---- results
    blocks.append(("h2", "Results"))
    blocks.append(("terms", [
        ("Wrong or missed letters", "letters in the answer that the reader got wrong or left out, per 100 letters of the answer. Lower is better."),
        ("Extra letters", "text the reader wrote that is not in the answer. On our pages it is mostly stamps and notes."),
        ("Key facts found", "names, places, dates and amounts from the answer that appear exactly in the reader's text."),
        ("Failed page", "more than half of the letters wrong."),
    ]))
    charts = []
    rows1 = []
    if ctl:
        rows1.append(("Clean printed copy", per100(ctl["missed"]), per100(ctl["extra"])))
    for d in ("easy", "medium", "hard"):
        r = get(v, dmg, "difficulty", "A", d)
        if r:
            rows1.append((f"Damaged pages, {d}", per100(r["missed"]), per100(r["extra"])))
    r = get(v, dmg, "difficulty", "B", "hard")
    if r:
        rows1.append(("Hard handwriting set", per100(r["missed"]), per100(r["extra"])))
    if rows1:
        charts.append(("chart_difficulty.svg", stacked_rows("Letters wrong per 100, by kind of page", rows1),
                       "How many letters go wrong, by kind of page",
                       "Each bar is the number of letters out of 100 that the reader got wrong, lost, or added."))
    stages = [s for s in ("1", "2", "3", "4", "5") if get(v, dmg, "stage", "A", s)]
    if stages:
        series = [("Damaged page", [m(dmg, "stage", "A", s) for s in stages], "a")]
        if has_clean:
            series.insert(0, ("Same pages, no damage", [m(cln, "stage", "A", s) for s in stages], "c"))
        charts.append(("chart_stage.svg", grouped_bars("Letters missed per 100, by damage stage", [f"Stage {s}" for s in stages], series),
                       "Letters missed, by damage stage",
                       "More damage means more missed letters. The grey bars show the same pages without damage, so the gap is what damage costs."))
    styles = [s for s in ("printed", "hybrid", "handwritten") if get(v, dmg, "style", "A", s)]
    if styles:
        lab = {"printed": "Printed", "hybrid": "Mixed", "handwritten": "Handwriting-style"}
        series = [("Damaged page", [m(dmg, "style", "A", s) for s in styles], "a")]
        if has_clean:
            series.insert(0, ("Same pages, no damage", [m(cln, "style", "A", s) for s in styles], "c"))
        charts.append(("chart_style.svg", grouped_bars("Letters missed per 100, by kind of text", [lab[s] for s in styles], series),
                       "Letters missed, by kind of text", "Printed text is easiest. Handwriting-style text is hardest, even before damage."))
    cats, f_all, f_num = [], [], []
    for lbl, s, val in (("Clean printed copy", "P", "control"), ("Easy", "A", "easy"), ("Medium", "A", "medium"), ("Hard", "A", "hard"),
                        ("Hard handwriting set", "B", "hard")):
        if get(v, dmg, "difficulty", s, val):
            cats.append(lbl)
            f_all.append(fct(dmg, "difficulty", s, val, "facts"))
            f_num.append(fct(dmg, "difficulty", s, val, "numbers"))
    if cats:
        charts.append(("chart_facts.svg", grouped_bars("Key facts found, out of 100", cats,
                                                       [("All key facts", f_all, "a"), ("Numbers only", f_num, "b")]),
                       "Key facts found", "This is what matters for a deed: who sold what to whom, and for how much. Numbers are the hardest part."))
    fails = [("Easy", "A", "easy"), ("Medium", "A", "medium"), ("Hard", "A", "hard"), ("Hard handwriting set", "B", "hard")]
    fails = [(l, per100(get(v, dmg, "difficulty", s, val)["failed"])) for l, s, val in fails if get(v, dmg, "difficulty", s, val)]
    if fails:
        charts.append(("chart_failed.svg", grouped_bars("Failed pages, out of 100", [f[0] for f in fails], [("Failed pages", [f[1] for f in fails], "a")]),
                       "Share of failed pages", "A page fails when more than half of its letters are wrong."))
    if len(readers) > 1:
        cats = [("Easy", "easy"), ("Medium", "medium"), ("Hard", "hard")]
        series = []
        for i, (rn, rr) in enumerate(readers):
            vv = view(rr)
            series.append((rn, [(None if not get(vv, dmg, "difficulty", "A", d) else per100(get(vv, dmg, "difficulty", "A", d)["missed"]))
                                for _, d in cats], ["a", "b", "c"][i % 3]))
        charts.append(("chart_readers.svg", grouped_bars("Letters missed per 100, by reader", [c for c, _ in cats], series),
                       "Readers compared", "The same damaged pages, read by each reader."))
    for fname, svg, alt, caption in charts:
        blocks.append(("chart", fname, svg, alt, caption))

    # ---- table
    head = ["Group", "Pages", "Letters missed per 100", "Extra per 100", "Key facts found", "Numbers found", "Failed pages"]
    trs = []
    for kind in (dmg, cln):
        if kind not in v:
            continue
        for key in ("difficulty", "style", "stage"):
            for (s, val), r in sorted(v[kind][key].items()):
                trs.append([f"{'Damaged' if kind == dmg else 'Clean copy'}, set {s}, {key} {val}", str(r["pages"]), fmt(per100(r["missed"])),
                            fmt(per100(r["extra"])), fmt(per100(r["facts"]), "%"), fmt(per100(r["numbers"]), "%"), fmt(per100(r["failed"]), "%")])
    blocks.append(("details", "All the numbers", [("table", head, trs)]))

    # ---- why this reader
    blocks.append(("h2", "Why Tesseract as the first reader"))
    blocks.append(("list", [
        "It is free, runs on a normal laptop, and has a Hindi language file, so anyone on the team can repeat the test.",
        "It is the usual starting point for OCR, so the numbers mean something to other people.",
        "It reads text only, with no AI guessing missing words, so its mistakes show what the page itself does to a reader.",
        "It is a starting point, not the best reader. A second reader and an AI model that reads whole pages are set up in the code but not run yet.",
    ]))

    blocks.append(("foot", "How scores are worked out: docs/SCORING.md. Raw numbers: docs/results/. This page was made by python -m benchmark.dashboard."))
    return blocks


# ---------------------------------------------------------------- renderers

def _inline_html(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


CSS = """
:root{--bg:#fff;--fg:#1f2328;--mut:#59636e;--line:#d1d9e0;--card:#f6f8fa;--acc:#3b6ea5}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#30363d;--card:#151b23;--acc:#7aa7d6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px}h2{font-size:21px;margin:44px 0 12px}
.sub{color:var(--mut);margin:0 0 20px;font-size:14px}p{margin:10px 0}li{margin:8px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:34px;line-height:1.1;color:var(--acc)}.tile span{font-weight:600}.tile small{display:block;color:var(--mut);margin-top:4px}
.step{display:grid;grid-template-columns:34px 1fr;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.num{width:30px;height:30px;border-radius:50%;background:var(--acc);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600}
.step h3{margin:0 0 2px;font-size:16px}.step p{margin:2px 0}.why{color:var(--mut)}
figure{margin:20px 0}figcaption{color:var(--mut);font-size:14px}svg{width:100%;height:auto;display:block}
.imgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin:12px 0}
.imgs figure{margin:0}.imgs img{width:100%;border:1px solid var(--line);border-radius:6px;display:block}.imgs figcaption{margin-top:4px;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
th{color:var(--mut);font-weight:600}details{margin:16px 0}summary{cursor:pointer;font-weight:600}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:10px 0}dt{font-weight:600}dd{margin:0;color:var(--mut)}
.paper{border-left:3px solid var(--acc);padding:2px 0 2px 14px;margin:14px 0}.paper a{font-weight:600;color:var(--acc)}
.foot{color:var(--mut);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:12px}
"""


def render_html(blocks):
    o = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
         "<title>Hindi OCR benchmark</title>", f"<style>{CSS}</style></head><body><main>"]

    def one(b):
        k = b[0]
        if k == "title":
            o.append(f"<h1>{html.escape(b[1])}</h1><p class=\"sub\">{html.escape(b[2])}</p>")
        elif k == "h2":
            o.append(f"<h2>{html.escape(b[1])}</h2>")
        elif k == "p":
            o.append(f"<p>{_inline_html(b[1])}</p>")
        elif k == "list":
            o.append("<ul>" + "".join(f"<li>{_inline_html(t)}</li>" for t in b[1]) + "</ul>")
        elif k == "tiles":
            o.append("<div class=\"tiles\">" + "".join(
                f"<div class=\"tile\"><b>{html.escape(a)}</b><span>{html.escape(l)}</span><small>{html.escape(s)}</small></div>" for a, l, s in b[1]) + "</div>")
        elif k == "steps":
            for i, (t, what, why) in enumerate(b[1], 1):
                o.append(f"<div class=\"step\"><div class=\"num\">{i}</div><div><h3>{html.escape(t)}</h3><p>{html.escape(what)}</p>"
                         f"<p class=\"why\">Why: {html.escape(why)}</p></div></div>")
        elif k == "chart":
            o.append(f"<figure>{b[2]}<figcaption>{html.escape(b[4])}</figcaption></figure>")
        elif k == "images":
            o.append("<div class=\"imgs\">" + "".join(
                f"<figure><img src=\"{html.escape(f)}\" alt=\"{html.escape(c)}\" loading=\"lazy\"><figcaption>{html.escape(c)}</figcaption></figure>"
                for f, c in b[1]) + "</div>")
        elif k == "terms":
            o.append("<dl>" + "".join(f"<dt>{html.escape(t)}</dt><dd>{html.escape(d)}</dd>" for t, d in b[1]) + "</dl>")
        elif k == "table":
            o.append("<table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in b[1]) + "</tr></thead><tbody>" +
                     "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in b[2]) + "</tbody></table>")
        elif k == "details":
            o.append(f"<details><summary>{html.escape(b[1])}</summary>")
            for x in b[2]:
                one(x)
            o.append("</details>")
        elif k == "foot":
            o.append(f"<p class=\"foot\">{html.escape(b[1])}</p>")

    for b in blocks:
        one(b)
    o.append("</main></body></html>")
    return "\n".join(o)


def render_md(blocks):
    out = []
    for b in blocks:
        k = b[0]
        if k == "title":
            out += [f"# {b[1]}", "", f"*{b[2]}*", ""]
        elif k == "h2":
            out += [f"## {b[1]}", ""]
        elif k == "p":
            out += [b[1], ""]
        elif k == "list":
            out += [f"- {t}" for t in b[1]] + [""]
        elif k == "tiles":
            out += ["| " + " | ".join(l for _, l, _ in b[1]) + " |", "|" + "---|" * len(b[1]),
                    "| " + " | ".join(f"**{a}**" for a, _, _ in b[1]) + " |",
                    "| " + " | ".join(s for _, _, s in b[1]) + " |", ""]
        elif k == "steps":
            for i, (t, what, why) in enumerate(b[1], 1):
                out += [f"**{i}. {t}.** {what}  ", f"*Why: {why}*", ""]
        elif k == "chart":
            out += [f"![{b[3]}](charts/{b[1]})", "", f"*{b[4]}*", ""]
        elif k == "images":
            for i in range(0, len(b[1]), 3):
                chunk = b[1][i:i + 3]
                out += ["| " + " | ".join(f"![{c}]({f})" for f, c in chunk) + " |", "|" + "---|" * len(chunk),
                        "| " + " | ".join(c for _, c in chunk) + " |", ""]
        elif k == "terms":
            out += [f"- **{t}**: {d}" for t, d in b[1]] + [""]
        elif k == "table":
            out += ["| " + " | ".join(b[1]) + " |", "|" + "---|" * len(b[1])] + ["| " + " | ".join(r) + " |" for r in b[2]] + [""]
        elif k == "details":
            out += [f"<details><summary>{b[1]}</summary>", ""]
            out += render_md(b[2]).splitlines() + ["", "</details>", ""]
        elif k == "foot":
            out += ["---", f"*{b[1]}*", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- build + CLI

def build(readers, out_dir, gallery=None, today=None):
    """readers = [(name, rows)]. Writes index.html, README.md and charts/ into out_dir."""
    out = Path(out_dir)
    (out / "charts").mkdir(parents=True, exist_ok=True)
    gallery = gallery if gallery is not None else load_gallery(out)
    blocks = story(readers, gallery, today)
    for b in blocks:
        if b[0] == "chart":
            (out / "charts" / b[1]).write_text(b[2], encoding="utf-8")
    # in the web page the charts sit inline; in the Markdown page they are files
    (out / "index.html").write_text(render_html(blocks), encoding="utf-8")
    (out / "README.md").write_text(render_md(blocks), encoding="utf-8")
    return blocks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", action="append", required=True, metavar="NAME=results.csv")
    ap.add_argument("--out", default="docs/dashboard")
    ap.add_argument("--set", action="append", default=[], metavar="A=DATASET_DIR",
                    help="dataset folders (A, B, C, P) to pick the sample pages from; leave out to keep the pictures already there")
    a = ap.parse_args(argv)
    readers = []
    for item in a.results:
        name, _, path = item.partition("=")
        readers.append((name, load_rows(path)))
    if a.set:
        build_gallery(dict(s.split("=", 1) for s in a.set), a.out)
    build(readers, a.out)
    print(f"dashboard written to {a.out} (open {Path(a.out) / 'index.html'})")


if __name__ == "__main__":
    main()
