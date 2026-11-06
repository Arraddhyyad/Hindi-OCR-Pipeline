# Handwriting step (experiments)

Goal: given one Hindi word as text, produce an image that looks like real pen handwriting, with the spelling exactly right, so it can be placed on a generated page.

Two approaches tried with FLUX.2 klein 4B (LoRA fine-tuning on Colab):
- Plan A, text to handwriting (`notebooks/flux_words_pilot_v2.ipynb`): learns the look but not the spelling (0 of 12 words read back correctly).
- Plan B, restyle (`notebooks/flux_words_edit_v3.ipynb`): the input is a printed render of the word and the model rewrites it as handwriting, so the spelling comes from the input. Not yet tested on Colab.

Scripts (run from the repo root):
- `inspect_datasets.py`: lists what is inside a dataset zip.
- `prepare_flux_words.py`: word images and captions for the Plan A pilot.
- `prepare_flux_edit_pairs.py`: printed/handwritten word pairs for Plan B.
- `rank_writers_by_slant.py`: ranks ICDAR writers by how much their writing leans (measure is rough; check `top_writers.png` by eye).

Data is not in git (ICDAR 2024 word-level training set, kept locally). Findings so far: ICDAR is mostly upright, neat writing, so it teaches the skill but not the fast slanted hand in the reference pages. Style needs small sets from the real references.
