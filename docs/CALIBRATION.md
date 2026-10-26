# Calibrating the easy / medium / hard label

Every v2 label carries `difficulty: {score, class, components, provisional}`. Until you calibrate, the weights and thresholds are guesses (`provisional: true`). Calibration measures how well a real OCR model reads pages of each difficulty and fits the numbers to that. You run the OCR step on your machine (it needs your Gemini key); everything else is offline.

## Steps (about an hour for 60 pages)

1. **Pick a model.** `export GEMINI_API_KEY=...` then `python tools/calibrate.py models` (same as `python main.py models`). Choose a model that reads images. There is no default on purpose.
2. **Make the set.** `python tools/calibrate.py make-set --run-id calib --count 60` renders 60 pages, balanced over printed / hybrid / handwritten, each at all five stages (300 images) with the clean aligned target of each page. For a full fit use 300 images or more (`--count 60` is 300 images).
3. **Run the OCR.** `python tools/calibrate.py run --run-id calib --model <name>`. It reads every image and every clean target (the clean baseline: how well the model reads the page with no damage), and stores per image: raw CER / WER / grapheme CER, the model name, the prompt hash, the page style, font, size, hand share, measured contrast / sharpness / coverage and the provisional difficulty. Results are cached, so a rerun costs nothing. Output: `runs/calib/calibration/calibration_raw.json`. **Send me this file.**
4. **Human spot check.** `python tools/calibrate.py spotcheck --run-id calib` writes contact sheets (`spotcheck_<class>_N.jpg`, 6 pages each) and `spotcheck_answers.csv` with 30 pages per class. Look at the full images in `runs/calib/dataset/` and fill column 3 with `y` or `n`: could a person who knows the script read this page? This is what keeps "hard" honest: hard for a machine, still readable by a person.
5. **Analyze.** `python tools/calibrate.py analyze --run-id calib --spot runs/calib/calibration/spotcheck_answers.csv`. Writes `calibration_report.md` and `calibrated_difficulty.yaml`.

## What the report tells you
- Clean-image baseline per style, and the **excess CER** (CER minus that baseline) so a style that is hard even when clean is not mistaken for damage.
- Median excess CER per style and stage, and whether error rises with the stage in every style.
- Fitted weights, the Spearman correlation between score and measured error, thresholds for a 20 / 40 / 40 split, and how often the score's class agrees with the class measured from the OCR.
- Stage weights that give the 20 / 40 / 40 balance, and guardrail limits (minimum text contrast, maximum covered share, minimum sharpness) taken from your human answers.

## Applying it
Copy the `difficulty:` block of `calibrated_difficulty.yaml` over the `difficulty:` block of `config/hindi_sale_deed_v2.yaml`. Copy `suggested_stage_weights` into `degrade.staged.stage_weights`, and `suggested_guardrails` into `degrade.guardrails` (this switches `enforce` on: a page past a limit is redone one stage lower, and the label records `downgraded_from`). Then regenerate; labels now say `provisional: false` and carry the model and prompt of the calibration.

## Caveats
- The class is relative to the OCR model you calibrated with. Another model may rank pages differently; the stored raw results let you redo the analysis.
- Small samples: below 300 images the fitted weights are blended with the provisional ones (the report says by how much).
- `--ocr fake` exists to test the tool offline; its numbers are not a calibration.
