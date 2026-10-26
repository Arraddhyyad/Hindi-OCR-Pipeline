"""Runs steps 1-6 for one page and SAVES THE RESULT OF EVERY STEP, so any page can be inspected, backtracked or resumed.

pages/<doc_id>/
  01_entities.json     page plan (size, font, ink, margins) + the entity graph
  02_text.json         paragraphs, transcript, writer, fit attempts
  03_layout.png/.json  clean fitted page, word + line boxes, reserved slots
  04_composed.png/.json  composed page (paper, header, footer, stamps, signatures, marks...), elements with polygons
  05_degraded.png / 05_target.png / 05_degraded.json   final image, aligned clean target, degradation log, transformed boxes
  06_label.json        compact training label
  steps.json           per-step status + seconds
Re-running skips steps whose files exist (resume); `from_step=N` recomputes steps N..6 from the saved files of steps < N.
"""
import io, json, logging, random, time, traceback
import copy
from dataclasses import asdict
from pathlib import Path
from PIL import Image
from .common import dump_json, load_json
from .step1_entities import generate_entity_graph
from .step2_text import TemplateWriter, missing_facts
from .step3_layout import PageStyle, Renderer, estimate_words, plan_page
from .step4_compose import compose_page
from .step5_degrade import degrade_page, degrade_page_staged
from .step6_export import write_dataset_page, split_of
from .assets import AssetLib

log = logging.getLogger("docgen")
STEPS = {1: "entities", 2: "text", 3: "layout", 4: "compose", 5: "degrade", 6: "label"}


def _png(img) -> bytes:
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


