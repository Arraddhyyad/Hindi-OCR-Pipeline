"""DohaScript: real handwritten Hindi pages where every writer copied the same six dohas.
Because the text is known, the answer key comes for free. Page-level only: no line or word boxes.

Data: https://huggingface.co/datasets/SIR-Lab/DohaScript (200 sample pages) or the paper's full set (531 pages).
Licence: research and education only. Do not republish the images. Keep the dataset README and cite the paper
(Singh, Prakash, Lone, arXiv:2602.18089). Ask the authors before putting the images in a public release."""
import json
import shutil
from pathlib import Path

from .prepare import contact_sheet

# The six dohas, as printed in the paper's Appendix C. CHECK THIS TEXT AGAINST THE PAPER before trusting scores:
# it was copied from a web summary of the paper, not from the PDF itself.
DOHAS = [
    "गुरु गोविंद दोऊ खड़े, काके लागूं पांय। बलिहारी गुरु आपने, गोविंद दियो बताय॥",
    "धीरे-धीरे रे मना, धीरे सब कुछ होय । माली सींचे सौ घड़ा, ऋतु आए फल होय॥",
    "दया धर्म का मूल है, पाप मूल अभिमान। तुलसी दया न छाँड़िये, जब लग घट में प्राण॥",
    "पोथी पढ़ि पढ़ि जग मुआ, पंडित भया न कोय। ढाई आखर प्रेम का, पढ़े सो पंडित होय॥",
    "सांच बराबर तप नहीं, झूठ बराबर पाप। जाके हिरदै सांच है, ताके हिरदै आप॥",
    "क्षेत्रपाल गुरु ज्ञान का, शुद्ध रखे विचार। षट्दर्शन सब जानिए, सद्गुरु ही आधार॥",
]


def build(images_dir, out_dir, limit=None, dohas=None):
    """Write out_dir/dataset/test/doc_H0001.{jpg,json} for every image, in the layout benchmark.run reads.
    Gender, age and place are deliberately left out, including from file names (they are part of the original names)."""
    imgs = sorted(p for p in Path(images_dir).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    imgs = imgs[:limit] if limit else imgs
    text = "\n".join(dohas or DOHAS)
    d = Path(out_dir) / "dataset" / "test"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, p in enumerate(imgs, 1):
        stem = f"doc_H{n:04d}"
        dest = d / (stem + p.suffix.lower())
        shutil.copy(p, dest)
        (d / (stem + ".json")).write_text(json.dumps({
            "transcript": text, "facts": [], "style": {"page_style": "handwritten_real"},
            "source": "DohaScript (SIR-Lab)", "source_index": n,
            "license": "research and education only; do not redistribute",
            "reference": "same six dohas for every writer; page-level text only, not verified per page",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append({"path": str(dest)})
    contact_sheet(rows[:24], Path(out_dir) / "check_sheet.jpg")
    return len(imgs)
