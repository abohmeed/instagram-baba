#!/usr/bin/env python3
"""Build content/quran/verses.json from content/quran/allowlist.json.

Quranic text is NEVER hand-written in this repo. It is fetched from the
Quran.com API v4 (Uthmani/Hafs script), with alquran.cloud as a fallback, then
passed through src/safety.py before it is allowed into the pool.

Run:  python content/quran/build_pool.py
Then: read content/quran/pool_review.txt and confirm every passage is one
      you're happy to see on the account.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

PACK = Path(__file__).resolve().parent
ROOT = PACK.parents[1]
sys.path.insert(0, str(ROOT))

from src.safety import check  # noqa: E402

QURAN_API = "https://api.quran.com/api/v4"
FALLBACK_API = "https://api.alquran.cloud/v1"
AYAH_MARK = "۝"  # END OF AYAH sign; encloses the following digits
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

session = requests.Session()
session.headers["User-Agent"] = "instagram-baba/1.0 (+quran verse poster)"


def arabic_number(n: int) -> str:
    return "".join(ARABIC_DIGITS[int(d)] for d in str(n))


def fetch_chapters() -> dict:
    r = session.get(f"{QURAN_API}/chapters", params={"language": "ar"}, timeout=30)
    r.raise_for_status()
    out = {}
    for c in r.json()["chapters"]:
        out[c["id"]] = {
            "name_arabic": c["name_arabic"],
            "name_simple": c["name_simple"],
            "verses_count": c["verses_count"],
        }
    return out


def fetch_chapter_text(chapter: int) -> dict:
    """Return {ayah_number: uthmani_text} for one surah."""
    try:
        r = session.get(
            f"{QURAN_API}/quran/verses/uthmani",
            params={"chapter_number": chapter},
            timeout=30,
        )
        r.raise_for_status()
        out = {}
        for v in r.json()["verses"]:
            ayah = int(v["verse_key"].split(":")[1])
            out[ayah] = v["text_uthmani"].strip()
        if out:
            return out
    except Exception as exc:  # noqa: BLE001
        print(f"  ! quran.com failed for surah {chapter}: {exc}; trying fallback")

    r = session.get(f"{FALLBACK_API}/surah/{chapter}/quran-uthmani", timeout=30)
    r.raise_for_status()
    return {int(a["numberInSurah"]): a["text"].strip() for a in r.json()["data"]["ayahs"]}


def parse_ref(ref: str):
    m = re.fullmatch(r"(\d+):(\d+)(?:-(\d+))?", ref.strip())
    if not m:
        raise ValueError(f"bad reference: {ref!r}")
    chapter = int(m.group(1))
    start = int(m.group(2))
    end = int(m.group(3)) if m.group(3) else start
    if end < start:
        raise ValueError(f"reversed range: {ref!r}")
    return chapter, start, end


def main() -> int:
    allowlist = json.loads((PACK / "allowlist.json").read_text("utf-8"))
    refs = allowlist["refs"]

    print(f"Fetching chapter metadata...")
    chapters = fetch_chapters()

    needed = sorted({parse_ref(r["ref"])[0] for r in refs})
    print(f"Fetching Uthmani text for {len(needed)} surahs...")
    texts = {}
    for i, ch in enumerate(needed, 1):
        texts[ch] = fetch_chapter_text(ch)
        print(f"  [{i}/{len(needed)}] surah {ch} ({chapters[ch]['name_simple']})")
        time.sleep(0.15)

    pool, rejected, flagged = [], [], []
    seen = set()

    for entry in refs:
        ref = entry["ref"]
        chapter, start, end = parse_ref(ref)
        meta = chapters[chapter]

        if end > meta["verses_count"]:
            rejected.append((ref, f"surah {chapter} only has {meta['verses_count']} ayat"))
            continue

        ayahs = []
        for n in range(start, end + 1):
            if n not in texts[chapter]:
                rejected.append((ref, f"ayah {n} missing from source"))
                ayahs = []
                break
            ayahs.append((n, texts[chapter][n]))
        if not ayahs:
            continue

        plain = " ".join(t for _, t in ayahs)
        if len(ayahs) == 1:
            display = ayahs[0][1]
        else:
            parts = []
            for idx, (n, t) in enumerate(ayahs):
                parts.append(t)
                if idx < len(ayahs) - 1:
                    parts.append(AYAH_MARK + arabic_number(n))
            display = " ".join(parts)

        verdict = check(plain)
        if verdict["blocked"]:
            rejected.append((ref, "blocked terms: " + ", ".join(verdict["blocked"])))
            continue

        key = plain
        if key in seen:
            rejected.append((ref, "duplicate text of an earlier reference"))
            continue
        seen.add(key)

        record = {
            "ref": ref,
            "surah": chapter,
            "surah_name": meta["name_arabic"],
            "surah_slug": meta["name_simple"].lower().replace(" ", "-").replace("'", ""),
            "ayah_start": start,
            "ayah_end": end,
            "theme": entry.get("theme", ""),
            "text": display,
            "text_plain": plain,
            "chars": len(plain),
        }
        pool.append(record)
        if verdict["flagged"]:
            flagged.append((ref, ", ".join(verdict["flagged"])))

    pool.sort(key=lambda r: (r["surah"], r["ayah_start"]))

    out = {
        "source": "Quran.com API v4 - text_uthmani (Hafs)",
        "generated_by": "content/quran/build_pool.py",
        "count": len(pool),
        "verses": pool,
    }
    (PACK / "verses.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )

    lines = [
        "VERSE POOL REVIEW",
        "=" * 70,
        f"{len(pool)} passages accepted, {len(rejected)} rejected.",
        "Read every passage below. Delete any reference you don't want from",
        "allowlist.json and re-run content/quran/build_pool.py.",
        "",
    ]
    for r in pool:
        mark = "  [FLAGGED] " if any(f[0] == r["ref"] for f in flagged) else "  "
        lines.append(f"{r['ref']:<10} {r['surah_name']}  ({r['theme']}, {r['chars']} chars)")
        lines.append(f"{mark}{r['text_plain']}")
        lines.append("")

    if flagged:
        lines += ["", "FLAGGED FOR A SECOND LOOK (allowed, but check the context)", "-" * 70]
        lines += [f"{ref:<10} contains: {terms}" for ref, terms in flagged]
        lines.append("")

    if rejected:
        lines += ["", "REJECTED (not in the pool)", "-" * 70]
        lines += [f"{ref:<10} {why}" for ref, why in rejected]
        lines.append("")

    (PACK / "pool_review.txt").write_text("\n".join(lines), "utf-8")

    print()
    print(f"Accepted : {len(pool)}")
    print(f"Rejected : {len(rejected)}")
    print(f"Flagged  : {len(flagged)}")
    print()
    print("Wrote content/quran/verses.json and content/quran/pool_review.txt")
    if rejected:
        print("\nRejected references:")
        for ref, why in rejected:
            print(f"  {ref:<10} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
