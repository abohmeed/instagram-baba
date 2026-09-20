"""Content safety net for the verse pool.

The account is a memorial and must stay gentle: nothing about Hell, punishment,
or divine wrath. The curated allowlist in data/allowlist.json is the primary
control; these rules are the second line of defence that runs over the fetched
text, so a mistaken reference gets caught instead of posted.

Matching happens on normalised text (diacritics stripped, alef/yeh/teh-marbuta
folded) via src.arabic.normalise.
"""
import re

from .arabic import normalise

# Hard block: if any of these appear, the passage never enters the pool.
BLOCK_TERMS = [
    # Names of the Fire
    "جهنم", "النار", "نارا", "بالنار", "سعير", "السعير", "لظى", "الحطمه",
    "سقر", "الجحيم", "هاويه", "الزقوم", "زقوم", "غساق", "صديد", "مقامع",
    # Punishment / torment
    "عذاب", "العذاب", "عذابي", "يعذب", "نعذب", "معذب", "العقاب", "عقاب",
    "نكال", "انتقام", "منتقمون", "وبال", "تبار", "خزي", "مهين", "اليم",
    "اثيم", "رجز", "طبع الله", "اغلال", "سلاسل", "يصلي", "يصلون", "صالوا",
    "تصليه", "حطمه", "موبقا", "بيس المصير", "بيس", "ساءت", "سوء الدار",
    # Wrath / cursing / destruction
    "غضب", "المغضوب", "لعن", "لعنه", "ملعون", "اهلك", "اهلكنا", "فاهلكناهم",
    "دمر", "دمرنا", "صاعقه", "الصاعقه", "خسفنا", "اغرقنا", "الطوفان",
    "فاخذناهم", "اخذ عزيز مقتدر", "بطش", "البطشه", "شديد المحال",
]

# Not about punishment, but not suitable as a standalone inspirational post:
# legal rulings, battle narrative, polemic, or anything that needs the
# surrounding passage to be read fairly. Used by discover.py when proposing new
# candidates; the curated allowlist can still include one deliberately.
CONTEXT_TERMS = [
    # war and conflict
    "قتال", "قتلوا", "يقتلون", "فاقتلوا", "الحرب", "جهاد", "نفروا", "الصف",
    "غزو", "اسري", "غنمتم", "الانفال", "اسلحتهم", "زحفا", "هزموهم",
    # legal / ritual minutiae
    "طلقتم", "الطلاق", "عدتهن", "المحيض", "ايلاء", "الميراث", "يوصيكم",
    "فريضه", "الزاني", "الزانيه", "جلده", "السارق", "السارقه", "القصاص",
    "الربا", "الخمر", "الميسر", "الانصاب", "الازلام", "تيمموا", "الجزيه",
    "نكحتم", "فانكحوا", "المطلقات", "ظاهر", "الايمن", "كفاره",
    # polemic and named groups
    "اليهود", "النصاري", "المنافقون", "المنافقين", "المشركون", "اهل الكتاب",
    "الاعراب", "بني اسراييل", "السامري", "ابي لهب",
    # narrative that needs its story
    "فرعون", "هامان", "قارون", "ثمود", "عاد", "مدين", "الايكه", "تبع",
    "النمل", "الهدهد", "سبا", "ياجوج", "ماجوج", "الرقيم", "طالوت", "جالوت",
    "ابرهه", "الفيل", "بدر", "حنين", "احد",
    # claims about disbelief/hypocrisy that read badly alone
    "لا يومنون", "كذبوا", "المكذبين", "يصدون", "استهزي", "سخروا",
    "الذين كفروا", "كفروا", "يشركون", "شركاء", "انداد", "من دون الله",
    "تدعون من دون", "اوثن", "اصنام", "يجحدون", "يفترون", "زعمتم",
    # pronouns with no antecedent in a standalone post
    "اوليك", "هولاء", "بعضهم", "فريق منهم", "منهم من", "فيهم",
    # rhetorical challenges aimed at an audience the post doesn't have
    "فاني يوفكون", "افمن", "ام من", "يسلونك", "زعم", "بزعمهم",
]


# Soft flag: legitimate in context but worth a human glance before it goes live.
FLAG_TERMS = [
    "حميم",      # a close friend (41:34) - but also scalding water elsewhere
    "الكافرين", "كفروا", "الظالمين", "المنافقين", "المشركين",
    "قتل", "قتلوا", "الموت", "ميت", "يموت",
    "خسر", "الخاسرين",
]


# Words that innocently contain a blocked substring. Matching is deliberately
# substring-based (over-blocking is the safe failure mode for this account), so
# these specific, verified word forms are excised before the check runs.
EXCEPTIONS = [
    "تبارك", "تباركت",        # "blessed is..." - contains تبار
    "مغاضبا", "مغضبا",         # "having left in anger" (21:87) - contains غضب
    "تاثيما",                  # "no sinful speech" (56:25) - contains اثيم
    "الانار", "انار",          # "he illuminated" - contains نار
    "مستنير",
]

_ARABIC = "\u0621-\u064A"


# Proclitics that attach to the front of an Arabic word (wa-, fa-, bi-, ka-,
# li-, al-), so "فتبارك" is recognised as the exception "تبارك".
_PROCLITIC = "[\u0648\u0641\u0628\u0643\u0644]{0,2}(?:\u0627\u0644)?"


def _strip_exceptions(norm: str) -> str:
    for word in EXCEPTIONS:
        norm = re.sub(
            f"(?<![{_ARABIC}]){_PROCLITIC}{re.escape(word)}(?![{_ARABIC}])", " ", norm
        )
    return norm


def _hits(text: str, terms) -> list:
    norm = _strip_exceptions(normalise(text))
    return [t for t in terms if t in norm]


def check(text: str) -> dict:
    """Return {'blocked': [...], 'flagged': [...]} for a passage."""
    return {"blocked": _hits(text, BLOCK_TERMS), "flagged": _hits(text, FLAG_TERMS)}


def needs_context(text: str) -> list:
    """Terms suggesting the passage can't stand alone as a post."""
    return _hits(text, CONTEXT_TERMS)


def is_safe(text: str) -> bool:
    return not _hits(text, BLOCK_TERMS)
