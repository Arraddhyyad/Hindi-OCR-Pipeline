# What each reference project contributed (honest account)

The pipeline was designed by studying four sources. Only **Augraphy** is imported as a library; the others informed the design and were **re-implemented**, not copied or called.

| Source | Used how | Where |
|---|---|---|
| **Augraphy** (library, v8.2.6) | Imported. Only pixel-level ops: InkMottling, LowInkRandomLines, BleedThrough, BadPhotoCopy, SubtleNoise, wrapped by `_aug()` (seeded, fails soft). Its geometry ops are not used because they do not track polygons. | `step5_degrade.py` |
| **indic-synthetic-docs** | Ideas only: render with a real browser for correct Devanagari shaping; word boxes from the DOM; seeded reproducibility; physical aging mindset. Code is our own (Playwright). Per-grapheme jitter is **not** implemented yet. | `step3_layout.py` |
| **Srinidhi's OCR-Research** | Ideas only: many degradation conditions, paper-occlusion, metric set (exact match, token F1, char similarity), error classification, Gemini read-back. No code imported. His `normalize()` (`[^\w\s]`) deletes Devanagari vowel signs/virama, so we wrote our own that keeps U+0900–097F. His seeding via Python `hash()` is not reproducible; ours is. | `step5_degrade.py`, `step8_evaluate.py` |
| **Aradhya's Colab notebook** | Ideas: entity graph first, Gemini writing, verbatim fact check, assets, Gemini read-back. Re-implemented as `step1_entities.py`, `step2_text.py` (GeminiWriter), `step8_evaluate.py` (GeminiOCR). | steps 1, 2, 7 |
| **Bond-paper occlusion PDF** | Informed the stain/blot/occluder design (idea only). | `step5_degrade.py` |
| IndicSQuAD | Not used (entity pools are hand-written Devanagari lists). | – |

Libraries actually imported: numpy, OpenCV, Pillow, PyYAML, Playwright (Chromium), Augraphy (+numba), rapidfuzz, google-genai (Gemini steps only).

## Bundled fonts (v2 config)

`assets/fonts/` holds 27 TrueType files from Google Fonts (SIL Open Font License 1.1, licence text kept next to each family; list in `assets/fonts/FONTS.csv`). They are loaded with `@font-face`, so nothing has to be installed on the machine. Every file passed two checks: `tools/font_coverage.py` (every character the generators can produce is in the font) and a rendered preview (`tools/font_preview.py`) inspected for broken Devanagari shaping.

Tried and rejected after the preview check: **Dekko** and **Kurale** (conjuncts such as क्ष and त्र are drawn as separate letters with a visible virama, so विक्रय reads as विकृय) and **Sarala** (ड़ is drawn like ङ). They are not bundled.
