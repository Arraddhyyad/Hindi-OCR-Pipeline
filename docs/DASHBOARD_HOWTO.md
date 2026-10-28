# The results dashboard

A simple page that shows what we did, why, and how well the reader did. It is made from the scored results, so it never needs editing by hand.

## Refresh it (PowerShell, from the repo folder)
```
python -m benchmark.dashboard --results Tesseract=docs/results/tesseract_v3_results.csv --out docs/dashboard
git add docs/dashboard
git commit -m "Update results dashboard"
git push
```
Open `docs/dashboard/index.html` in a browser to look at it before pushing.

## Change the sample page pictures (only needed once, or when the pages change)
Add the dataset folders so it can pick pages by their labels (a few pages, shrunk to about 70 KB each):
```
python -m benchmark.dashboard --results Tesseract=docs/results/tesseract_v3_results.csv --out docs/dashboard `
  --set A=data/benchmark_v1/setA_standard/dataset --set B=data/benchmark_v1/setB_hard/dataset `
  --set C=data/benchmark_v1/setC_ladder/dataset --set P=data/benchmark_v1/controlA/dataset
```

## Add another reader
Score it with `benchmark.run` (its own `--out` folder), then list both:
```
python -m benchmark.dashboard --results Tesseract=docs/results/tesseract_v3_results.csv --results EasyOCR=docs/results/easyocr_results.csv --out docs/dashboard
```

## Where the team sees it
- **On GitHub right away:** open the `docs/dashboard` folder. GitHub shows `README.md`, which has the same story and the charts.
- **As a proper web page:** in the repo, Settings, Pages, choose the `main` branch and the `/docs` folder. The page is then at `https://arraddhyyad.github.io/Hindi-OCR-Pipeline/dashboard/`. (Pages only works from a branch you pick, so merge `benchmark` into `main` first, or pick `benchmark` as the branch while testing.)
- **Offline:** send the `docs/dashboard` folder; `index.html` needs no internet.

## What is in it
Everything on the page comes from the results file or from the two text files in `benchmark/dashboard.py` (`story` and `PAPERS`). The sentences under "What stands out" are computed from the numbers, so they change when the results change. Change the wording of the story in `story()`.
