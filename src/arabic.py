"""Arabic text helpers: normalisation for keyword matching, and shaping fallbacks."""
import re
import unicodedata

# Harakat, tanween, quranic annotation marks, superscript alef, tatweel.
_DIACRITICS = re.compile(
    "[" 
    "ؐ-ؚ"   # quranic honorifics
    "ً-ٟ"   # harakat / tanween
    "ٰ"          # superscript alef
    "ۖ-ۭ"   # small quranic marks, sajdah, waqf
    "ـ"          # tatweel
    "]"
)

_ALEF = re.compile("[آأإٱ]")   # آ أ إ ٱ
_YEH = re.compile("[ىی]")                 # ى ی
_WAW = re.compile("[ؤ]")                       # ؤ
_HEH = re.compile("[ة]")                       # ة


def strip_diacritics(text: str) -> str:
    """Remove all harakat and quranic marks, keeping the bare letters."""
    return _DIACRITICS.sub("", text)


def normalise(text: str) -> str:
    """Aggressive normalisation used only for keyword matching, never for display."""
    text = unicodedata.normalize("NFC", text)
    text = strip_diacritics(text)
    text = _ALEF.sub("ا", text)
    text = _YEH.sub("ي", text)
    text = _WAW.sub("و", text)
    text = _HEH.sub("ه", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def shape_fallback(text: str) -> str:
    """Manually shape + reorder Arabic for renderers without libraqm.

    Only used when Pillow was built without Raqm; Raqm does this correctly itself.
    """
    import arabic_reshaper
    from bidi.algorithm import get_display

    reshaper = arabic_reshaper.ArabicReshaper(
        configuration={"delete_harakat": False, "support_ligatures": True}
    )
    return get_display(reshaper.reshape(text))


ARABIC_INDIC = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"


def to_arabic_digits(value) -> str:
    """0-9 -> ٠-٩. Also sidesteps a bidi trap: a Latin range like "5-6" gets
    reordered to "6-5" inside right-to-left text, while Arabic-Indic digits
    keep their reading order."""
    return "".join(ARABIC_INDIC[int(c)] if c.isdigit() else c for c in str(value))


# Pause/recitation marks: useful when reciting, visual noise in artwork - and
# they strand awkwardly when a line break lands on one. U+06DD (end of ayah) is
# deliberately NOT in this set; it separates ayat in multi-verse passages.
_WAQF = re.compile(
    "["
    "\u06D6-\u06DC"   # small high ligature waqf signs (sala, qala, meem...)
    "\u06DE"           # start of rub el hizb
    "\u06E2"           # small high meem isolated form
    "\u06E9"           # place of sajdah
    "\u06EA-\u06ED"   # empty centre low/high stops, small low meem
    "]"
)


def strip_waqf(text: str) -> str:
    """Remove pause marks, keeping every letter and vowel."""
    return re.sub(r"\s{2,}", " ", _WAQF.sub("", text)).strip()
