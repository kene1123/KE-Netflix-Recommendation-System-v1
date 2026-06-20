import re
import unicodedata

CHAR_MAP: dict[str, str] = {
    "\u2018": "'",  "\u2019": "'",
    "\u201c": '"',  "\u201d": '"',
    "\u201a": "'",  "\u201e": '"',
    "\u2013": "-",  "\u2014": "-",  "\u2015": "-",
    "\u2026": "...",
    "\u00b7": ".",
    "\u00a0": " ",  "\u200b": "",  "\u200e": "",  "\u200f": "",  "\ufeff": "",
    "\u00e9": "e",  "\u00e8": "e",  "\u00ea": "e",  "\u00eb": "e",
    "\u00e0": "a",  "\u00e2": "a",  "\u00e4": "a",  "\u00e6": "ae",
    "\u00f9": "u",  "\u00fa": "u",  "\u00fb": "u",  "\u00fc": "u",
    "\u00ee": "i",  "\u00ef": "i",  "\u00ec": "i",  "\u00ed": "i",
    "\u00f4": "o",  "\u00f6": "o",  "\u00f8": "o",  "\u0153": "oe",
    "\u00f3": "o",  "\u00f2": "o",  "\u00f5": "o",
    "\u00e7": "c",  "\u00f1": "n",  "\u00e3": "a",  "\u00e1": "a",
    "\u00df": "ss",
    "\u00e5": "a",  "\u00c5": "A",
    "\u00f0": "d",  "\u00de": "Th", "\u00fe": "th",
    "\u0107": "c",  "\u010d": "c",  "\u0161": "s",  "\u017e": "z",
    "\u0144": "n",  "\u0142": "l",  "\u0159": "r",  "\u017c": "z",
    "\u00c9": "E",  "\u00c8": "E",  "\u00ca": "E",
    "\u00c0": "A",  "\u00c2": "A",  "\u00c4": "A",  "\u00c6": "AE",
    "\u00d6": "O",  "\u00dc": "U",  "\u00c7": "C",
    "\u00d1": "N",  "\u00d4": "O",  "\u00d3": "O",  "\u00c1": "A",
    "\u0152": "OE",
    "\u2122": "TM", "\u00ae": "(R)", "\u00a9": "(C)",
    "\u2605": "*",  "\u2606": "*",
}

_YEAR_RE    = re.compile(r"\((\d{4})\)\s*$")
_ARTICLE_RE = re.compile(
    r",\s*(The|A|An|Les|Le|La|L'|Der|Die|Das|Ein|El|Los|Las|Gli|I|Il|Os|As)\s*$",
    re.IGNORECASE,
)
_MULTI_SP  = re.compile(r"\s{2,}")
_NON_ASCII = re.compile(r"[^\x00-\x7F]")


def clean_text(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return raw or ""
    text = raw
    for src, dst in CHAR_MAP.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = _NON_ASCII.sub("", text)
    text = _MULTI_SP.sub(" ", text).strip()
    return text


def clean_title(raw: str) -> tuple[str, int | None]:
    if not isinstance(raw, str) or not raw.strip():
        return (raw or ""), None
    text = raw
    for src, dst in CHAR_MAP.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = _NON_ASCII.sub("", text)
    year: int | None = None
    m = _YEAR_RE.search(text)
    if m:
        year = int(m.group(1))
        text = text[: m.start()].strip()
    m = _ARTICLE_RE.search(text)
    if m:
        text = f"{m.group(1)} {text[: m.start()].strip()}"
    text = _MULTI_SP.sub(" ", text).strip()
    return text, year


def clean_genres(raw: str, separator: str = "|") -> str:
    if not isinstance(raw, str) or not raw.strip():
        return raw or ""
    parts = [clean_text(g.strip()) for g in raw.split(separator)]
    return separator.join(p for p in parts if p)


def audit_text(texts: list[str]) -> list[dict]:
    from collections import Counter
    freq: Counter = Counter()
    examples: dict[str, str] = {}
    for text in texts:
        if not isinstance(text, str):
            continue
        for ch in text:
            if ord(ch) > 127:
                freq[ch] += 1
                if ch not in examples:
                    examples[ch] = text.strip()
    results = []
    for ch, count in freq.most_common():
        try:
            name = unicodedata.name(ch)
        except ValueError:
            name = f"UNKNOWN (U+{ord(ch):04X})"
        action = f"-> '{CHAR_MAP[ch]}'" if ch in CHAR_MAP else "-> stripped via NFKD / removed"
        results.append({
            "char":          ch,
            "unicode_point": f"U+{ord(ch):04X}",
            "unicode_name":  name,
            "count":         count,
            "action":        action,
            "example":       examples.get(ch, ""),
        })
    return results

def whitespace_tokenizer(text: str) -> list[str]:
    return text.split()