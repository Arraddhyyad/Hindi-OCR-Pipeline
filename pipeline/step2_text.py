"""STEP 2 - text: TemplateWriter (offline) or GeminiWriter (async, retries, cache) turns the entity graph into paragraphs; every required fact is verified verbatim.
"""
import asyncio, hashlib, json, random, re
from dataclasses import dataclass, field
from pathlib import Path
from .step1_entities import required_facts


@dataclass
class Doc:
    paragraphs: list
    writer: str = "template"
    attempts: int = 1
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(p["text"] for p in self.paragraphs)

    @property
    def n_words(self) -> int:
        return len(self.text.split())


def missing_facts(graph: dict, doc: Doc) -> list:
    t = doc.text
    return [f for f in required_facts(graph) if f not in t]


def _full(p, with_age=True):
    rel_title = "श्री"
    s = f"{p['title']} {p['name']} {p['relation']} {rel_title} {p['relative']}"
    return s


class TemplateWriter:
    name = "template"

    def write(self, g: dict, rng: random.Random, target_words: int = 260) -> Doc:
        S, B = _full(g["seller"]), _full(g["buyer"])
        v, t, d = g["village"], g["tehsil"], g["district"]
        bd = g["boundaries"]
        obj = "भूमि" if g["property_type"] == "agricultural" else "आवासीय भूखंड"
        addr = f"निवासी ग्राम {v}, तहसील {t}, जनपद {d}"

        def pick(*opts):
            return rng.choice(opts)

        title = {"kind": "title", "text": pick("विक्रय पत्र (बैनामा)", "बैनामा", "विक्रय पत्र")}
        pre = pick(
            f"यह विक्रय पत्र आज दिनांक {g['date']} को {g['place']} में {S}, आयु लगभग {g['seller']['age']} वर्ष, {addr} "
            f"(जिन्हें आगे “विक्रेता” कहा गया है) की ओर से {B}, आयु लगभग {g['buyer']['age']} वर्ष, {addr} "
            f"(जिन्हें आगे “क्रेता” कहा गया है) के पक्ष में निष्पादित किया जाता है।",
            f"दिनांक {g['date']} को {g['place']} में यह बैनामा {S}, {addr} (आगे “विक्रेता”) द्वारा "
            f"{B}, {addr} (आगे “क्रेता”) को लिखा गया है।")
        prop = pick(
            f"विक्रेता ग्राम {v}, तहसील {t}, जनपद {d} में स्थित {g['property_label']}, क्षेत्रफल {g['area']} की {obj} का "
            f"एकमात्र स्वामी एवं काबिज दखलकार है, जिसकी चौहद्दी इस प्रकार है: पूर्व में {bd['पूर्व']}, पश्चिम में {bd['पश्चिम']}, "
            f"उत्तर में {bd['उत्तर']} तथा दक्षिण में {bd['दक्षिण']} की भूमि।",
            f"उक्त {obj} ग्राम {v}, तहसील {t}, जनपद {d} में {g['property_label']} पर स्थित है और इसका क्षेत्रफल {g['area']} है। "
            f"इसकी चौहद्दी पूर्व में {bd['पूर्व']}, पश्चिम में {bd['पश्चिम']}, उत्तर में {bd['उत्तर']} और दक्षिण में {bd['दक्षिण']} है।")
        cons = pick(
            f"विक्रेता ने उक्त संपत्ति का सौदा क्रेता से कुल रुपये {g['amount_text']} (अक्षरे {g['amount_words']}) में तय किया है। "
            f"उक्त धनराशि का भुगतान क्रेता ने विक्रेता को {g['payment']} द्वारा आज इस विक्रय पत्र के निष्पादन के समय कर दिया है, "
            f"जिसे विक्रेता ने प्राप्त कर लिया है।",
            f"उक्त संपत्ति का विक्रय मूल्य रुपये {g['amount_text']} ({g['amount_words']}) निर्धारित हुआ, जो {g['payment']} के रूप में "
            f"विक्रेता को प्राप्त हो चुका है। अब क्रेता से कोई धनराशि पाना शेष नहीं है।")
        rights = pick(
            "अतः आज से उक्त संपत्ति पर विक्रेता का समस्त स्वत्व, अधिकार एवं कब्जा समाप्त हो गया और क्रेता उक्त संपत्ति का पूर्ण स्वामी हो गया। "
            "क्रेता को उक्त संपत्ति को अपनी इच्छानुसार बेचने, दान देने, बंधक रखने अथवा किसी भी प्रकार से हस्तांतरित करने का पूर्ण अधिकार होगा।",
            "आज से उक्त संपत्ति में विक्रेता का कोई हक या हिस्सा शेष नहीं रहा। क्रेता उसका पूर्ण स्वामी होकर उसे अपनी इच्छानुसार "
            "बेचने या हस्तांतरित करने का अधिकारी होगा।")
        expenses = f"इस विक्रय पत्र पर स्टाम्प शुल्क रुपये {g['stamp_duty']} का भुगतान किया गया है तथा पंजीकरण आदि का समस्त व्यय क्रेता द्वारा वहन किया गया है।"
        w1, w2 = g["witnesses"]
        closing = (f"यह विक्रय पत्र विक्रेता ने ताकि सनद रहे और समय पर काम आए, लिख दिया है। साक्षीगण: (1) {w1['name']}, निवासी ग्राम "
                   f"{w1['village']}; (2) {w2['name']}, निवासी ग्राम {w2['village']}।")

        optional = {
            "own": pick("उक्त संपत्ति विक्रेता को पारिवारिक उत्तराधिकार में प्राप्त हुई थी और तब से विक्रेता का उस पर निर्बाध स्वामित्व एवं कब्जा चला आ रहा है।",
                        "उक्त संपत्ति विक्रेता की स्वअर्जित संपत्ति है और इसमें किसी अन्य व्यक्ति का कोई हिस्सा या अधिकार नहीं है।"),
            "poss": "विक्रेता ने उक्त संपत्ति का भौतिक कब्जा आज ही क्रेता को सौंप दिया है।",
            "enc": "विक्रेता घोषणा करता है कि उक्त संपत्ति किसी भी प्रकार के भार, बंधक, कुर्की, न्यायालय के आदेश अथवा वाद से मुक्त है तथा इसका कोई अंश "
                   "किसी अन्य व्यक्ति को पूर्व में बेचा, दान किया अथवा बंधक नहीं रखा गया है।",
            "ind": "यदि भविष्य में उक्त संपत्ति पर किसी व्यक्ति द्वारा कोई दावा किया जाता है अथवा कोई भार प्रकट होता है, तो उसका निराकरण विक्रेता "
                   "स्वयं अपने व्यय पर करेगा तथा क्रेता को होने वाली समस्त हानि की पूर्ति करेगा।",
            "tax": "उक्त संपत्ति का भू-राजस्व एवं अन्य सरकारी देय आज की तिथि तक विक्रेता द्वारा चुकता किया जा चुका है; आज के बाद का समस्त देय क्रेता वहन करेगा।",
            "mut": "क्रेता को अधिकार होगा कि वह राजस्व अभिलेखों में अपना नाम दर्ज कराने हेतु दाखिल-खारिज की कार्यवाही कराए, जिस पर विक्रेता को कोई आपत्ति नहीं होगी।",
            "eas": "उक्त संपत्ति तक पहुँचने का मार्ग पूर्व की भाँति यथावत् रहेगा तथा क्रेता को उसके प्रयोग का पूर्ण अधिकार होगा।",
            "vol": "यह विक्रय पत्र विक्रेता ने अपने पूरे होश-हवास में, बिना किसी दबाव, भय या प्रलोभन के स्वेच्छा से लिखा एवं लिखाया है।",
        }
        slot = {"own": 0, "enc": 0, "poss": 2, "tax": 2, "mut": 2, "eas": 2, "ind": 2, "vol": 2}
        order = list(slot)
        rng.shuffle(order)
        words = sum(len(x.split()) for x in [pre, prop, cons, rights, expenses, closing]) + 3
        chosen = []
        for k in order:
            if words >= target_words:
                break
            chosen.append(k)
            words += len(optional[k].split())
        before = [optional[k] for k in chosen if slot[k] == 0]
        after = [optional[k] for k in chosen if slot[k] == 2]
        body = [pre, prop] + before + [cons, rights] + after + [expenses, closing]
        paras = [title] + [{"kind": "body", "text": b} for b in body]
        return Doc(paras, writer=self.name)


