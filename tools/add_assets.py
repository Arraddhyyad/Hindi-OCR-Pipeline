#!/usr/bin/env python3
"""Register new asset files in assets/manifest.csv (idempotent: files already listed are left alone).

  python tools/add_assets.py                 # scan assets/ and append rows for files that are not in the manifest yet
  python tools/add_assets.py --era v3        # era label written to new rows (older configs ignore non-empty eras)

Background rule per folder:  png with transparency -> alpha | jpg in stains_and_damage, blots -> white (white becomes transparent)
                             jpg in paper, torn_edges -> opaque | jpg in tape -> black (clear tape photographed on black)
"""
import argparse, csv, json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "assets"
FIELDS = ["file", "category", "width", "height", "background", "content_fraction", "content_bbox", "mean_colour_rgb", "lang", "era", "notes"]
NOTES = {
    "header_02_seal_rule_squiggle": "contains pseudo-text (non-Hindi letters); listed in skip_assets of the v3 config",
    "header_05_emblem_rule_text": "contains pseudo-Devanagari text; listed in skip_assets of the v3 config",
    "header_07_stamp_paper_pink": "contains small pseudo-text in the ribbons",
    "paper": "aged paper photo with a plain surround; the surround is cropped at load time",
    "torn_edges": "page photographed on black; black = outside the page; used as a 1-D tear profile",
    "tape_clear": "clear tape on black: R = shiny highlight, alpha = tape outline; composited with screen + haze",
    "tape_old": "aged tape cut-out; multiplied with the page and lowers text contrast underneath",
    "stains": "stain on white; white -> alpha, multiply-blended",
    "damage": "burnt holes on white; not used by default",
}
SKIP_SUFFIX = ("_rgba",)          # derived files, not assets in their own right


def background_of(cat, path, im):
    if cat == "tape":
        return "black" if path.suffix.lower() in (".jpg", ".jpeg") else "alpha"
    if cat in ("paper", "torn_edges", "creases"):
        return "opaque"
    if im.mode == "RGBA" and np.asarray(im)[..., 3].min() < 250:
        return "alpha"
    return "white"


def row_for(path: Path, era: str):
    cat = path.parent.name
    im = Image.open(path)
    bg = background_of(cat, path, im)
    rgb = im.convert("RGB"); a = np.asarray(rgb)
    if bg == "alpha":
        al = np.asarray(im.convert("RGBA"))[..., 3] > 40
    elif bg == "white":
        al = a.min(axis=2) < 235
    elif bg == "black":
        al = a.max(axis=2) > 28
    else:
        al = np.ones(a.shape[:2], bool)
    ys, xs = np.where(al)
    bbox = f"{xs.min()},{ys.min()},{xs.max()},{ys.max()}" if len(xs) else ""
    mean = [int(v) for v in a[al].mean(axis=0)] if al.any() else [0, 0, 0]
    stem = path.stem
    note = NOTES.get(stem) or (NOTES["tape_clear"] if cat == "tape" and bg == "black" else NOTES["tape_old"] if cat == "tape" else
                                NOTES["damage"] if stem.startswith("damage") else NOTES["stains"] if cat == "stains_and_damage" else NOTES.get(cat, ""))
    return {"file": f"{cat}/{path.name}", "category": cat, "width": im.width, "height": im.height, "background": bg,
            "content_fraction": round(float(al.mean()), 3), "content_bbox": bbox, "mean_colour_rgb": json.dumps(mean), "lang": "", "era": era, "notes": note}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--era", default="v3"); a = ap.parse_args()
    mf = ROOT / "manifest.csv"
    rows = list(csv.DictReader(open(mf, encoding="utf-8")))
    have = {r["file"] for r in rows}
    new = []
    for p in sorted(ROOT.glob("*/*")):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg") or p.parent.name in ("fonts", "text"):
            continue
        if p.stem.endswith(SKIP_SUFFIX) or f"{p.parent.name}/{p.name}" in have:
            continue
        new.append(row_for(p, a.era))
    if not new:
        print("manifest already up to date"); return
    with open(mf, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); [w.writerow(r) for r in new]
    print(f"added {len(new)} rows")
    for r in new: print(" ", r["file"], r["background"])


if __name__ == "__main__":
    main()
