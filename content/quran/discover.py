#!/usr/bin/env python3
"""Propose new candidate verses by scanning the whole Qur'an.

Curating hundreds of references from memory risks mistakes in scripture. This
instead reads every ayah from the Quran.com API and narrows it mechanically:

  1. drop anything the safety filter blocks (Fire, punishment, wrath)
  2. drop anything needing its surrounding passage to read fairly
     (legal rulings, battle narrative, polemic) - see safety.CONTEXT_TERMS
  3. keep only what renders well as artwork (a length window)
  4. rank what's left by how strongly it speaks of mercy, guidance, patience,
     gratitude, creation and du'a

The output is a *proposal*, never a pool. A human reads it and moves the good
ones into allowlist.json.

    python content/quran/discover.py --limit 400 > candidates.txt
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

PACK = Path(__file__).resolve().parent
ROOT = PACK.parents[1]
sys.path.insert(0, str(ROOT))

from src.arabic import normalise  # noqa: E402
from src.safety import check, needs_context  # noqa: E402

QURAN_API = "https://api.quran.com/api/v4"
CACHE = PACK / ".cache"

# Themes worth posting, weighted. Matched against normalised text.
THEMES = {
    "mercy": (3, ["رحمه", "رحيم", "الرحمن", "غفور", "غفار", "يغفر", "توبه", "تواب",
                  "عفو", "يعفو", "رووف", "حليم", "ودود"]),
    "guidance": (3, ["هدي", "يهدي", "المهتدون", "نور", "بينات", "الصراط", "رشد",
                     "بصاير", "الحكمه", "موعظه", "ذكري"]),
    "hope": (3, ["بشري", "يبشر", "المبشرين", "لا خوف", "لا تحزن", "لا تقنطوا",
                 "فرج", "يسرا", "اطمانت", "سكينه", "الفلاح", "المفلحون"]),
    "patience": (2, ["صبر", "الصابرين", "اصبر", "صابروا", "المصابره"]),
    "gratitude": (2, ["شكر", "الشاكرين", "اشكروا", "نعمه", "انعم", "فضل"]),
    "creation": (3, ["السموت", "الارض", "خلق", "ايات", "الشمس", "القمر", "النجوم",
                     "الجبال", "البحر", "الانهر", "المطر", "الرياح", "الليل",
                     "النهار", "الثمرت", "انبتنا", "زرع", "حدايق", "النحل",
                     "الطير", "الانعم", "السحاب", "الماء"]),
    "trust": (2, ["توكل", "المتوكلين", "حسبنا", "حسبه", "ولي", "نصير", "كفي بالله"]),
    "prayer": (3, ["ربنا", "رب اغفر", "رب زدني", "ادعوني", "دعا", "استجاب",
                   "قريب", "اقرب"]),
    "character": (2, ["الاحسان", "المحسنين", "العدل", "الصدق", "الصادقين", "امانه",
                      "العافين", "الكاظمين", "المتقين", "التقوي", "اصلحوا",
                      "تعاونوا", "معروف"]),
    "knowledge": (2, ["العلم", "يعلمون", "اولو الالبب", "يتفكرون", "يعقلون",
                      "يتدبرون", "اولي النهي"]),
    "reward": (2, ["الجنه", "جنت", "نعيم", "سلم", "رضوان", "رضي الله", "الحسني",
                   "اجرهم", "خير", "طوبي"]),
}


def load_quran() -> dict:
    """{(surah, ayah): text}, cached locally after the first run."""
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / "uthmani.json"
    if cache_file.exists():
        raw = json.loads(cache_file.read_text("utf-8"))
        return {tuple(int(x) for x in k.split(":")): v for k, v in raw.items()}

    session = requests.Session()
    session.headers["User-Agent"] = "instagram-baba/1.0"
    out = {}
    for chapter in range(1, 115):
        r = session.get(
            f"{QURAN_API}/quran/verses/uthmani",
            params={"chapter_number": chapter}, timeout=30,
        )
        r.raise_for_status()
        for v in r.json()["verses"]:
            s, a = (int(x) for x in v["verse_key"].split(":"))
            out[(s, a)] = v["text_uthmani"].strip()
        print(f"  fetched surah {chapter}/114", file=sys.stderr)
        time.sleep(0.12)

    cache_file.write_text(
        json.dumps({f"{s}:{a}": t for (s, a), t in out.items()},
                   ensure_ascii=False), "utf-8"
    )
    return out


def chapter_names() -> dict:
    r = requests.get(f"{QURAN_API}/chapters", params={"language": "ar"}, timeout=30)
    r.raise_for_status()
    return {c["id"]: c["name_arabic"] for c in r.json()["chapters"]}


def score(text: str) -> tuple:
    norm = normalise(text)
    total, hit = 0, []
    for theme, (weight, terms) in THEMES.items():
        matches = sum(1 for t in terms if t in norm)
        if matches:
            total += weight * matches
            hit.append(theme)
    return total, hit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--min-chars", type=int, default=55)
    parser.add_argument("--max-chars", type=int, default=340)
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    print("Loading Qur'an text...", file=sys.stderr)
    quran = load_quran()
    names = chapter_names()

    existing = {
        e["ref"] for e in json.loads((PACK / "allowlist.json").read_text("utf-8"))["refs"]
    }

    stats = {"blocked": 0, "context": 0, "length": 0, "score": 0, "existing": 0}
    candidates = []
    for (surah, ayah), text in quran.items():
        ref = f"{surah}:{ayah}"
        if ref in existing:
            stats["existing"] += 1
            continue
        if not (args.min_chars <= len(text) <= args.max_chars):
            stats["length"] += 1
            continue
        if check(text)["blocked"]:
            stats["blocked"] += 1
            continue
        if needs_context(text):
            stats["context"] += 1
            continue
        value, themes = score(text)
        if value < args.min_score:
            stats["score"] += 1
            continue
        candidates.append({
            "ref": ref, "surah_name": names[surah], "score": value,
            "themes": themes, "chars": len(text), "text": text,
        })

    candidates.sort(key=lambda c: (-c["score"], c["ref"]))
    candidates = candidates[:args.limit]

    print(f"\n{len(quran)} ayat scanned. Excluded: "
          f"{stats['blocked']} unsafe, {stats['context']} need context, "
          f"{stats['length']} wrong length, {stats['score']} off-theme, "
          f"{stats['existing']} already in the allowlist.", file=sys.stderr)
    print(f"{len(candidates)} candidates proposed.\n", file=sys.stderr)

    if args.json:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
    else:
        for c in candidates:
            print(f"{c['ref']:<9} [{c['score']:>2}] {'/'.join(c['themes'][:3]):<28} "
                  f"{c['surah_name']}")
            print(f"          {c['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