def write_compact(g: dict, rng: random.Random) -> Doc:
    """Short-form deed (about 90 words) for pages set in very large type. Same facts, fewer clauses. Used by v2 only; TemplateWriter.write is untouched."""
    S, B = _full(g["seller"]), _full(g["buyer"])
    bd = g["boundaries"]; obj = "भूमि" if g["property_type"] == "agricultural" else "आवासीय भूखंड"
    addr = f"निवासी ग्राम {g['village']}, तहसील {g['tehsil']}, जनपद {g['district']}"
    w1, w2 = g["witnesses"]
    body = [f"दिनांक {g['date']} को {S}, {addr} (विक्रेता) ने {B} (क्रेता) को यह बैनामा लिखा।",
            f"{g['property_label']}, क्षेत्रफल {g['area']} की {obj}। चौहद्दी: पूर्व में {bd['पूर्व']}, पश्चिम में {bd['पश्चिम']}, उत्तर में {bd['उत्तर']}, दक्षिण में {bd['दक्षिण']}।",
            f"विक्रय मूल्य रुपये {g['amount_text']} ({g['amount_words']}), {g['payment']} द्वारा प्राप्त।",
            f"स्टाम्प शुल्क रुपये {g['stamp_duty']}। साक्षी: (1) {w1['name']}, (2) {w2['name']}।"]
    title = {"kind": "title", "text": rng.choice(["विक्रय पत्र", "बैनामा"])}
    return Doc([title] + [{"kind": "body", "text": b} for b in body], writer="template-compact")


