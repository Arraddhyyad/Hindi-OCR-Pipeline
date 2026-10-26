"""Glyph-coverage test for fonts in assets/fonts: every character the pipeline can print must exist in the font's cmap.
Collects the character set from the real generators (template writer over many seeds, header/footer/stamp/note strings),
so it follows the code instead of a hand-written list.

    python tools/font_coverage.py [--seeds 400] [--json out.json]
Exit code 1 if any font misses characters (shaping / conjunct forms still need the preview sheet: tools/font_preview.py).
"""
import argparse, json, pathlib, random, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fontTools.ttLib import TTFont
from pipeline.common import load_config
from pipeline.step1_entities import generate_entity_graph
from pipeline.step2_text import TemplateWriter
from pipeline.step4_compose import NOTE_WORDS


def needed_chars(n_seeds: int, cfg_path: str) -> set:
    cfg = load_config(cfg_path); chars = set()
    for s in range(n_seeds):
        rng = random.Random(s); g = generate_entity_graph(rng, cfg)
        d = TemplateWriter().write(g, random.Random(s * 31 + 1), 400)
        chars |= set(d.text)
        for k in ("date", "place", "district", "tehsil", "village", "amount_text", "amount_words", "payment", "stamp_duty"):
            chars |= set(str(g[k]))
        r = g["registration"]; chars |= set("".join(str(v) for v in r.values()))
    fixed = ["विक्रेता", "क्रेता", "साक्षी (1)", "साक्षी (2)", "पंजीकरण संख्या: ", "दिनांक: ", "उत्तर प्रदेश शासन", "उप-निबंधक कार्यालय, ",
             "बही संख्या जिल्द संख्या पृष्ठ संख्या", "आज दिनांक को प्रस्तुत एवं पंजीकृत किया गया। उप-निबंधक", "पंजीकृत", "स्टाम्प शुल्क अदा किया गया",
             "रुपये", "प्रमाणित प्रतिलिपि", "अभिलेख कक्ष", "0123456789०१२३४५६७८९", "“”()/-.,;:।॥"] + NOTE_WORDS
    for f in fixed:
        chars |= set(f)
    chars -= set(" \n\t‌‍")           # joiners are control characters, not glyphs
    return chars


def cmap_of(path: pathlib.Path) -> set:
    return set(TTFont(str(path), lazy=True).getBestCmap())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--seeds", type=int, default=400); ap.add_argument("--json")
    ap.add_argument("--config", default=str(ROOT / "config/hindi_sale_deed.yaml")); a = ap.parse_args()
    need = needed_chars(a.seeds, a.config); print(f"{len(need)} distinct characters needed: " + "".join(sorted(need)))
    rep, bad = {}, 0
    for ttf in sorted((ROOT / "assets/fonts").rglob("*.ttf")):
        miss = sorted(c for c in need if ord(c) not in cmap_of(ttf))
        rep[ttf.relative_to(ROOT / "assets/fonts").as_posix()] = miss
        print(("OK   " if not miss else "MISS ") + ttf.relative_to(ROOT / "assets/fonts").as_posix() + ("" if not miss else "  missing: " + " ".join(f"{c}(U+{ord(c):04X})" for c in miss)))
        bad += bool(miss)
    if a.json: pathlib.Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if bad else 0)
