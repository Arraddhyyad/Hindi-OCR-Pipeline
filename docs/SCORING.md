# How pages are scored

Everything here is in `benchmark/`. Nothing is hidden in the OCR tools: the same cleaning and the same rules apply to every reader.

## 1. Clean the text first (`benchmark/normalize.py`)
The answer key and the OCR text both go through the same steps, so we only count real mistakes:
1. Unicode NFC. The same letter can be stored in different ways (for example a letter with a dot, as one code or two). NFC makes them equal.
2. Remove zero-width joiner and non-joiner marks (invisible, and OCR tools add or drop them freely).
3. Devanagari digits become 0 to 9 (default). Pages use both styles and readers pick either. `--digits keep` turns this off.
4. All runs of spaces and line breaks become one space. So line breaks and reading-order line splits do not count as errors, but a missing or extra space inside a word does.

Not removed: punctuation, danda marks, case. A wrong or missing punctuation mark counts as an error.

## 2. Error rates (`benchmark/metrics.py`)
Error rate = (substitutions + deletions + insertions) divided by the length of the answer key. 0% is perfect, and above 100% is possible (the reader wrote more than there was).
- **CER**: counted in characters (code points, spaces included).
- **gCER**: counted in letter clusters, so a letter with its vowel sign, or a conjunct like क्ष, is one unit. This is closer to what a reader sees as one mistake. Rules in `benchmark/graphemes.py`. Not the `regex` module, so every machine gives the same number.
- **WER**: counted in words (split on spaces).
- **Pooled rates**: for a group of pages, total errors divided by total length, so long pages count more.
- **medCER**: the median page, not the pooled rate. One looping or empty output can pull a pooled average far up, so look at both.
- **failed**: the share of pages with CER above 50%. A page like that is a failed read, not a slightly wrong one.

## 3. Fact recall (`benchmark/facts.py`)
Each page label lists its key facts (names, places, dates, plot number, area, amounts in digits and in words, cheque number, stamp duty). A fact counts as found if it appears in the OCR text after cleaning.
- **facts**: found word for word.
- **facts close**: found with small slips (rapidfuzz partial match at 85 or more of 100; facts shorter than 4 characters must match exactly).
- **numbers**: the facts that contain a digit (dates, amounts, plot numbers).
This tells us if the part that matters, who sold what to whom for how much, was read, which a low CER cannot.

## 4. Groups
Rows are grouped by the page's difficulty label (easy, medium, hard), damage stage (1 to 5) and page style (printed, hybrid, handwritten). Set names: A is the standard set, B the hard handwriting set, C the ladder (the same page at stages 1 to 5), P the printed control.

## 5. The printed control (`benchmark/make_control.py`)
The same text as each page, in a plain font on a white page, with no stamps, notes or damage. It shows how well a reader does on the text alone. The gap between the control and a clean benchmark page is the cost of our layout (stamps, notes, handwriting fonts), and the gap between the clean and the damaged copy is the cost of the damage.

## 6. Known limits
- The answer key is the scored text only. Stamps, margin notes and overlap text are not in it, but a reader will read them, so they count as insertions. That raises every reader's error on every page by a similar amount.
- Reading order is not scored separately. Lines are compared as one stream of words.
- Struck-through words are in the answer key (they are visible text). `transcript_marked` in the label shows them with `~~`.
- Provisional: the difficulty classes come from weights that have not been calibrated against real OCR results.
- Samples from the slow page-reading model are a spread of pages, not the whole set. Compare it with the other readers on the same pages (use `--spread` for those too).
