"""STEP 8 - evaluation (scoring; later): OCR read-back (Gemini or fake), Indic-aware metrics, error taxonomy.
"""
import asyncio, hashlib, json, os, random, re, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from rapidfuzz.distance import Levenshtein

PROMPT = ("Transcribe all the text in this image exactly as written, in reading order, line by line. "
          "The document is in {lang}. Keep the original script and numerals. Do not translate, correct, summarise or add commentary. "
          "Output only the transcription.")

# ------------------------------------------------------------------ normalisation (keeps Devanagari combining marks!)
_P = re.compile(r"[^\w\sऀ-ॿ]", re.UNICODE)      # \w alone drops matras/viramas: Srinidhi's normalize() deleted them


def normalize(t: str, strip_punct=True) -> str:
    t = unicodedata.normalize("NFC", t).replace("‌", "").replace("‍", "")
    t = t.replace("।", ".").replace("॥", ".")
    if strip_punct: t = _P.sub("", t).replace("_", "")
    return re.sub(r"\s+", " ", t).strip()


def graphemes(s):
    """Orthographic units: base + following combining marks (and virama-joined conjuncts stay one unit)."""
    out, i = [], 0
    while i < len(s):
        j = i + 1
        while j < len(s) and (unicodedata.category(s[j]) in ("Mn", "Mc") or s[j - 1] == "्" or s[j] == "्"):
            j += 1
        out.append(s[i:j]); i = j
    return out


# ------------------------------------------------------------------ metrics
def cer(p, g): return Levenshtein.distance(p, g) / max(1, len(g))
def wer(p, g): return Levenshtein.distance(p.split(), g.split()) / max(1, len(g.split()))
def gcer(p, g): return Levenshtein.distance(graphemes(p), graphemes(g)) / max(1, len(graphemes(g)))


def token_f1(p, g):
    a, b = Counter(p.split()), Counter(g.split())
    c = sum((a & b).values())
    if not c: return float(not a and not b)
    pr, rc = c / sum(a.values()), c / sum(b.values()); return 2 * pr * rc / (pr + rc)


DEV, LAT = "०१२३४५६७८९", "0123456789"
def _digit_norm(s): return s.translate(str.maketrans(DEV, LAT))


def fact_recall(pred, facts):
    """Share of entity facts (names, amounts, dates, plot numbers...) that the OCR output contains verbatim / digit-normalised."""
    if not facts: return None
    p, pd = normalize(pred), _digit_norm(normalize(pred))
    hit = sum(1 for f in facts if normalize(f) in p or _digit_norm(normalize(f)) in pd)
    return hit / len(facts)


# ------------------------------------------------------------------ error classification
MATRAS = set("ािीुूृेैोौॅॉंँः")
def _kind(g, p):
    """Classify one substitution/ins/del between reference text g and prediction p (short strings)."""
    if not g and p: return "insertion"
    if g and not p: return "deletion"
    gd, pd = set(g) & set(DEV + LAT), set(p) & set(DEV + LAT)
    if (set(g) <= set(DEV + LAT + ".,/-") and set(p) <= set(DEV + LAT + ".,/-")) and (gd or pd):
        return "digit_script" if _digit_norm(g) == _digit_norm(p) else "digit_confusion"
    if "्" in g or "्" in p: return "conjunct_halant"
    if "़" in g or "़" in p: return "nukta"
    if any(c in MATRAS for c in g + p): return "matra"
    if g.isalpha() and p.isalpha() or True: return "consonant_vowel"


def classify(pred, gold):
    """Character-level alignment -> counts per error kind (+ word-level drops/hallucinated words)."""
    ops = Levenshtein.opcodes(gold, pred)
    c = Counter()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal": continue
        g, p = gold[i1:i2], pred[j1:j2]
        c[_kind(g, p)] += max(len(g), len(p))
    gw, pw = gold.split(), pred.split()
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(gw, pw):
        if tag == "delete" and i2 - i1 >= 3: c["line_or_block_dropped"] += i2 - i1
        if tag == "insert" and j2 - j1 >= 3: c["hallucinated_block"] += j2 - j1
    return c


def score(pred, rec_label, facts=None, ref_key="transcript"):
    g, p = normalize(rec_label[ref_key]), normalize(pred)
    return {"cer": cer(p, g), "gcer": gcer(p, g), "wer": wer(p, g), "token_f1": token_f1(p, g), "exact": int(p == g),
            "fact_recall": fact_recall(pred, facts), "errors": dict(classify(p, g)), "len_ratio": len(p) / max(1, len(g))}


