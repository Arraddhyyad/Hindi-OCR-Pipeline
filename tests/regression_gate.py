"""Regression gate: proves that changes to the pipeline did not alter existing behaviour.

Runs fixed seeds through steps 1-6 (including the dataset export) for each *old* config and compares with tests/regression_golden.json.

  Tier A (strict): Chromium launched with deterministic flags (injected here, pipeline code untouched). EVERY output file is hashed:
                   images, every step JSON, the exported dataset images and labels.
  Tier B (production flags): the pipeline exactly as users run it. Every JSON file must be byte-identical and every image must have the
                   same size. (Chromium's default rasteriser moves a few dozen pixels between launches on some pages, so image bytes
                   cannot be compared there; Tier A covers pixels.)

    python tests/regression_gate.py --record     # write the golden file (only from code you trust, e.g. before a change)
    python tests/regression_gate.py              # compare; exit code 1 on any difference
    python tests/regression_gate.py --fast       # Tier A only

Golden hashes depend on the machine (fonts, Chromium, library versions): they prove "my edits changed nothing here", not "this machine
matches another machine". Re-record on a new machine with --record from an unmodified checkout. steps.json is compared by status only
(it also holds timings).
"""
import argparse, hashlib, json, pathlib, shutil, struct, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEEDS = json.loads((ROOT / "tests" / "regression_seeds.json").read_text())
GOLDEN = ROOT / "tests" / "regression_golden.json"
DETERMINISTIC_FLAGS = ["--disable-gpu", "--disable-lcd-text", "--disable-font-subpixel-positioning", "--num-raster-threads=1"]


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def png_size(path: pathlib.Path):
    with open(path, "rb") as f:
        head = f.read(24)
    return list(struct.unpack(">II", head[16:24])) if head[:8] == b"\x89PNG\r\n\x1a\n" else None


def nondeterministic_pages(run: pathlib.Path) -> set:
    """Pages whose degradation recipe includes Augraphy's BadPhotoCopy. Its numba code has its own RNG that is not seeded,
    so the FINAL degraded image of such a page differs on every run (known defect, reproduced on the original package).
    Everything else on those pages (all JSON, the composed page, the aligned clean target) is still compared exactly."""
    ids = set()
    for j in (run / "pages").glob("doc_*/05_degraded.json"):
        ops = [o.get("op", "") for o in json.loads(j.read_text(encoding="utf-8")).get("degradation", {}).get("ops", [])]
        if any(o.startswith("augraphy.BadPhotoCopy") for o in ops):
            ids.add(j.parent.name)
    return ids


def is_final_image(rel: str, exempt: set) -> bool:
    parts = rel.split("/")
    if parts[0] == "pages" and len(parts) == 3:
        return parts[1] in exempt and parts[2] == "05_degraded.png"
    if parts[0] == "dataset" and len(parts) == 3:
        stem = parts[2].rsplit(".", 1)[0]
        return stem in exempt and not stem.endswith("_target") and parts[2].rsplit(".", 1)[-1] in ("png", "jpg")
    return False


def hash_run(run: pathlib.Path, tier: str) -> dict:
    out = {}
    exempt = nondeterministic_pages(run)
    for f in sorted(run.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(run).as_posix()
        if f.name == "steps.json":
            st = json.loads(f.read_text(encoding="utf-8"))
            out[rel] = md5(json.dumps({k: v.get("status") for k, v in st.items() if isinstance(v, dict)}, sort_keys=True).encode())
        elif f.suffix == ".json":
            out[rel] = md5(f.read_bytes())
        elif tier == "A" and not is_final_image(rel, exempt):
            out[rel] = md5(f.read_bytes())
        else:
            out[rel] = png_size(f) if f.suffix == ".png" else (list(__import__("PIL.Image", fromlist=["x"]).open(f).size) if f.suffix == ".jpg" else md5(f.read_bytes()))
    return out


def environment() -> dict:
    from pipeline.common import versions
    env = versions()
    try:
        env["fontlist_md5"] = md5(subprocess.run("fc-list | sort", shell=True, capture_output=True, text=True).stdout.encode())
    except Exception:
        env["fontlist_md5"] = None
    return env


class _Chromium:
    def __init__(self, real, extra):
        self._real, self._extra = real, extra

    def launch(self, **kw):
        kw["args"] = list(kw.get("args") or []) + self._extra
        return self._real.launch(**kw)

    def __getattr__(self, k):
        return getattr(self._real, k)


class _PW:
    def __init__(self, extra):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.chromium = _Chromium(self._pw.chromium, extra)

    def stop(self):
        self._pw.stop()


def run_all(tier: str) -> dict:
    import pipeline.step3_layout as L
    from pipeline.common import load_config
    from pipeline.assets import AssetLib
    from pipeline.orchestrator import PageRunner
    real = L.sync_playwright
    if tier == "A":
        class _Shim:
            def start(self):
                return _PW(DETERMINISTIC_FLAGS)
        L.sync_playwright = lambda: _Shim()
    res = {}
    try:
        for cfg_rel, seeds in SEEDS["configs"].items():
            cfg = load_config(ROOT / cfg_rel)
            run = ROOT / "runs" / ("_gate_" + tier + "_" + pathlib.Path(cfg_rel).stem)
            shutil.rmtree(run, ignore_errors=True)
            with L.Renderer() as r:
                pr = PageRunner(cfg, run, r, AssetLib(cfg["assets_dir"], skip=cfg.get("skip_assets", [])))
                for s in seeds:
                    pr.run(s)
            res[cfg_rel] = hash_run(run, tier)
            shutil.rmtree(run, ignore_errors=True)
    finally:
        L.sync_playwright = real
    return res


def compare(gold_files: dict, now: dict, tier: str) -> list:
    bad = []
    for cfg_rel, files in gold_files.items():
        cur = now.get(cfg_rel, {})
        for rel, h in files.items():
            if cur.get(rel) != h:
                bad.append(f"[tier {tier}] {cfg_rel}: {rel} " + ("MISSING" if rel not in cur else "CHANGED"))
        for rel in cur:
            if rel not in files:
                bad.append(f"[tier {tier}] {cfg_rel}: {rel} NEW FILE")
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--fast", action="store_true", help="Tier A only")
    a = ap.parse_args()
    tiers = ["A"] if a.fast and not a.record else ["A", "B"]
    now = {t: run_all(t) for t in tiers}
    if a.record:
        GOLDEN.write_text(json.dumps({"env": environment(), "seeds": SEEDS["configs"], "flags_A": DETERMINISTIC_FLAGS,
                                      "files_A": now["A"], "files_B": now["B"]}, indent=1), encoding="utf-8")
        print("recorded", sum(len(v) for t in now.values() for v in t.values()), "entries ->", GOLDEN)
        sys.exit(0)
    gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = []
    for t in tiers:
        bad += compare(gold["files_" + t], now[t], t)
    n = sum(len(v) for t in tiers for v in gold["files_" + t].values())
    env_now = environment()
    drift = {k: (gold["env"].get(k), env_now.get(k)) for k in env_now if gold["env"].get(k) != env_now.get(k)}
    if drift:
        print("NOTE: environment differs from the recording machine:", drift)
    if bad:
        print(f"GATE FAILED: {len(bad)} difference(s) out of {n} entries")
        for b in bad[:25]:
            print(" ", b)
        sys.exit(1)
    pages = sum(len(v) for v in SEEDS["configs"].values())
    print(f"GATE PASSED (tiers {'+'.join(tiers)}): {n} entries identical across {pages} pages")
