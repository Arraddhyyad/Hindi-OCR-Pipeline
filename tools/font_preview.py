"""Render a preview sheet of every bundled font file, for a human check of Devanagari shaping.
    python tools/font_preview.py [out.png]
"""
import sys, pathlib, html
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
SAMPLE = "क्ष त्र ज्ञ श्र द्य ड़ ज़ ऑ ऋ ॐ । ०१२३४५६७८९ विक्रय विलेख ₹ 4,50,000/- श्रीमती सुनीता देवी"
files = sorted((ROOT / "assets/fonts").rglob("*.ttf"))
rows, css = [], []
for i, f in enumerate(files):
    css.append(f"@font-face{{font-family:'F{i}';src:url('{f.as_uri()}');}}")
    rows.append(f"<div class=r><span class=n>{html.escape(f.parent.name + '/' + f.name)}</span><div style=\"font-family:'F{i}';font-size:26px\">{SAMPLE}</div></div>")
page = f"<html><meta charset=utf-8><style>{''.join(css)}body{{margin:12px;width:1500px;background:#fff}}.r{{border-bottom:1px solid #ccc;padding:3px 0}}.n{{font:11px monospace;color:#555}}</style><body>{''.join(rows)}</body></html>"
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "font_preview.png")
tmp = out.with_suffix(".html"); tmp.write_text(page, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium") if pathlib.Path("/opt/pw-browsers/chromium").exists() else p.chromium.launch()
    pg = b.new_page(viewport={"width": 1530, "height": 800}); pg.goto(tmp.as_uri()); pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(500); pg.screenshot(path=str(out), full_page=True); b.close()
print("wrote", out, len(files), "fonts")