# ------------------------------------------------------------------ OCR backends
class FakeOCR:
    """Offline stand-in: corrupts the true transcript with Indic-style errors, more when the page is more damaged."""
    def __init__(self, label_lookup, base=0.01): self.lookup, self.base = label_lookup, base

    async def read(self, image_bytes, mime="image/png", key=None):
        lab = self.lookup(key); rng = random.Random(key); sev = {"light": 1, "medium": 2, "heavy": 4}[lab["severity"]]
        out = []
        for ch in lab["transcript"]:
            r = rng.random()
            if r < self.base * sev * .35 and ch in MATRAS: continue
            if r < self.base * sev * .6 and ch in DEV: out.append(LAT[DEV.index(ch)]); continue
            if r < self.base * sev: out.append(rng.choice("कपमनरतस")); continue
            out.append(ch)
        t = "".join(out)
        if sev == 4 and rng.random() < .3: t = "\n".join(t.split("\n")[:-rng.randint(1, 3)])
        return t


class GeminiOCR:
    def __init__(self, model="gemini-2.5-flash", lang="Hindi", concurrency=8, cache_dir=None, max_retries=6, client=None):
        self.model, self.lang, self.max_retries = model, lang, max_retries
        self.sem = asyncio.Semaphore(concurrency); self.cache = Path(cache_dir) if cache_dir else None
        if self.cache: self.cache.mkdir(parents=True, exist_ok=True)
        if client is None:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.client = client

    async def read(self, image_bytes, mime="image/png", key=None):
        from google.genai import types
        prompt = PROMPT.format(lang=self.lang)
        ck = hashlib.sha256(self.model.encode() + prompt.encode() + image_bytes).hexdigest()
        if self.cache and (self.cache / f"{ck}.txt").exists(): return (self.cache / f"{ck}.txt").read_text(encoding="utf-8")
        for i in range(1, self.max_retries + 1):
            try:
                async with self.sem:
                    r = await self.client.aio.models.generate_content(
                        model=self.model, contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt],
                        config={"temperature": 0.0})
                text = (r.text or "").strip()
                if self.cache: (self.cache / f"{ck}.txt").write_text(text, encoding="utf-8")
                return text
            except Exception as e:
                if type(e).__name__ in ("InvalidArgument", "PermissionDenied", "Unauthenticated", "NotFound") or i == self.max_retries: raise
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(e))
                await asyncio.sleep(float(m.group(1)) if m else min(60, 2 ** i) + random.random())


# ------------------------------------------------------------------ runner + report
async def evaluate(ds_dir, ocr, split="test", limit=None, use_target=False, concurrency=8, facts_fn=None):
    ds = Path(ds_dir); labels = sorted((ds / split).glob("doc_*[0-9].json"))[:limit]
    sem = asyncio.Semaphore(concurrency); rows = []

    async def one(lp):
        lab = json.loads(lp.read_text(encoding="utf-8"))
        img = next((lp.with_suffix(e) for e in (".png", ".jpg") if lp.with_suffix(e).exists()), None)
        if use_target: img = lp.with_name(lp.stem + "_target.png")
        async with sem:
            pred = await ocr.read(img.read_bytes(), "image/jpeg" if img.suffix == ".jpg" else "image/png", key=lab["id"])
        s = score(pred, lab, lab.get('facts'))
        rows.append({"id": lab["id"], "severity": lab["severity"], "ops": lab["ops"], "pred": pred, **s})
    await asyncio.gather(*(one(p) for p in labels))
    return sorted(rows, key=lambda r: r["id"])


def summarize(rows):
    m = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    out = {"n": len(rows), "cer": m([r["cer"] for r in rows]), "gcer": m([r["gcer"] for r in rows]), "wer": m([r["wer"] for r in rows]),
           "token_f1": m([r["token_f1"] for r in rows]), "exact": m([r["exact"] for r in rows])}
    by = defaultdict(list)
    for r in rows: by[r["severity"]].append(r)
    out["by_severity"] = {k: {"n": len(v), "cer": m([x["cer"] for x in v]), "wer": m([x["wer"] for x in v])} for k, v in by.items()}
    ops = defaultdict(list)
    for r in rows:
        for o in set(r["ops"]): ops[o].append(r["cer"])
    base = out["cer"] or 0
    out["by_op_cer_delta"] = {o: {"n": len(v), "mean_cer": m(v), "delta_vs_all": round(m(v) - base, 4)} for o, v in sorted(ops.items()) if len(v) >= 2}
    tot = Counter()
    for r in rows: tot.update(r["errors"])
    s = sum(tot.values()) or 1
    out["error_types"] = {k: {"count": v, "share": round(v / s, 3)} for k, v in tot.most_common()}
    return out


# ------------------------------------------------------------------ helpers for calibration (added with v2; nothing above changed)
def prompt_sha(lang="Hindi"):
    """Hash of the exact OCR prompt, stored with every calibration result so a changed prompt cannot be mistaken for the same experiment."""
    return hashlib.sha256(PROMPT.format(lang=lang).encode()).hexdigest()[:12]


def list_gemini_models(client=None):
    """Names of the models this API key can use for generateContent (the ones that can read an image and answer in text)."""
    if client is None:
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    out = []
    for m in client.models.list():
        acts = getattr(m, "supported_actions", None) or []
        if not acts or "generateContent" in acts: out.append((m.name.replace("models/", ""), getattr(m, "display_name", "") or ""))
    return sorted(out)
