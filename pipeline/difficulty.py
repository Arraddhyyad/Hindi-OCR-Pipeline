"""Difficulty label (v2 only). Turns what a page is made of and what its pixels look like into a score in 0..1 and a class easy / medium / hard.

The class is meant to be read by a machine later, so every input is a number that is stored next to it. Weights and thresholds start as
PROVISIONAL guesses; tools/calibrate.py fits them against measured OCR error rates and writes a calibrated block (provisional: false).
"""
COMPONENTS = ("stage", "contrast", "sharpness", "occlusion", "handwriting", "small_text", "font")
EXTRA = ("corrections", "density", "photo")     # hard-page parts: only used (and only written) when the config gives them a weight, so older configs score exactly as before
DEFAULTS = {"enabled": True, "provisional": True, "version": 1,
            "weights": {"stage": .25, "contrast": .20, "sharpness": .15, "occlusion": .15, "handwriting": .12, "small_text": .08, "font": .05},
            "thresholds": {"easy_max": 0.22, "medium_max": 0.46},
            "font_difficulty": {"Amita": 0.5, "Kalam": 0.3, "Tiro Devanagari Hindi": 0.15},
            "small_text_px": 22}


def _clip(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))


def features(label: dict, cfg: dict) -> dict:
    """Each component is 0 (no extra difficulty) .. 1 (maximum). Missing measurements count as 0 and are listed in `missing`."""
    st, sg = label.get("style") or {}, label.get("stage") or {}
    ms = sg.get("measure") or {}; miss = []
    def m(key):
        if key not in ms: miss.append(key)
        return ms.get(key)
    n = max(1, len(label.get("words", [])))
    cr, sh, oc = m("contrast_ratio"), m("sharpness_ratio"), m("occluded_frac")
    fs = st.get("font_size") or 24
    fam = st.get("hand_font") if (st.get("page_style") == "handwritten") else st.get("font")
    f = {"stage": ((sg.get("stage") or 1) - 1) / 4,
         "contrast": _clip(1 - cr) if cr is not None else 0.0,
         "sharpness": _clip(1 - sh) if sh is not None else 0.0,
         "occlusion": _clip((oc or 0) / 0.5),
         "handwriting": _clip(1.25 * (st.get("hand_words", 0) / n)),
         "small_text": _clip((cfg["small_text_px"] - fs) / 8),
         "font": _clip(cfg["font_difficulty"].get(fam, 0.0) * 2)}
    w = cfg["weights"]
    if "corrections" in w: f["corrections"] = _clip(sum(1 for x in label.get("words", []) if x.get("struck") or x.get("correction")) / n / 0.04)     # share of words struck or corrected (4% = maximum)
    if "density" in w: f["density"] = _clip((n - 150) / 300)                                                                                      # words per page: 150 = none, 450 = maximum
    if "photo" in w: f["photo"] = 1.0 if "phone_photo" in (label.get("ops") or []) else 0.0
    return {"components": {k: round(v, 3) for k, v in f.items()}, "missing": miss}


def assess(label: dict, cfg: dict | None = None) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    ft = features(label, cfg); w = cfg["weights"]; tot = sum(w.values()) or 1.0
    score = round(sum(w[k] * ft["components"][k] for k in COMPONENTS + tuple(k for k in EXTRA if k in w)) / tot, 4)
    t = cfg["thresholds"]; cls = "easy" if score < t["easy_max"] else ("medium" if score < t["medium_max"] else "hard")
    out = {"score": score, "class": cls, "components": ft["components"], "provisional": bool(cfg.get("provisional", True)), "version": cfg.get("version", 1)}
    if ft["missing"]: out["missing"] = ft["missing"]
    return out
