"""Make the printed control: the same text as each benchmark page, set in a plain font on a white page.
No stamps, no notes, no damage. If an OCR tool scores badly here, the problem is the tool, not our page effects.

  python -m benchmark.make_control --src data/benchmark_v1/setA_standard/dataset --out data/benchmark_v1/controlA/dataset

Needs a Chromium-based browser (Edge or Chrome on Windows works). Set CHROME_PATH if it is not found."""
import argparse
import html
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PAGE_W = 1240

_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_browser():
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for c in _CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        w = shutil.which(name)
        if w:
            return w
    raise RuntimeError("No Chrome or Edge found. Install one, or set CHROME_PATH to its program file.")


def page_html(text, font_file, size):
    font_url = Path(font_file).resolve().as_uri()
    paras = "".join(f"<p>{html.escape(line)}</p>" for line in text.split("\n") if line.strip())
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>'
            f'@font-face{{font-family:Ctl;src:url("{font_url}")}}'
            f'html,body{{margin:0;background:#fff}}'
            f'body{{width:{PAGE_W}px;padding:60px;box-sizing:border-box;font-family:Ctl;font-size:{size}px;line-height:1.7;color:#111}}'
            f'p{{margin:0 0 {size * 0.5:.0f}px 0}}</style></head><body>{paras}</body></html>')


def page_height(text, size):
    chars_per_line = max(20, int((PAGE_W - 120) / (size * 0.62)))   # a little too cautious on purpose: spare white space is harmless
    lines = sum(max(1, math.ceil(len(p) / chars_per_line)) for p in text.split("\n") if p.strip())
    return int(lines * size * 1.7 + lines * 0.5 * size * 0.3 + 200)


def render_page(html_path, png_path, height, browser=None):
    browser = browser or find_browser()
    cmd = [browser, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1",
           "--default-background-color=FFFFFFFF", f"--window-size={PAGE_W},{height}",
           f"--screenshot={Path(png_path).resolve()}", Path(html_path).resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if not Path(png_path).exists():
        raise RuntimeError("browser did not write a screenshot: " + r.stderr.decode("utf-8", "replace")[-300:])


def make_control(src, out, font_file, size=26, render=render_page, limit=None):
    """For every page label in src (train/val/test) write a plain printed page and a label in out."""
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for split in ("train", "val", "test"):
            d = Path(src) / split
            if not d.is_dir():
                continue
            for lab in sorted(d.glob("doc_*.json")):
                if lab.stem.endswith("_target"):
                    continue
                if limit and n >= limit:
                    return n
                label = json.loads(lab.read_text(encoding="utf-8"))
                text = label.get("transcript", "")
                dest = Path(out) / split
                dest.mkdir(parents=True, exist_ok=True)
                hp = Path(tmp) / (lab.stem + ".html")
                hp.write_text(page_html(text, font_file, size), encoding="utf-8")
                render(hp, dest / (lab.stem + ".png"), page_height(text, size))
                (dest / (lab.stem + ".json")).write_text(json.dumps({
                    "transcript": text, "facts": label.get("facts", []),
                    "difficulty": {"class": "control"}, "stage": {"stage": 0}, "style": {"page_style": "printed"},
                    "source_page": lab.stem, "control": {"font": Path(font_file).name, "size": size},
                }, ensure_ascii=False), encoding="utf-8")
                n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="a benchmark dataset folder (has train/val/test)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--font", default="assets/fonts/hind/Hind-Regular.ttf")
    ap.add_argument("--size", type=int, default=26)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if not Path(a.font).exists():
        raise SystemExit(f"font not found: {a.font} (run from the repo folder, or pass --font)")
    n = make_control(a.src, a.out, a.font, a.size, limit=a.limit)
    print(f"wrote {n} control pages -> {a.out}")


if __name__ == "__main__":
    main()
