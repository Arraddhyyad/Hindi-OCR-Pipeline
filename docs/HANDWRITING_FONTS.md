# Added handwriting fonts

Six handwriting fonts were added from the `hindi-handwritten-styles` branch (all SIL OFL, files and licences in `assets/fonts/<name>/`):
Tillana, Dekko, Playpen Sans Deva, Ranga, Yatra One, Jaini Purva. Kalam and Amita were already in the pipeline.

Use them with `config/hindi_sale_deed_v2_hand8.yaml` (a copy of the v2 config with a longer `handwriting.fonts` list and font difficulty values).
No pipeline code was changed. The default configs behave exactly as before (`python tests/regression_gate.py` passes).

| Font | Enabled | Note |
|---|---|---|
| Kalam, Amita | yes | already in the pipeline |
| Tillana | yes | thin, slightly slanted pen |
| Playpen Sans Deva | yes | rounded, child-like |
| Ranga | yes | small, condensed |
| Yatra One | yes | bold brush |
| Jaini Purva | yes | old manuscript shapes, hardest to read |
| Dekko | NO | draws conjuncts as separate letters (श्री looks like शुरी), so the image would not match the label. Bundled, not enabled. |

The font weights and the difficulty values for the new fonts are first guesses (provisional, like the rest) until the calibration is run.
