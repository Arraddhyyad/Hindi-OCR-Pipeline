# Hard pages

Config: `config/hindi_sale_deed_v2_hard.yaml` (built on `hindi_sale_deed_v2_hand8.yaml`). Every other config behaves exactly as before; the regression gate proves it.

A **hard page** is a fully handwritten page that falls in the dense small-type band (`handwriting.fs`, first band, 20% of handwritten pages). The page is marked `ext.hard` in step 3 and every later step reads that flag. Nothing below runs on other pages.

## What a hard page gets

| Step | What | Where in the code |
|---|---|---|
| 3 layout | Dense, small type (about 16 to 23 px, line height 1.25 to 1.40), the full-length deed (about 470 words). A much untidier hand (messy 2.2 to 3.0 instead of 0.7 to 1.9, more ink spread). | `step3_layout.py` (band line height, `handwriting.hard`) |
| 4 compose | Pen pressure per word, words bent slightly, smudges, a block of words in a second pen. A few words struck through with a wavy line, most of them with a correction written above. More marks, margin notes, stamps and overlapping text. Signatures scrawled across the text. | `hard_effects.py` (`messy_text`, `add_corrections`, `add_signatures_over_text`), `compose.hard` in the config |
| 5 degrade | Only the two severe damage stages (4 and 5). Patchy ink fade, writing on the back showing through, ink cracked along the real fold lines, a photocopy look. Ring stains, low-ink streaks and bleed-through are likelier. Blur and resolution loss are weaker (`soft_scale`) so small text stays recoverable. BadPhotoCopy is not used (it is not repeatable). | `hard_effects.py`, `step5_degrade.py`, `degrade.hard` and `degrade.staged.hard_stage_weights` |
| 5 degrade, sometimes | Phone photo (chance `degrade.hard.photo.p`, 0.4): paper curl, camera angle, hand shadow, a thumb at one edge, soft focus on one side, sensor grain. The word polygons and the clean target move with the pixels. The thumb is an element (`finger`), so words under it count as occluded. | `hard_effects.phone_photo` |
| 6 label | `struck: true` on struck words, `correction: true` on words written above them, and `transcript_marked` (struck words shown as `~~word~~`). | `step6_export.py` |
| difficulty | Three extra parts: corrections, density, photo. Version 2, weights re-balanced. Older configs do not list these parts, so they score exactly as before. | `difficulty.py` |

## Strike-through and the transcript

A struck word stays in the transcript. The word is flagged `struck`, and `transcript_marked` shows it as `~~word~~`. The correction is written above it and is a normal scored word of kind `correction`; it is read straight after the word it replaces. `transcript_marked` with `~~` removed equals `transcript_scored`, which is what step 7 compares to the label words.

## Randomness

Each effect uses its own generator built from the page seed (`hardfx|<seed>`, `hard|<seed>`, and one per damage op), so a page is reproducible and adding an effect does not disturb any other draw.

## Settings (all in the hard config)

- `handwriting.fs` (first band is the dense one), `handwriting.hard` (`max_fs`, `messy`, `ink_spread`)
- `compose.hard` (`pressure`, `smudge`, `strike`, `second_pen`, `sig_over`, `clutter`)
- `degrade.staged.hard_stage_weights`, `degrade.hard` (`p5`, `soft_scale`, `photo`)
- `difficulty` (version 2 weights)

## Known limits

- The class cut-offs and weights are still provisional until the calibration run.
- Hard pages are dense on purpose; at the most severe stage some lines are very faint. `soft_scale` and the ink fade strength are the knobs.
- The correction word is chosen from other words of the page; it is not meant to be the "right" word, only a visible rewrite. The label records exactly what is visible.
- Tests: `tests/test_hard.py` (forces the phone photo); `tests/regression_gate.py` proves older configs are unchanged.
