"""Typed-page typography variants (v3). Per page, chosen in plan_page from its own random stream (config `typography`) and saved in the page plan
as ext["typo"], so every page says which variant it uses and runs can be compared with the variant switched on and off.

  spacing   normal       the browser's normal word gaps
            uneven       ragged-left text; each word gets its own extra gap (mostly small, sometimes wide), like badly set or retyped text
            tight_messy  words pushed close together (gap shrunk to almost touching, sometimes), with small up/down shifts of single words
  font_mix  none         one size
            mixed        runs of 2-7 words set smaller (0.78-0.92) or larger (1.15-1.3) than the body
            small_only   runs of words set smaller only (0.7-0.92): a cramped, small-print look

Everything is plain CSS on the word spans, so the measured word boxes are exact and the line fit already accounts for it. Titles are left alone.
"""
import random


def choose(cfg_typo: dict, seed) -> dict:
    rng = random.Random(f"typo|{seed}")
    pick = lambda d: rng.choices(list(d), weights=list(d.values()))[0]
    return {"spacing": pick(cfg_typo.get("spacing", {"normal": 1.0})), "font_mix": pick(cfg_typo.get("font_mix", {"none": 1.0})), "seed": f"typo|{seed}"}


def word_styles(n: int, ty: dict, para_index: int, kind: str):
    """CSS text per word (or None) for one paragraph."""
    if kind == "title" or (ty["spacing"] == "normal" and ty["font_mix"] == "none"):
        return [None] * n
    rnd = random.Random(f"{ty['seed']}|{para_index}")
    sizes = [1.0] * n
    if ty["font_mix"] != "none":
        i = 0
        while i < n:
            run = rnd.randint(2, 7)
            if rnd.random() < 0.55:
                m = rnd.choice([0.78, 0.85, 0.92, 1.15, 1.3]) if ty["font_mix"] == "mixed" else rnd.choice([0.7, 0.78, 0.85, 0.92])
                for j in range(i, min(n, i + run)): sizes[j] = m
            i += run
    out = []
    for k in range(n):
        css = []
        if ty["spacing"] == "uneven":
            g = rnd.uniform(0.1, 0.7) if rnd.random() < 0.3 else rnd.gauss(0.0, 0.05)
            css.append(f"margin-left:{g:.3f}em")
        elif ty["spacing"] == "tight_messy":
            css.append(f"margin-left:{rnd.uniform(-0.2, 0.02):.3f}em"); css.append(f"position:relative;top:{rnd.uniform(-0.07, 0.07):.3f}em")
            css.append("letter-spacing:-0.015em")
        if sizes[k] != 1.0: css.append(f"font-size:{sizes[k]:.2f}em")
        out.append(";".join(css) if css else None)
    return out