# ----------------------------------------------------------------------------- Gemini
PROMPT = """You are drafting a formal Hindi property sale deed (बैनामा / विक्रय पत्र) of Uttar Pradesh, as training data for OCR models.

FACTS (JSON). Every string listed under "must_appear" has to appear in your text EXACTLY as written, character for character, including digits and punctuation:
{facts}

RULES
- Write in formal legal Hindi in Devanagari. Do not translate or transliterate the facts.
- Do not invent any other names, dates, numbers, places or amounts.
- Use roughly {target} words in total. Short paragraphs, as in a real deed. No bullet characters.
- Include: title, preamble naming both parties, property description with boundaries, price and payment, transfer of rights, stamp duty and expenses, and a closing clause naming the witnesses. Add other usual clauses (ownership history, possession, no encumbrance, indemnity, mutation, easement, voluntary execution) if needed to reach the length.
- Vary phrasing and clause order from document to document. Variation seed: {seed}.
{retry}
Return ONLY JSON: {{"paragraphs": [{{"kind": "title" | "body", "text": "..."}}]}}"""


class GeminiWriter:
    name = "gemini"

    def __init__(self, model: str, client=None, api_key: str | None = None, concurrency: int = 32,
                 max_attempts: int = 3, max_api_retries: int = 6, cache_dir: str | None = None, temperature: float = 0.9):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self.client, self.model = client, model
        self.sem = asyncio.Semaphore(concurrency)
        self.max_attempts, self.max_api_retries, self.temperature = max_attempts, max_api_retries, temperature
        self.cache = Path(cache_dir) if cache_dir else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)

    def _prompt(self, g, seed, target, missing):
        facts = json.dumps({"must_appear": required_facts(g), "graph": g}, ensure_ascii=False, indent=1)
        retry = ("\nYour previous draft was missing these exact strings. Include every one verbatim: " + " | ".join(missing)) if missing else ""
        return PROMPT.format(facts=facts, target=target, seed=seed, retry=retry)

    async def _call(self, prompt: str) -> str:
        key = hashlib.sha256((self.model + prompt).encode()).hexdigest()
        if self.cache and (self.cache / f"{key}.json").exists():
            return (self.cache / f"{key}.json").read_text(encoding="utf-8")
        for i in range(1, self.max_api_retries + 1):
            try:
                async with self.sem:
                    r = await self.client.aio.models.generate_content(
                        model=self.model, contents=prompt,
                        config={"response_mime_type": "application/json", "temperature": self.temperature})
                text = r.text
                if self.cache:
                    (self.cache / f"{key}.json").write_text(text, encoding="utf-8")
                return text
            except Exception as e:  # transient: rate limit, 5xx, network
                if type(e).__name__ in ("InvalidArgument", "PermissionDenied", "Unauthenticated", "NotFound") or i == self.max_api_retries:
                    raise
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(e))
                await asyncio.sleep(float(m.group(1)) if m else min(60, 2 ** i) + random.random())

    async def awrite(self, g: dict, seed: int, target_words: int = 260) -> Doc:
        missing, last = None, None
        for attempt in range(1, self.max_attempts + 1):
            raw = await self._call(self._prompt(g, seed, target_words, missing))
            try:
                paras = json.loads(raw)["paragraphs"]
                paras = [{"kind": p.get("kind", "body"), "text": p["text"].strip()} for p in paras if p.get("text", "").strip()]
            except (ValueError, KeyError, TypeError):
                missing = ["(output was not valid JSON in the required shape)"]
                continue
            doc = Doc(paras, writer=self.name, attempts=attempt)
            missing = missing_facts(g, doc)
            last = doc
            if not missing:
                return doc
        raise RuntimeError(f"Gemini draft failed fact check after {self.max_attempts} attempts; missing: {missing}")

    def write(self, g, rng, target_words=260):
        return asyncio.run(self.awrite(g, rng.randrange(10**9), target_words))
