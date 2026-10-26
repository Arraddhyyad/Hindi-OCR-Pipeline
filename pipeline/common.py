"""Shared plumbing: config loading, logging, versions, artifact saving."""
import json, logging, platform, sys, time
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config(path):
    cfg = yaml.safe_load(open(path, encoding="utf-8"))
    cfg["_config_path"] = str(path)
    if not Path(cfg["assets_dir"]).is_absolute():
        cfg["assets_dir"] = str(ROOT / cfg["assets_dir"])
    return cfg


def setup_logging(run_dir: Path, verbose=True):
    run_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("docgen"); log.setLevel(logging.DEBUG); log.handlers.clear()
    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8"); fh.setFormatter(logging.Formatter("%(asctime)s %(processName)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    if verbose:
        sh = logging.StreamHandler(sys.stdout); sh.setLevel(logging.INFO); sh.setFormatter(logging.Formatter("%(message)s")); log.addHandler(sh)
    return log


def versions():
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for m in ("numpy", "cv2", "PIL", "augraphy", "playwright", "yaml", "rapidfuzz", "google.genai"):
        try:
            mod = __import__(m, fromlist=["x"]); out[m] = getattr(mod, "__version__", "?")
        except Exception: out[m] = None
    return out


def dump_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