class PageRunner:
    def __init__(self, cfg, run_dir, renderer: Renderer, lib: AssetLib, writer=None):
        self.cfg, self.run_dir, self.r, self.lib = cfg, Path(run_dir), renderer, lib
        self.writer = writer or TemplateWriter()
        import pipeline.step3_layout as _L; _L.FONT_BASE = cfg["assets_dir"]      # relative font paths in v2 configs resolve here

    def run(self, seed: int, from_step: int | None = None, until_step: int = 6):
        cfg = self.cfg; pid = f"doc_{seed:07d}"; d = self.run_dir / "pages" / pid; d.mkdir(parents=True, exist_ok=True)
        steps = load_json(d / "steps.json") if (d / "steps.json").exists() else {}
        f = lambda n: d / n
        done = lambda n, *files: (from_step is None or n < from_step) and all(f(x).exists() for x in files)
        t_all = time.time()
        if from_step is None and until_step >= 6 and f("06_label.json").exists() and steps.get("label", {}).get("status") == "ok":
            lab = load_json(f("06_label.json")); return {"seed": seed, "id": pid, "skipped": True, "severity": lab["severity"]}

        def timed(n, fn):
            t = time.time()
            try:
                out = fn(); steps[STEPS[n]] = {"status": "ok", "sec": round(time.time() - t, 2)}; log.debug("%s step %d %s ok", pid, n, STEPS[n]); return out
            except Exception as e:
                steps[STEPS[n]] = {"status": "error", "error": repr(e), "tb": traceback.format_exc()[-1500:]}; dump_json(f("steps.json"), steps); raise

        # ---- step 1: page plan + entity graph
        if done(1, "01_entities.json"): s1 = load_json(f("01_entities.json"))
        else:
            def go():
                rng = random.Random(cfg.get("seed_base", 0) + seed)
                st = plan_page(cfg, rng, seed); g = generate_entity_graph(rng, cfg)
                plan = asdict(st)
                if plan.get("ext") is None: plan.pop("ext", None)      # v1 configs: saved plan identical to the original package
                out = {"id": pid, "seed": seed, "page_plan": plan, "entities": g}; dump_json(f("01_entities.json"), out); return out
            s1 = timed(1, go)
        st = PageStyle(**s1["page_plan"]); g = s1["entities"]
        if until_step < 2: return pid

        # ---- steps 2+3: text then layout (a fit loop: if the page overflows or underfills, text length is rescaled and rewritten)
        if done(2, "02_text.json") and done(3, "03_layout.json", "03_layout.png"):
            s2, rec = load_json(f("02_text.json")), load_json(f("03_layout.json")); clean_png = f("03_layout.png").read_bytes()
        else:
            def go():
                scale, res, doc = 1.0, None, None
                for attempt in range(1, cfg["fit"]["max_attempts"] + 1):
                    target = max(150, int(estimate_words(st, (st.ext or {}).get("fs_target", 24.0)) * scale))
                    if (st.ext or {}).get("compact") and self.writer.name == "template":     # v2 very large type: short-form deed
                        from .step2_text import write_compact
                        doc = write_compact(g, random.Random(seed * 31 + attempt))
                    else:
                        doc = self.writer.write(g, random.Random(seed * 31 + attempt), target)
                    miss = missing_facts(g, doc); assert not miss, f"facts missing: {miss}"
                    hand = None
                    if st.ext and st.ext.get("hand"):                                  # v2 handwriting: which words are written by hand
                        from .handwriting import hybrid_marks
                        h = st.ext["hand"]
                        if h["mode"] == "handwritten": hand = {(pi, wi) for pi, p_ in enumerate(doc.paragraphs) for wi in range(len(p_["text"].replace("\n", " ").split()))}
                        else: hand = hybrid_marks(doc.paragraphs, g, cfg["handwriting"]["hybrid_facts"], cfg["handwriting"].get("hybrid_digits", True))
                    res = self.r.fit_and_render(doc.paragraphs, st, hand=hand)
                    if res.status == "ok": break
                    scale *= 0.8 if res.status == "overflow" else 1.25
                return doc, res, attempt
            doc, res, attempt = timed(2, go)
            s2 = {"id": pid, "writer": doc.writer, "paragraphs": doc.paragraphs, "transcript": doc.text, "attempts": attempt, "fit_status": res.status}
            dump_json(f("02_text.json"), s2)
            rec = {"id": pid, "seed": seed, "status": res.status, "attempts": attempt,
                   "page": {"width": st.width, "height": st.height, "font": st.font_family, "weight": st.font_weight, "ink": st.ink,
                            "align": st.align, "font_size": res.font_size, "line_height": res.line_height, "fill": res.fill},
                   "entities": g, "writer": doc.writer, "paragraphs": doc.paragraphs, "transcript": doc.text,
                   "words": res.words, "lines": res.lines, "slots": res.slots}
            if st.ext:                                                                      # v2 only
                rec["page"]["ext"] = {**st.ext, "fonts_status": res.font_status}
                if st.ext.get("hand"): rec["page"]["ext"]["hand_words"] = sum(1 for w_ in res.words if w_.get("hand"))
            clean_png = res.png; f("03_layout.png").write_bytes(clean_png); dump_json(f("03_layout.json"), rec)
            steps["text"] = {"status": "ok", "attempts": attempt, "sec": steps["text"]["sec"]}
        if until_step < 4: dump_json(f("steps.json"), steps); return pid

        # ---- step 4: compose (assets)
        if done(4, "04_composed.json", "04_composed.png"):
            rec = load_json(f("04_composed.json")); composed = Image.open(f("04_composed.png")).convert("RGB")
        else:
            def go():
                img, extra = compose_page(clean_png, rec, self.lib, cfg, random.Random(seed * 7919 + 1), self.r)
                rec.update(extra); rec["stage"] = 4; return img
            composed = timed(4, go); composed.save(f("04_composed.png")); dump_json(f("04_composed.json"), rec)
        if until_step < 5 or not cfg.get("degrade", {}).get("enabled", True): dump_json(f("steps.json"), steps); return pid

        # ---- step 5: degrade (last image step)
        if done(5, "05_degraded.json") and (f("05_degraded.png").exists()):
            rec = load_json(f("05_degraded.json")); final = f("05_degraded.png").read_bytes()
            target = f("05_target.png").read_bytes() if f("05_target.png").exists() else None
        else:
            sg = cfg["degrade"].get("staged") or {}
            sg = sg if sg.get("enabled") else None
            base_rec = None
            def go():
                nonlocal base_rec
                if sg:                                     # v2 staged mode: one image per page at a stage drawn from the weights
                    sw = sg["stage_weights"]
                    if sg.get("hard_stage_weights") and (rec.get("page", {}).get("ext") or {}).get("hard"): sw = sg["hard_stage_weights"]     # v2 hard pages: only the severe stages
                    stage = random.Random(f"stage|{seed}").choices([int(k) for k in sw], weights=list(sw.values()))[0]
                    base_rec = copy.deepcopy(rec); first = stage
                    out, tgt, _, new_el, meta = degrade_page_staged(composed, rec, self.lib, cfg, str(seed), stage, cfg["degrade"].get("paired", True))
                    while (cfg["degrade"].get("guardrails") or {}).get("enforce") and meta.get("guardrail", {}).get("would_reject") and stage > 1:
                        stage -= 1                                      # enforcement (after calibration): a page past the limits is redone one stage lower
                        rec.clear(); rec.update(copy.deepcopy(base_rec))
                        out, tgt, _, new_el, meta = degrade_page_staged(composed, rec, self.lib, cfg, str(seed), stage, cfg["degrade"].get("paired", True))
                        meta["guardrail"]["downgraded_from"] = first
                else:
                    out, tgt, _, new_el, meta = degrade_page(composed, rec, self.lib, cfg, random.Random(seed * 104729 + 3), cfg["degrade"].get("paired", True))
                rec["elements"].extend(new_el); rec["degradation"] = meta; rec["final_size"] = meta["final_size"]; rec["stage"] = 5
                return out, tgt, meta
            out, tgt, meta = timed(5, go)
            fmt = "JPEG" if cfg["degrade"].get("format") == "jpg" else "PNG"
            b = io.BytesIO(); out.save(b, fmt, quality=meta["jpeg_quality"]); final = b.getvalue()
            f("05_degraded.png").write_bytes(final)           # (jpg runs: bytes are JPEG; suffix kept stable on purpose)
            target = _png(tgt) if tgt is not None else None
            if target: f("05_target.png").write_bytes(target)
            dump_json(f("05_degraded.json"), rec)
            lad = (sg or {}).get("ladder") or {}
            if sg and lad.get("enabled") and split_of(seed, cfg) in lad.get("splits", ["test"]):     # optional ladder: all five stages of this page
                for k in range(1, 6):
                    r2 = copy.deepcopy(base_rec)
                    o2, t2, _, el2, m2 = degrade_page_staged(composed, r2, self.lib, cfg, str(seed), k, cfg["degrade"].get("paired", True))
                    r2["elements"].extend(el2); r2["degradation"] = m2; r2["final_size"] = m2["final_size"]; r2["stage"] = 5; r2["id"] = f"{pid}_s{k}"
                    b2 = io.BytesIO(); o2.save(b2, fmt, quality=m2["jpeg_quality"])
                    f(f"05_degraded_s{k}.png").write_bytes(b2.getvalue())
                    if t2 is not None: f(f"05_target_s{k}.png").write_bytes(_png(t2))
                    dump_json(f(f"05_degraded_s{k}.json"), r2)
        if until_step < 6: dump_json(f("steps.json"), steps); return pid

        # ---- step 6: label + dataset export
        def go():
            if f("05_degraded_s1.json").exists():          # ladder page: the dataset gets the five stage variants (shared seed, hence the same split), not the base image
                for k in range(1, 6):
                    r2 = load_json(f(f"05_degraded_s{k}.json")); tg = f(f"05_target_s{k}.png"); sp, rel2, lab2 = write_dataset_page(
                        cfg, self.run_dir / "dataset", r2, f(f"05_degraded_s{k}.png").read_bytes(), tg.read_bytes() if tg.exists() else None)
                    dump_json(f(f"06_label_s{k}.json"), lab2)
                label = lab2; relfile = f"{sp}/{pid}_s1..s5"
                dump_json(f("06_label.json"), label); return sp, relfile, label
            sp, relfile, label = write_dataset_page(cfg, self.run_dir / "dataset", rec, final, target)
            dump_json(f("06_label.json"), label); return sp, relfile, label
        sp, relfile, label = timed(6, go)
        steps["total_sec"] = round(time.time() - t_all, 2); dump_json(f("steps.json"), steps)
        return {"seed": seed, "id": pid, "split": sp, "file": relfile, "severity": label["severity"], "words": len(label["words"]),
                "fill": rec["page"]["fill"], "status": rec["status"], "sec": steps["total_sec"],
                "ops": label["ops"], "composition": label["composition"]}
