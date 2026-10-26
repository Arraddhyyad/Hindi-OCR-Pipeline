"""STEP 6 - export: compact training label per page, deterministic train/val/test split, dataset folder writer."""
import hashlib, json
from pathlib import Path
from .step1_entities import required_facts


def split_of(seed, cfg):
    """Hash of the seed -> split, so extending a dataset never reshuffles existing pages."""
    f = cfg.get("export", {}).get("split", {"train": 0.9, "val": 0.05, "test": 0.05})
    u = int(hashlib.sha256(str(seed).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    acc = 0
    for k, v in f.items():
        acc += v
        if u <= acc: return k
    return list(f)[-1]


def slim(rec):
    """Training label: transcript, facts, scored word polygons (with visible / occluded), elements, degradation ops."""
    words = [{"text": w["text"], "poly": w["poly"], "visible": w.get("visible", 1), "occluded": w.get("occluded", 0)}
             for w in rec["words_all"] if w.get("scored")]
    for w, src in zip(words, [w for w in rec["words_all"] if w.get("scored")]):
        if src.get("hand"): w["hand"] = True                       # v2 only: written by hand (key absent otherwise, so v1 labels are unchanged)
        if src.get("struck"): w["struck"] = True                   # hard pages only: struck through with a pen (the word stays in the transcript)
        if src.get("kind") == "correction": w["correction"] = True # hard pages only: written above a struck word
    out = _slim_base(rec, words)
    if rec.get("transcript_marked"): out["transcript_marked"] = rec["transcript_marked"]      # hard pages only: struck words shown as ~~word~~
    ext = (rec.get("page") or {}).get("ext")
    if ext: out["style"] = {"page_style": ext.get("page_style"), "font": rec["page"]["font"], "font_size": rec["page"]["font_size"],
                            "hand_font": (ext.get("hand") or {}).get("family"), "hand_words": ext.get("hand_words", 0)}
    dg = rec["degradation"]
    if dg.get("stage"): out["stage"] = {"stage": dg["stage"], "name": dg["stage_name"], "measure": dg.get("measure")}      # staged degradation (v2) only
    return out


def _slim_base(rec, words):
    return {"id": rec["id"], "facts": required_facts(rec["entities"]), "seed": rec["seed"], "size": rec["final_size"],
            "transcript": rec["transcript"], "words": words,
            "severity": rec["degradation"]["severity"], "ops": [o["op"] for o in rec["degradation"]["ops"]],
            "elements": [{"type": e["type"], "bbox": e["bbox"], "visible": e.get("visible", 1)} for e in rec["elements"]],
            "composition": rec["composition"]}


def write_dataset_page(cfg, out_dir: Path, rec, final_bytes, target_bytes):
    """Write image + target + label into out_dir/<split>/. The label is written last and acts as the 'done' marker."""
    sp = split_of(rec["seed"], cfg); d = Path(out_dir) / sp; d.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if cfg["degrade"].get("format") == "jpg" else "png"; pid = rec["id"]
    (d / f"{pid}.{ext}").write_bytes(final_bytes)
    if target_bytes: (d / f"{pid}_target.png").write_bytes(target_bytes)
    label = slim(rec)
    if (cfg.get("difficulty") or {}).get("enabled"):          # v2 only: difficulty block (score, class, the numbers behind it)
        from .difficulty import assess
        label["difficulty"] = assess(label, cfg["difficulty"])
    (d / f"{pid}.json").write_text(json.dumps(label, ensure_ascii=False), encoding="utf-8")
    return sp, f"{sp}/{pid}.{ext}", label
