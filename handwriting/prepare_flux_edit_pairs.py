"""Make training pairs for a "restyle" LoRA: clean printed word in, real handwriting out.

For each chosen word we write two pictures with the same file name:
  reference/NAME.png  the word drawn in a clean printed font (this is the INPUT)
  target/NAME.png     the real handwritten word from the dataset (this is the OUTPUT)
  target/NAME.txt     one fixed instruction, the same for every pair
We also write test_reference/00.png ... for 12 deed words the model has never seen.

Run (from the repo folder):
  python3 handwriting/prepare_flux_edit_pairs.py ~/Downloads/Word_Level_Hindi_Training_Set.zip \
      --out flux_data/edit_pairs --writers 3 --per-writer 40
Then zip the folder:  cd flux_data && zip -r edit_pairs.zip edit_pairs
"""
import argparse, csv, io, os, random, re, zipfile
from collections import defaultdict
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

DEV = re.compile(r"^[ऀ-ॿ]+$")
LINE = re.compile(r"^(image/\S+?\.jpg)\s*(.*)$")
INSTRUCTION = "Rewrite this printed Hindi word as real pen handwriting on white paper."
TEST_WORDS = ["घर", "पानी", "किताब", "स्कूल", "हमारा", "बहुत", "कृपया",
              "विक्रेता", "क्रेता", "रजिस्ट्री", "दस्तावेज़", "संपत्ति"]

ap = argparse.ArgumentParser()
ap.add_argument("zip")
ap.add_argument("--out", default="flux_data/edit_pairs")
ap.add_argument("--writers", type=int, default=3)
ap.add_argument("--per-writer", type=int, default=40)
ap.add_argument("--size", type=int, default=512)
ap.add_argument("--writer-ids", default="", help="comma-separated writer IDs to use (e.g. from rank_writers_by_slant.py) instead of a random pick")
ap.add_argument("--min-chars", type=int, default=2)
ap.add_argument("--max-chars", type=int, default=12)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--chromium", action="store_true", help="draw printed words with Chromium instead of Pillow")
ap.add_argument("--font", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                "..", "assets", "fonts", "hind", "Hind-Regular.ttf"))
a = ap.parse_args()
S = a.size


def flatten(im):
    """Remove the paper tint and uneven light so only ink is left on white."""
    pad = 16
    arr = np.pad(np.asarray(im, dtype=np.float32), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    big = Image.fromarray(arr.astype(np.uint8))
    bg = big.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(10))
    bg = np.asarray(bg, dtype=np.float32)[pad:-pad, pad:-pad]
    r = np.asarray(im, dtype=np.float32) / np.maximum(bg, 1.0)
    r = np.clip((r - 0.55) / 0.35, 0, 1)   # paper noise goes fully white, ink stays dark
    return Image.fromarray((r * 255).astype(np.uint8))


def tight(im, thresh=40):
    """Crop to the ink. A higher thresh ignores faint speckle (used for the photographed handwriting)."""
    box = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > thresh else 0).getbbox()
    return im.crop(box) if box else im


def fit(im):
    """Centre on a white square. Both reference and target use the same rule so they line up."""
    k = min(0.8 * S / im.width, 0.45 * S / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    canvas = Image.new("RGB", (S, S), (255, 255, 255))
    canvas.paste(im, ((S - im.width) // 2, (S - im.height) // 2))
    return canvas


# ---- clean printed word (needs correct Devanagari letter joining) ----
if features.check("raqm") and not a.chromium:
    _font = ImageFont.truetype(a.font, 220, layout_engine=ImageFont.Layout.RAQM)

    def render_word(text):
        probe = Image.new("RGB", (4000, 500), "white")
        ImageDraw.Draw(probe).text((40, 40), text, font=_font, fill="black")
        return tight(probe)
else:
    print("Pillow has no raqm text engine here; using Chromium (Playwright) to draw the printed words.")
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _br = _pw.chromium.launch()
    _pg = _br.new_page(viewport={"width": 2000, "height": 500})
    _furl = "file://" + os.path.abspath(a.font)

    def render_word(text):
        _pg.set_content(f"<style>@font-face{{font-family:H;src:url('{_furl}')}}"
                        "body{margin:0;background:#fff}"
                        f"span{{font-family:H;font-size:220px;color:#000;white-space:nowrap;display:inline-block;padding:60px 80px}}</style>"
                        f"<span id=w>{text}</span>")
        _pg.wait_for_timeout(150)
        png = _pg.locator("#w").screenshot()
        return tight(Image.open(io.BytesIO(png)).convert("RGB"))

# ---- read the dataset labels ----
z = zipfile.ZipFile(os.path.expanduser(a.zip))
label_name = next(n for n in z.namelist() if n.endswith(".txt"))
root = label_name.rsplit("/", 1)[0]
by_writer = defaultdict(list)
for raw in z.read(label_name).decode("utf8", "replace").splitlines():
    m = LINE.match(raw.strip())
    if not m:
        continue
    path, text = m.group(1), m.group(2).strip()
    if not (a.min_chars <= len(text) <= a.max_chars) or not DEV.match(text):
        continue
    by_writer[os.path.basename(path).split("_")[0]].append((path, text))

rng = random.Random(a.seed)
eligible = sorted(w for w, v in by_writer.items() if len(v) >= a.per_writer)
if a.writer_ids:
    chosen = [w.strip() for w in a.writer_ids.split(",") if w.strip() in by_writer]
    print("using the writers you named:", chosen)
else:
    chosen = rng.sample(eligible, min(a.writers, len(eligible)))
print(f"{len(by_writer)} writers usable; {len(eligible)} with >= {a.per_writer} words; using {chosen}")

for d in ("reference", "target", "test_reference"):
    os.makedirs(os.path.join(a.out, d), exist_ok=True)

rows = []
for w in chosen:
    for path, text in rng.sample(by_writer[w], min(a.per_writer, len(by_writer[w]))):
        stem = os.path.splitext(os.path.basename(path))[0]
        hand = tight(flatten(Image.open(io.BytesIO(z.read(f"{root}/{path}"))).convert("RGB")), thresh=110)
        fit(hand).save(os.path.join(a.out, "target", f"{stem}.png"))
        open(os.path.join(a.out, "target", f"{stem}.txt"), "w", encoding="utf8").write(INSTRUCTION)
        fit(render_word(text)).save(os.path.join(a.out, "reference", f"{stem}.png"))
        rows.append((stem, w, text))

for i, word in enumerate(TEST_WORDS):
    fit(render_word(word)).save(os.path.join(a.out, "test_reference", f"{i:02d}.png"))
open(os.path.join(a.out, "test_words.txt"), "w", encoding="utf8").write("\n".join(TEST_WORDS))
open(os.path.join(a.out, "instruction.txt"), "w", encoding="utf8").write(INSTRUCTION)
with open(os.path.join(a.out, "manifest.csv"), "w", encoding="utf8", newline="") as f:
    csv.writer(f).writerows([("file", "writer", "text")] + rows)
print(f"wrote {len(rows)} pairs and {len(TEST_WORDS)} test references to {a.out}")
