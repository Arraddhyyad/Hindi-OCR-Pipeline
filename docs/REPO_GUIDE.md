# How this repo is organised

One folder per job. Each job can be run and tested on its own.

| Folder | Job | Test |
|---|---|---|
| `pipeline/`, `config/`, `assets/`, `main.py` | Makes the synthetic deed pages and answer keys | `python tests/test_pipeline_smoke.py` |
| `handwriting/` | The word to handwriting step (Flux restyle experiments) | its own tests, added as it grows |
| `benchmark/` | Runs OCR tools on the pages and scores them | `python -m unittest tests.test_benchmark -v` |
| `data/` | Local copy of generated pages (not in git, see `data/README.md`) | none |
| `docs/` | Notes and plans | none |

## Working rule
1. `main` always works. It only gets code whose tests pass.
2. One branch per piece of work, named for the job: `benchmark`, `flux-handwriting`, and so on.
3. Small commits, each says what changed and why, in plain words.
4. When a branch's test passes, merge it into `main`.

## The benchmark in one line
```
python -m benchmark.run --set A=data/benchmark_v1/setA_standard/dataset \
    --set B=data/benchmark_v1/setB_hard/dataset --backend tesseract --out runs_benchmark/tess --clean
```
It writes `summary.md` (error rates by difficulty, damage stage and page style) and `results.csv` (one row per page). Predictions are saved per page, so a re-run only does what is missing.

Backends: `tesseract` (needs the Hindi model, `hin`), `easyocr`, and two fake ones used only by the tests.

## Later: one command for everything
When the handwriting step works, a single script will chain: generate pages, put handwriting in, damage, benchmark.
