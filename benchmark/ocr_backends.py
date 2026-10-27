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
        # Read raw bytes and decode as UTF-8 ourselves. text=True would use the Windows code page and crash on Devanagari.
        r = subprocess.run(["tesseract", str(image_path), "-", "-l", self.lang, "--psm", str(self.psm)],
                           capture_output=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[:300])
        return r.stdout.decode("utf-8", "replace")


class EasyOCR:
    """Needs `pip install easyocr` (pulls in torch). Lines are put in reading order by position."""
    name = "easyocr_hi_en"

    def __init__(self):
        import easyocr
        try:
            import torch
            use_gpu = torch.cuda.is_available()
        except Exception:
            use_gpu = False
        self.reader = easyocr.Reader(["hi", "en"], gpu=use_gpu, verbose=False)

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


class QwenVL:
    """A page-reading vision-language model from Hugging Face (needs a GPU; made for Colab).
    Default is a small Qwen model that fits a free T4. Bigger ones: pass model_id and load_4bit=True.
    The model reads the whole page and returns plain text. Slow: about a minute or more per dense page."""
    PROMPT = ("Read all the text in this image exactly as written. The text is Hindi (Devanagari). "
              "Output only the text, line by line in reading order. Do not translate, explain or summarise.")

    def __init__(self, model_id=None, max_new_tokens=3500, load_4bit=False):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        self.model_id = model_id or "Qwen/Qwen2.5-VL-3B-Instruct"
        self.name = "qwenvl_" + self.model_id.split("/")[-1]
        self.max_new_tokens = max_new_tokens
        kw = {"device_map": "auto"}
        if load_4bit:
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        else:
            kw["torch_dtype"] = torch.float16
        self.model = AutoModelForImageTextToText.from_pretrained(self.model_id, **kw)
        # a page is about 1300x1800 px: keep full resolution so small Hindi stays readable
        self.processor = AutoProcessor.from_pretrained(self.model_id, min_pixels=256 * 28 * 28, max_pixels=3_300_000)
        self.torch = torch

    def read(self, image_path):
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": self.PROMPT}]}]
        prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[prompt], images=[img], return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        new_tokens = out[:, inputs["input_ids"].shape[1]:]
        return self.processor.batch_decode(new_tokens, skip_special_tokens=True)[0]


def get_backend(name, answers=None, **kw):
    if name == "fake_perfect":
        return FakePerfect(answers)
    if name == "fake_noisy":
        return FakeNoisy(answers, **kw)
    if name == "tesseract":
        return Tesseract(**kw)
    if name == "easyocr":
        return EasyOCR()
    if name == "qwen_vl":
        return QwenVL(**kw)
    raise ValueError(f"unknown backend {name!r}. Choose: fake_perfect, fake_noisy, tesseract, easyocr, qwen_vl")
