# Real Hindi documents: find, annotate, score

Goal: about 50 real Hindi legal or official pages with a corrected transcript, so we can check the generated pages
against real ones and score readers on real pages. Everything runs from the repo root. Work files go in `real_work/`
(git-ignored).

Needs: `pip install -r requirements.txt`, and Tesseract with the Hindi model (`hin`) installed.

## Steps

```
python -m realdocs fetch    --work real_work              # 1. search + download open-licensed items -> sources.csv
python -m realdocs prepare  --work real_work              # 2. page images, blanks dropped -> contact_sheet.jpg
python -m realdocs pick     --work real_work -n 50        # 3. 50 pages spread across sources -> selected.csv
python -m realdocs annotate --work real_work              # 4. automatic draft labels -> labels/*.json
python -m realdocs ls-export --work real_work             # 5. files for Label Studio
   ... correct the drafts in Label Studio, export JSON ...
python -m realdocs ls-import --work real_work --export export.json   # 6. mark corrected pages reviewed
python -m realdocs build    --work real_work              # 7. real_work/dataset/test/doc_R0001.{jpg,json}
python -m benchmark.run --set R=real_work/dataset --backend tesseract --out docs/results/real_tesseract
```

Step 7's folder has the same layout as the generated sets, so the existing scoring runs unchanged.

## After step 2: screen by eye
Open `real_work/contact_sheet.jpg`. Note the ids of pages that are private, personal, unreadable or not Hindi
and leave them out in step 3: `python -m realdocs pick --work real_work -n 50 --drop PAGE_ID PAGE_ID`.
Pages are named `<source id>_p<page number>`. Use the contact sheet row and column to find the file in `real_work/images/`.

## Licences
`fetch` only downloads items that are public domain or openly licensed (public domain mark, CC0, CC BY, CC BY-SA, or
Internet Archive "not in copyright"). Everything else is skipped. Each download is logged with its URL and licence in
`sources.csv`. Check that file before publishing the set.

## Label Studio (step 5 to 6)
1. `pip install label-studio`, then set local file serving and start it from the repo root:
   - PowerShell: `$env:LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED="true"; $env:LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=(Resolve-Path real_work).Path; label-studio start`
2. Create a project. Labeling Setup > Custom template: paste the contents of `real_work/ls_config.xml`.
3. Add Source Storage > Local files, path = the `real_work` folder (images are under `images/`). Then Import
   `real_work/ls_tasks.json`.
4. For each page: fix the transcript text, give each coloured box a type (stamp, signature, thumbprint, ink_blot,
   handwritten_note, other), delete wrong boxes, draw missed ones, Submit.
5. Export as JSON (not JSON-MIN) and run step 6.

## What gets corrected
- Full correction (transcript + marks): aim for about 15 pages.
- Transcript only: the rest. Word boxes in `labels/*.json` are the unchecked Tesseract draft and are not written into
  the dataset.
- Re-check about 10 pages with a second pass and compare, to measure how much annotators disagree.

## Notes
- Re-running `annotate` never overwrites a page that already has a label file.
- `build` leaves out pages that are still "draft". `--include-draft` is for a dry run only.
- If an Internet Archive or Wikimedia request fails, `fetch` can be re-run: known items are skipped.
