"""Manual correction in Label Studio (free, runs on your machine), then export to the benchmark's folder layout.

  export_tasks  -> ls_tasks.json (images + the draft transcript and marks) and ls_config.xml
  import_export -> reads Label Studio's exported JSON back, marks those pages "reviewed"
  build_dataset -> real_set/dataset/test/doc_R0001.{jpg,json}: what `python -m benchmark.run --set R=...` reads"""
import json
import shutil
from pathlib import Path

OBJECT_TYPES = ["stamp", "signature", "thumbprint", "ink_blot", "handwritten_note", "other"]

LS_CONFIG = """<View>
  <Image name="image" value="$image" zoom="true"/>
  <RectangleLabels name="mark" toName="image">
%s
  </RectangleLabels>
  <Header value="Transcript: fix the text so it matches the page exactly. One line per printed line, reading order."/>
  <TextArea name="transcript" toName="image" rows="14" editable="true" perRegion="false" required="true"/>
</View>
""" % "\n".join(f'    <Label value="{t}"/>' for t in OBJECT_TYPES)


def _labels(work):
    return sorted((Path(work) / "labels").glob("*.json"))


def export_tasks(work_dir, url_prefix="/data/local-files/?d="):
    """Write ls_tasks.json + ls_config.xml. Point Label Studio's local storage at the work folder; images are served
    from <url_prefix><relative image path>."""
    work = Path(work_dir)
    tasks = []
    for lp in _labels(work):
        lab = json.loads(lp.read_text(encoding="utf-8"))
        W, H = lab["width"], lab["height"]
        rel = Path(lab["image"]).resolve().relative_to(work.resolve()).as_posix()
        result = [{"from_name": "transcript", "to_name": "image", "type": "textarea",
                   "value": {"text": lab["transcript"].split("\n")}}]
        for i, o in enumerate(lab["objects"]):
            (x0, y0), (x1, y1) = o["box"][0], o["box"][2]
            result.append({"id": f"m{i}", "from_name": "mark", "to_name": "image", "type": "rectanglelabels",
                           "original_width": W, "original_height": H,
                           "value": {"x": 100 * x0 / W, "y": 100 * y0 / H, "width": 100 * (x1 - x0) / W,
                                     "height": 100 * (y1 - y0) / H, "rectanglelabels": [o["type"] or "other"]}})
        tasks.append({"data": {"image": url_prefix + rel, "page_id": lab["page_id"]},
                      "predictions": [{"model_version": lab["draft_reader"], "result": result}]})
    (work / "ls_tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "ls_config.xml").write_text(LS_CONFIG, encoding="utf-8")
    return len(tasks)


def import_export(work_dir, export_json):
    """Read a Label Studio JSON export. Every task with a submitted annotation becomes status "reviewed"."""
    work = Path(work_dir)
    done = 0
    for t in json.loads(Path(export_json).read_text(encoding="utf-8")):
        anns = [a for a in t.get("annotations", []) if not a.get("was_cancelled")]
        if not anns:
            continue
        lp = work / "labels" / (t["data"]["page_id"] + ".json")
        lab = json.loads(lp.read_text(encoding="utf-8"))
        W, H = lab["width"], lab["height"]
        text, objs = None, []
        for r in anns[-1]["result"]:
            v = r["value"]
            if r["type"] == "textarea":
                text = "\n".join(v["text"])
            elif r["type"] == "rectanglelabels":
                x0, y0 = v["x"] * W / 100, v["y"] * H / 100
                x1, y1 = x0 + v["width"] * W / 100, y0 + v["height"] * H / 100
                objs.append({"type": v["rectanglelabels"][0],
                             "box": [[round(x0), round(y0)], [round(x1), round(y0)], [round(x1), round(y1)], [round(x0), round(y1)]]})
        if text is None:
            continue
        lab.update({"transcript": text, "objects": objs, "status": "reviewed"})
        lp.write_text(json.dumps(lab, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
    return done


def build_dataset(work_dir, out_dir=None, include_draft=False):
    """Write the benchmark folder layout. Only reviewed pages go in unless include_draft (for a dry run only)."""
    work = Path(work_dir)
    d = Path(out_dir or work / "dataset") / "test"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for lp in _labels(work):
        lab = json.loads(lp.read_text(encoding="utf-8"))
        if lab["status"] != "reviewed" and not include_draft:
            continue
        n += 1
        stem = f"doc_R{n:04d}"
        shutil.copy(lab["image"], d / (stem + ".jpg"))
        (d / (stem + ".json")).write_text(json.dumps({
            "transcript": lab["transcript"], "facts": lab.get("facts", []), "objects": lab["objects"],
            "source_page": lab["page_id"], "source_url": lab["source_url"], "license": lab["license"],
            "status": lab["status"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return n
