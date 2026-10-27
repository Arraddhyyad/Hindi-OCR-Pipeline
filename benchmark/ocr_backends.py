"""OCR tools behind one interface: backend.read(image_path) -> text.
fake_perfect / fake_noisy exist so the benchmark itself can be tested without any OCR installed."""
import random
import subprocess


class FakePerfect:
    name = "fake_perfect"

    def __init__(self, answers=None):
        self.answers = answers or {}

    def read(self, image_path):
        return self.answers.get(str(image_path), "")


class FakeNoisy(FakePerfect):
    """Drops or swaps characters at a fixed rate. Not an OCR model: only for testing the scoring."""
    name = "fake_noisy"

    def __init__(self, answers=None, rate=0.1, seed=0):
        super().__init__(answers)
        self.rate, self.rng = rate, random.Random(seed)

    def read(self, image_path):
        out = []
        for ch in super().read(image_path):
            r = self.rng.random()
            if ch != " " and r < self.rate / 2:
                continue
            out.append("क" if (ch != " " and r < self.rate) else ch)
        return "".join(out)


class Tesseract:
    """Needs the tesseract program and its Hindi model (hin). psm 3 = automatic page layout."""
    def __init__(self, lang="hin", psm=3):
        self.lang, self.psm = lang, psm
        self.name = f"tesseract_{lang}_psm{psm}"

    def read(self, image_path):
        r = subprocess.run(["tesseract", str(image_path), "-", "-l", self.lang, "--psm", str(self.psm)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:300])
        return r.stdout


class EasyOCR:
    """Needs `pip install easyocr` (pulls in torch). Lines are put in reading order by position."""
    name = "easyocr_hi_en"

    def __init__(self):
        import easyocr
        self.reader = easyocr.Reader(["hi", "en"], gpu=False, verbose=False)

    def read(self, image_path):
        res = self.reader.readtext(str(image_path))   # [(box, text, conf)]
        if not res:
            return ""
        items = sorted(((min(q[1] for q in b), min(q[0] for q in b), t) for b, t, _ in res))
        lines, cur, line_y = [], [], None
        for y, x, t in items:
            if line_y is not None and y - line_y > 25:   # a new text line starts about 25 px lower
                lines.append(" ".join(w for _, w in sorted(cur)))
                cur = []
                line_y = None
            if line_y is None:
                line_y = y
            cur.append((x, t))
        if cur:
            lines.append(" ".join(w for _, w in sorted(cur)))
        return "\n".join(lines)


def get_backend(name, answers=None, **kw):
    if name == "fake_perfect":
        return FakePerfect(answers)
    if name == "fake_noisy":
        return FakeNoisy(answers, **kw)
    if name == "tesseract":
        return Tesseract(**kw)
    if name == "easyocr":
        return EasyOCR()
    raise ValueError(f"unknown backend {name!r}. Choose: fake_perfect, fake_noisy, tesseract, easyocr")
