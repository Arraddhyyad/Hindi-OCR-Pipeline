# Hindi sale-deed OCR training data — synthetic document pipeline

Generates Hindi sale-deed page images **with exact ground truth** (transcript, word polygons, element boxes, damage log) for OCR training.
Language and document type live in the config (`config/hindi_sale_deed.yaml`), not in code.

## Quick start
    ./setup.sh                                   # venv, deps, Chromium, smoke test   (details below)
    python main.py generate --count 8 --run-id demo --workers 2
    python main.py sheet --run-id demo           # runs/demo/contact_sheet.png (+ _boxes.png: tracked word boxes drawn on the damaged pages)
    python main.py verify --run-id demo --repro 3           # step 7: checks every page + regenerates 3 to prove byte-identical output
    # (scoring, later:)  python main.py evaluate --run-id demo --ocr fake

System needs: Python 3.10+, Chromium (Playwright's or `CHROME_PATH`), Devanagari fonts (see `setup.sh`: Noto Serif/Sans Devanagari, Lohit, Gargi, Sarai, Nakula, Kalimati, Samanata). `python main.py info` checks them.

## The pipeline (one file per step in `pipeline/`)
| Step | File | What happens |
|---|---|---|
| 1 | `step1_entities.py` (+ `hindi_numbers.py`) | Entity graph decided in code first: parties, ages, property, boundaries, price in digits **and** Hindi words, stamp duty, witnesses, registration block. |
| 2 | `step2_text.py` | Graph → paragraphs. `TemplateWriter` (offline) or `GeminiWriter` (async, retry/backoff, cache). Every required fact is checked verbatim; Gemini output that drops one is retried with the missing facts named. |
| 3 | `step3_layout.py` | Headless Chrome renders on a fixed page size (varied per page); font size and line height are fitted so text fills 90–96.5 % of the usable area. Word and line boxes come from the browser. Header/footer/signature slots are reserved. |
| 4 | `step4_compose.py` (+ `assets.py`, `imaging.py`) | Paper, header, footer, overlapping text, stamps, signatures, thumbprints, ticks/ovals/underlines/strikes on real word boxes, margin notes, blue/black inks — from `assets/`. Multiply-blended; every element recorded with a polygon and a `scored` flag. |
| 5 | `step5_degrade.py` | **Always last.** Stains, ink blots, ink thickness, folds (always), torn edge (always), bleed-through, rotation, perspective, page bend, lighting, shadow, specks, contrast, photocopy, resample, blur, noise, JPEG. Geometry ops move every stored polygon. An aligned clean target is saved. |
| 6 | `step6_export.py` | Compact label per page, deterministic train/val/test split (hash of seed), dataset folder. |
| 7 | `step8_evaluate.py` | OCR read-back (Gemini / fake), CER, grapheme-CER, WER, token-F1, fact recall, per-severity and per-degradation breakdown, error taxonomy. |
`pipeline/orchestrator.py` runs steps 1–6 per page and saves each step; `pipeline/common.py` has config/logging; `main.py` is the CLI.

## Verification (step 7) — how you know a page is right
`python main.py verify --run-id demo [--repro N]` (or `generate --verify`) writes `runs/<id>/verify_report.md|json` and, per page, `07_verify.json` + `07_verify_overlay.png`. Exit code is non-zero if any page fails.
| check | what it proves |
|---|---|
| facts_present | every required fact (names, ages, plot, boundaries, dates, amount, witnesses...) is in the text verbatim |
| amount_words_parse | the Hindi number words in the deed are parsed **back** to a number and equal the entity amount (independent check of the number-to-words code) |
| amount_digits | the amount's digits (Indian grouping, deed numeral style) appear |
| labels_match_text | scored label words == `transcript_scored`; body words == the written paragraphs |
| fill_in_range / boxes_in_page | text fills the configured share of the page; word boxes inside the page, none overlapping |
| composition_valid | every asset used exists; every element has a polygon |
| folded_and_torn | the page has folds **and** a torn edge (spec); severity valid |
| polygons_valid | all final polygons finite, 4 points, non-degenerate |
| boxes_on_ink_target / _final | **pixel check**: in each word's own frame the ink reaches both ends of the box and sits mid-box, on the aligned clean target (strict, ≥90 %) and on the degraded image (lenient, ≥60 %, because faint/blurred pages lose ink) |
The pixel check has a **negative control**: every box is shifted by 0.4 box-heights and the same check must collapse (observed ≈0–5 % vs 95–100 % real). `tests/test_verifier.py` also breaks pages on purpose (missing fact, wrong amount, label mismatch, un-torn page, 18 px shift, untracked rotation) and confirms each is caught.
The report also lists variety (page sizes, fonts, severities, header/footer modes, stamps per page, degradation frequencies) and duplicate transcripts.

## What gets saved (everything, per step — for backtracking and logging)
    runs/<run_id>/
      config.snapshot.yaml  env.json (library versions)  run.log  manifest.jsonl  summary.json
      pages/doc_0000007/
        01_entities.json       page plan + entity graph
        02_text.json           paragraphs, transcript, writer, attempts
        03_layout.png/.json    clean fitted page, word/line boxes, slots
        04_composed.png/.json  composed page, elements + polygons, scored flags
        05_degraded.png  05_target.png  05_degraded.json   final image, aligned clean target, damage log + transformed boxes
        06_label.json          training label
        07_verify.json, 07_verify_overlay.png   per-page check results; green = scored word, orange = occluded, red = torn away, blue = stamps/marks/signatures
        steps.json             status + seconds per step (errors include traceback)
      dataset/{train,val,test}/doc_*.png|jpg, *_target.png, *.json     <- what you train on
      verify_report.md/json     contact_sheet*.png     eval/ (later)
Resume: re-running the same command skips finished pages. Redo from a step: `--seeds 7 --from-step 5` (recomputes 5–6 from the saved step-4 files; byte-identical to the original if nothing changed).

## Determinism
Page *i* depends only on `seed_base + i` (+ config + assets). Each step has its own RNG, Augraphy is seeded, and a re-run is byte-identical (tested). Python's `hash()` is never used.

## Label format (`06_label.json`)
`transcript` (reading order, scored text only), `facts`, `words[] {text, poly, visible, occluded}`, `elements[] {type, bbox, visible}`, `severity`, `ops[]`, `composition`.
`scored`: the deed's own printed text (body, title, header/footer text, signature labels). Stamps, overlap text, ticks/ovals, margin notes are **not** in the transcript.
`visible` = fraction in frame and not torn away; `occluded` = overlap with stamps/blots/overlay text.

## Config
`config/hindi_sale_deed.yaml`: page sizes, margins, fonts, ink colours, writer, fit tolerance, `compose:` probabilities, `degrade:` (severity weights, paired, use_augraphy, format png|jpg), `export:` (out_dir, split), `skip_assets: [stems]`.

## v2 config: fonts, sizes, handwriting (optional)
`python main.py generate --config config/hindi_sale_deed_v2.yaml --verify` produces pages with 20 font entries (9 system + 11 bundled Google Fonts), varied body size and line spacing, and three page styles: printed, hybrid (printed text, handwritten names/dates/amounts) and fully handwritten (35 % of pages). Body type goes up to 48 px; pages above 34 px use a short-form deed. The default config and the v1 reference config behave exactly as before; `python tests/regression_gate.py` proves it (record a baseline with `--record` on your machine first). Bundled fonts: `assets/fonts/FONTS.csv`; preview them with `python tools/font_preview.py out.png`; coverage test `python tools/font_coverage.py`. Labels of v2 pages carry `style` and per-word `hand`. Damage is staged in the v2 config (`degrade.staged`): five nested stages, one image per page by default, or an optional ladder with all five stages of a page (`ladder: {enabled: true, splits: [test]}`). Each staged page records measured text contrast, sharpness and coverage. Each v2 label also carries an easy / medium / hard `difficulty` block (provisional until calibrated: see `docs/CALIBRATION.md`, `python tools/calibrate.py`). Status: all planned parts are built; the calibration needs a Gemini run on your machine.

## Tools: what is real and what is borrowed → see `docs/TOOLS_AND_PROVENANCE.md`. Development history and bugs fixed → `DEVELOPMENT_LOG.md`.
## Known limitations
Hindi templates not proofread by a native speaker · stamps 1–4 carry 2023 dates / English text (use `skip_assets`) · one torn-edge photo (all tears share a contour) · Handwriting fonts (Kalam/Amita/Tiro) not installed — margin notes fall back to Noto Sans Devanagari · `config/hindi_sale_deed_v1_reference.yaml` reproduces the earlier 3-font results · Gemini text writer needs an async runner (`docs/GEMINI.md`) · ~6 s/page/core.
