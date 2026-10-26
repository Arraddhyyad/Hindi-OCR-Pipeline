# Verification report — demo
**24/24 pages pass all checks.**  Duplicate transcripts: 0.  Negative-control alignment rate: 0.006 (must be far below the real rate).

| check | passed | failed | skipped |
|---|---|---|---|
| amount_digits | 24 | 0 | 0 |
| amount_words_parse | 24 | 0 | 0 |
| boxes_in_page | 24 | 0 | 0 |
| boxes_on_ink_final | 24 | 0 | 0 |
| boxes_on_ink_target | 24 | 0 | 0 |
| composition_valid | 24 | 0 | 0 |
| facts_present | 24 | 0 | 0 |
| fill_in_range | 24 | 0 | 0 |
| folded_and_torn | 24 | 0 | 0 |
| labels_match_text | 24 | 0 | 0 |
| polygons_valid | 24 | 0 | 0 |

## Variety
```
{
 "page_sizes": {
  "1317x1713": 2,
  "1313x1710": 1,
  "1264x1771": 1,
  "1277x1780": 1,
  "1228x1818": 1,
  "1368x1766": 1,
  "1302x1701": 1,
  "1361x1760": 1
 },
 "fonts": {
  "Nakula": 2,
  "Noto Serif Devanagari": 8,
  "Samanata": 3,
  "Gargi": 3,
  "Noto Sans Devanagari": 2,
  "Lohit Devanagari": 4,
  "Kalimati": 2
 },
 "severity": {
  "light": 7,
  "heavy": 7,
  "medium": 10
 },
 "header_modes": {
  "banner": 17,
  "letterhead": 5,
  "none": 2
 },
 "footer_modes": {
  "endorsement": 10,
  "none": 9,
  "line": 5
 },
 "stamps_per_page": {
  "1": 5,
  "2": 12,
  "3": 6,
  "4": 1
 },
 "ops": {
  "folds": 24,
  "jpeg": 24,
  "torn_edge": 24,
  "noise": 24,
  "rotate": 24,
  "blur": 21,
  "ink_blots": 21,
  "resample": 18,
  "dust_specks": 14,
  "perspective": 12,
  "lighting_gradient": 12,
  "page_bend": 11,
  "shadow_band": 10,
  "stain": 9,
  "low_contrast": 8,
  "ink_erode": 7,
  "augraphy.SubtleNoise": 6,
  "augraphy.BleedThrough": 6,
  "augraphy.LowInkRandomLines": 6,
  "ink_dilate": 5,
  "augraphy.InkMottling": 5,
  "augraphy.BadPhotoCopy.FAILED": 2,
  "augraphy.BadPhotoCopy": 1
 },
 "fill_min_max": [
  0.918,
  0.964
 ]
}
```

Overlays: `pages/<id>/07_verify_overlay.png` (green=scored word, orange=occluded, red=torn away/invisible, blue=stamps/marks/signatures).