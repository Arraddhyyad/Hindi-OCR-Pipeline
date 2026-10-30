"""Automatic first-draft labels for each selected page. A person corrects them afterwards (see review.py).

Draft transcript and word boxes: Tesseract (Hindi + English). Draft stamp / mark boxes: coloured-ink blobs.
Everything written here has status "draft" and is never scored against until it is reviewed."""
import csv
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def parse_tsv(tsv):
    """Tesseract TSV text -> (transcript, words). Words carry a four-corner box, like the generated labels."""
    lines = tsv.splitlines()
    if not lines:
        return "", []
    head = lines[0].split("\t")
    words, rows = [], {}
    for ln in lines[1:]:
        c = ln.split("\t")
        if len(c) < len(head):
            continue
        d = dict(zip(head, c))
        txt = d["text"].strip()
        if d["level"] != "5" or not txt:
            continue
        try:
            conf = float(d["conf"])
            x, y, w, h = (int(d[k]) for k in ("left", "top", "width", "height"))
        except ValueError:
            continue
        words.append({"text": txt, "conf": conf, "box": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]})
        rows.setdefault((d["block_num"], d["par_num"], d["line_num"]), []).append(txt)
    transcript = "\n".join(" ".join(v) for v in rows.values())
    return transcript, words


def run_tesseract_tsv(image, lang="hin+eng", psm=3):
    r = subprocess.run(["tesseract", str(image), "-", "-l", lang, "--psm", str(psm), "tsv"],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[:300])
    return r.stdout.decode("utf-8", "replace")


def propose_marks(image_path, min_area=0.0008, max_area=0.08):
    """Boxes around strongly coloured ink (stamps, thumbprints, ink blots). Type is left blank for the reviewer."""
    img = cv2.imread(str(image_path))
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] > 90) & (hsv[..., 2] > 40) & (hsv[..., 2] < 235)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    H, W = mask.shape
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if min_area * H * W <= w * h <= max_area * H * W:
            out.append({"type": "", "box": [[int(x), int(y)], [int(x + w), int(y)], [int(x + w), int(y + h)], [int(x), int(y + h)]]})
    return out


def annotate(work_dir, lang="hin+eng", log=print):
    work = Path(work_dir)
    (work / "labels").mkdir(exist_ok=True)
    with open(work / "selected.csv", newline="", encoding="utf-8") as f:
        sel = list(csv.DictReader(f))
    src = {}
    sp = work / "sources.csv"
    if sp.exists():
        with open(sp, newline="", encoding="utf-8") as f:
            src = {r["id"]: r for r in csv.DictReader(f)}
    for n, r in enumerate(sel, 1):
        dest = work / "labels" / (r["page_id"] + ".json")
        if dest.exists():
            continue   # never overwrite a page someone has already worked on
        transcript, words = parse_tsv(run_tesseract_tsv(r["path"], lang))
        s = src.get(r["source_id"], {})
        dest.write_text(json.dumps({
            "page_id": r["page_id"], "source_id": r["source_id"], "image": r["path"],
            "width": int(r["width"]), "height": int(r["height"]),
            "source_url": s.get("source_url", ""), "license": s.get("license", ""),
            "status": "draft", "draft_reader": f"tesseract_{lang}",
            "transcript": transcript, "words": words, "objects": propose_marks(r["path"]), "facts": [],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        if n % 10 == 0:
            log(f"{n}/{len(sel)} drafted")
    return len(sel)
