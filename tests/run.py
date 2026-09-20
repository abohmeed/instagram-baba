#!/usr/bin/env python3
"""Dependency-free test runner:  python -m tests.run"""
import json
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import caption, content, library, profile as profile_mod  # noqa: E402
from src import render, safety, schedule  # noqa: E402
from src.arabic import normalise, to_arabic_digits  # noqa: E402

RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


def check(condition, message):
    if not condition:
        raise AssertionError(message)


# --------------------------------------------------------------------------- safety
@test
def safety_blocks_punishment():
    check(not safety.is_safe("إِنَّ عَذَابِي لَشَدِيدٌ"), "should block عذاب")
    check(not safety.is_safe("خَـٰلِدِينَ فِي جَهَنَّمَ"), "should block جهنم")
    check(not safety.is_safe("أَصْحَـٰبُ ٱلنَّارِ"), "should block النار")


@test
def safety_allows_gentle_text():
    check(safety.is_safe("فَإِنَّ مَعَ ٱلْعُسْرِ يُسْرًا"), "94:5 must pass")
    check(safety.is_safe("وَرَحْمَتِى وَسِعَتْ كُلَّ شَىْءٍ"), "mercy must pass")


@test
def safety_exceptions_avoid_false_positives():
    # تبارك contains تبار; مغاضبا contains غضب; تأثيما contains اثيم.
    check(safety.is_safe("فَتَبَارَكَ ٱللَّهُ رَبُّ ٱلْعَـٰلَمِينَ"), "تبارك is not تبار")
    check(safety.is_safe("وَذَا ٱلنُّونِ إِذ ذَّهَبَ مُغَـٰضِبًا"), "مغاضبا is not غضب")
    check(safety.is_safe("لَا يَسْمَعُونَ فِيهَا لَغْوًا وَلَا تَأْثِيمًا"), "تأثيما is not اثيم")


@test
def normalise_folds_forms():
    check(normalise("ٱلْخَـٰسِرِينَ") == "الخسرين", normalise("ٱلْخَـٰسِرِينَ"))
    check(to_arabic_digits("17-20") == "١٧-٢٠", to_arabic_digits("17-20"))


# ----------------------------------------------------------------------------- pool
@test
def pool_is_clean():
    prof = profile_mod.load("mahmoudelfakharany8")
    pool = content.load_pool(prof.pool_path)
    check(len(pool) >= 250, f"pool is suspiciously small: {len(pool)}")

    seen = set()
    for item in pool:
        for field in ("ref", "text", "text_plain", "surah_name", "ayah_start", "ayah_end"):
            check(field in item, f"{item.get('ref')} missing {field}")
        verdict = safety.check(item["text_plain"])
        check(not verdict["blocked"], f"{item['ref']} contains {verdict['blocked']}")
        check(item["text_plain"] not in seen, f"duplicate text at {item['ref']}")
        seen.add(item["text_plain"])
        check(item["ayah_end"] >= item["ayah_start"], f"{item['ref']} reversed range")


# ------------------------------------------------------------------------- schedule
@test
def schedule_target_is_inside_the_window():
    prof = profile_mod.load("mahmoudelfakharany8")
    tz = ZoneInfo(prof["timezone"])
    lo, hi = prof["post_window"]["start_hour"], prof["post_window"]["end_hour"]
    for day in range(1, 29):
        now = datetime(2026, 3, day, 12, 0, tzinfo=tz)
        target = schedule.target_time(prof, now)
        check(lo <= target.hour < hi, f"{target} outside {lo}-{hi}")
        check(target.date() == now.date(), "target drifted to another day")


@test
def schedule_is_stable_within_a_day_and_varies_across_days():
    prof = profile_mod.load("mahmoudelfakharany8")
    tz = ZoneInfo(prof["timezone"])
    a = schedule.target_time(prof, datetime(2026, 5, 4, 9, 0, tzinfo=tz))
    b = schedule.target_time(prof, datetime(2026, 5, 4, 20, 0, tzinfo=tz))
    check(a == b, "target must not change between runs on the same day")

    targets = {
        schedule.target_time(prof, datetime(2026, 5, d, 12, 0, tzinfo=tz)).strftime("%H:%M")
        for d in range(1, 29)
    }
    check(len(targets) > 20, f"targets not spread out enough: {sorted(targets)}")


@test
def schedule_differs_between_profiles():
    a = profile_mod.load("mahmoudelfakharany8")
    b = profile_mod.load("example-english")
    tz = ZoneInfo(a["timezone"])
    same = sum(
        schedule.target_time(a, datetime(2026, 6, d, 12, 0, tzinfo=tz)).hour
        == schedule.target_time(b, datetime(2026, 6, d, 12, 0, tzinfo=ZoneInfo(b["timezone"]))).hour
        for d in range(1, 29)
    )
    check(same < 20, "two accounts should not share a posting schedule")


# -------------------------------------------------------------------------- caption
@test
def caption_renders_and_fits():
    prof = profile_mod.load("mahmoudelfakharany8")
    pool = content.load_pool(prof.pool_path)
    rng = random.Random(1)
    for item in pool:
        text = caption.build(prof, item, rng)
        check(len(text) <= caption.MAX_CAPTION, f"{item['ref']} caption too long")
        check(item["text"] in text, f"{item['ref']} verse missing from caption")
        check(item["surah_name"] in text, f"{item['ref']} surah name missing")
        check(text.count("#") <= caption.MAX_HASHTAGS, "too many hashtags")


@test
def caption_uses_arabic_numerals_for_ranges():
    prof = profile_mod.load("mahmoudelfakharany8")
    pool = {v["ref"]: v for v in content.load_pool(prof.pool_path)}
    ref = caption.reference_text(prof, pool["88:17-20"])
    check("١٧-٢٠" in ref, ref)
    check("الآيات" in ref, ref)


# -------------------------------------------------------------------------- content
@test
def selection_does_not_repeat_within_a_cycle():
    pool = [{"ref": f"1:{i}", "text": f"t{i}"} for i in range(12)]
    history = {"posts": []}
    rng = random.Random(3)
    picked = []
    for _ in range(len(pool)):
        item = content.choose(pool, history, rng)
        picked.append(item["ref"])
        content.record(history, {"ref": item["ref"], "status": "posted", "date": "x"})
    check(len(set(picked)) == len(pool), f"repeated inside one cycle: {picked}")

    # The next pick starts a fresh cycle rather than running out.
    nxt = content.choose(pool, history, rng)
    check(nxt["ref"] in {p["ref"] for p in pool}, "cycle did not reset")


@test
def failed_posts_do_not_consume_a_verse():
    pool = [{"ref": "1:1", "text": "a"}, {"ref": "1:2", "text": "b"}]
    history = {"posts": [{"ref": "1:1", "status": "pending", "date": "x"}]}
    picks = {content.choose(pool, history, random.Random(i))["ref"] for i in range(20)}
    check(picks == {"1:1", "1:2"}, f"pending post should not be excluded: {picks}")


# --------------------------------------------------------------------------- render
@test
def render_produces_a_correctly_sized_jpeg():
    prof = profile_mod.load("mahmoudelfakharany8")
    pool = {v["ref"]: v for v in content.load_pool(prof.pool_path)}
    bg = Image.new("RGB", (1600, 900), (40, 60, 45))

    for ref in ("94:5-6", "7:23", "2:255"):
        item = pool[ref]
        image = render.compose(prof, item, bg, caption.reference_text(prof, item))
        check(image.size == (prof["image"]["width"], prof["image"]["height"]),
              f"{ref} wrong size: {image.size}")
        with tempfile.TemporaryDirectory() as tmp:
            out = render.save(image, Path(tmp) / "x.jpg")
            size_kb = out.stat().st_size / 1024
            # Instagram rejects images over 8 MB.
            check(size_kb < 8000, f"{ref} image too large: {size_kb:.0f} KB")


@test
def long_text_still_fits_the_canvas():
    prof = profile_mod.load("mahmoudelfakharany8")
    pool = content.load_pool(prof.pool_path)
    longest = max(pool, key=lambda v: v["chars"])
    cfg = prof["image"]
    box = (int(cfg["width"] * cfg["text_box"]["width_pct"]),
           int(cfg["height"] * cfg["text_box"]["height_pct"]))
    font, lines, line_height = render._layout(longest["text"], cfg, box, "rtl", "ar")
    check(len(lines) * line_height <= box[1] + line_height,
          f"{longest['ref']} overflows: {len(lines)} lines")
    check(font.size >= cfg["min_font_size"], "font shrank below the floor")


@test
def the_dedication_never_collides_with_the_verse():
    """The bottom line sits in a fixed margin; long verses must clear it."""
    prof = profile_mod.load("mahmoudelfakharany8")
    cfg = prof["image"]
    if not cfg.get("signature"):
        return
    pool = content.load_pool(prof.pool_path)
    box = (int(cfg["width"] * cfg["text_box"]["width_pct"]),
           int(cfg["height"] * cfg["text_box"]["height_pct"]))
    sig_top = cfg["height"] - cfg["height"] * 0.075 - cfg["signature_size"] * 0.7
    gap = cfg["height"] * cfg.get("reference_gap_pct", 0.05)
    ref_lh = cfg["reference_size"] * 1.4

    worst = None
    for verse in pool:
        font, lines, lh = render._layout(verse["text"], cfg, box, "rtl", "ar")
        group = len(lines) * lh + gap + ref_lh
        bottom = (cfg["height"] - group) / 2 + group
        slack = sig_top - bottom
        if worst is None or slack < worst[1]:
            worst = (verse["ref"], slack)
    check(worst[1] > 0, f"{worst[0]} overlaps the dedication by {-worst[1]:.0f}px")


# ----------------------------------------------------------------------- providers
@test
def a_provider_list_skips_sources_with_no_key():
    import os

    from src import background

    prof = profile_mod.load("mahmoudelfakharany8")
    prof.data["background"] = {**prof["background"],
                               "provider": ["unsplash", "pexels", "pixabay"]}
    saved = {k: os.environ.pop(k, None)
             for k in ("UNSPLASH_ACCESS_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY")}
    try:
        background.collect(prof, 10, random.Random(1))
    except RuntimeError as exc:
        check("no API keys" in str(exc), f"should name the real problem: {exc}")
    else:
        check(False, "expected a clear error when no provider has a key")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


@test
def every_provider_is_reachable_by_name():
    from src import background

    for name in ("unsplash", "pexels", "pixabay"):
        check(name in background.PROVIDERS, f"{name} missing from PROVIDERS")
        check(callable(background.PROVIDERS[name]), f"{name} is not callable")


# -------------------------------------------------------------------------- library
def _fake_manifest(n: int) -> dict:
    return {"profile": "t", "edition": 1, "count": n, "per_verse": 1,
            "items": [{"id": f"{i:04d}", "ref": f"1:{i}", "file": f"f{i}.jpg",
                       "caption": "c"} for i in range(1, n + 1)]}


@test
def library_cycle_visits_every_image_once():
    prof = profile_mod.load("mahmoudelfakharany8")
    manifest = _fake_manifest(20)
    history = {"posts": []}
    rng = random.Random(11)

    picked = []
    for _ in range(20):
        item = library.choose(prof, manifest, history, rng)
        picked.append(item["id"])
        content.record(history, {"library_id": item["id"], "ref": item["ref"],
                                 "status": "posted", "date": "d"})
    check(len(set(picked)) == 20, f"repeated within a cycle: {sorted(picked)}")

    state = library.cycle_state(prof, manifest, history)
    check(state["complete"], f"cycle should be complete: {state}")
    check(state["remaining"] == 20, f"remaining should reset: {state}")

    # Next pick starts cycle 2 rather than running dry.
    nxt = library.choose(prof, manifest, history, rng)
    check(nxt["id"] in {i["id"] for i in manifest["items"]}, "cycle did not restart")


@test
def library_cycle_state_tracks_position():
    prof = profile_mod.load("mahmoudelfakharany8")
    manifest = _fake_manifest(10)
    history = {"posts": [{"library_id": f"{i:04d}", "ref": "1:1", "status": "posted",
                          "date": "d"} for i in range(1, 4)]}
    state = library.cycle_state(prof, manifest, history)
    check(state["used_in_cycle"] == 3, state)
    check(state["remaining"] == 7, state)
    check(not state["complete"], state)


@test
def rerender_refuses_when_backgrounds_cannot_be_recovered():
    """Without a stored source URL a re-render would silently need 310 API calls."""
    prof = profile_mod.load("mahmoudelfakharany8")
    manifest = _fake_manifest(3)
    for item in manifest["items"]:
        item["background"] = {"provider": "unsplash", "id": "abc"}  # no url
    original_load = library.load
    library.load = lambda _p: manifest
    try:
        library.rerender(prof)
    except RuntimeError as exc:
        check("--build" in str(exc), f"should point at a full build: {exc}")
    else:
        check(False, "expected a RuntimeError when no background URL is stored")
    finally:
        library.load = original_load


@test
def a_built_library_records_its_background_urls():
    """Guards the field that makes --rerender possible at all."""
    prof = profile_mod.load("mahmoudelfakharany8")
    path = library.manifest_path(prof)
    if not path.exists():
        return  # nothing built in this checkout
    import json as _json
    items = _json.loads(path.read_text("utf-8"))["items"]
    missing = [i["id"] for i in items
               if not (i["background"].get("url") or i["background"].get("file"))]
    check(not missing,
          f"{len(missing)}/{len(items)} library entries have no recoverable background; "
          f"a text-only change would need a full rebuild")


@test
def library_reports_a_useful_error_when_missing():
    prof = profile_mod.load("example-english")
    try:
        library.load(prof)
    except RuntimeError as exc:
        check("--build" in str(exc), f"error should say how to fix it: {exc}")
    else:
        check(False, "expected a RuntimeError for a missing library")


@test
def a_missing_library_does_not_fail_the_daily_run():
    """The hourly job must not email the owner once a day before the first build."""
    import argparse

    from src import main as main_mod

    prof = profile_mod.load("example-english")  # has no library
    args = argparse.Namespace(live=False, force=True, push=False)
    check(main_mod.cmd_run(prof, args) == 0, "a missing library must exit 0, not 1")


@test
def library_paths_land_under_docs():
    prof = profile_mod.load("mahmoudelfakharany8")
    directory = library.library_dir(prof)
    check(directory.name == prof.name, directory)
    check("docs/library" in str(directory), directory)


# -------------------------------------------------------------------------- profile
@test
def profiles_are_valid():
    for path in sorted((ROOT / "profiles").glob("*.json")):
        prof = profile_mod.load(path.stem)
        check(prof.name == path.stem, f"{path.stem}: name mismatch")
        check(0 <= prof["post_window"]["start_hour"] < prof["post_window"]["end_hour"] <= 24,
              f"{path.stem}: bad post_window")
        ZoneInfo(prof["timezone"])
        for key in ("ig_user_id", "ig_access_token"):
            check(key in prof["secrets"], f"{path.stem}: missing secret mapping {key}")
        font = ROOT / prof["image"]["font"]
        check(font.exists(), f"{path.stem}: font not found at {font}")


@test
def public_urls_point_at_the_repo():
    import os
    os.environ["GITHUB_REPOSITORY"] = "someone/instagram-baba"
    os.environ["GITHUB_REF_NAME"] = "main"
    prof = profile_mod.load("mahmoudelfakharany8")
    url = prof.public_url_for(library.library_dir(prof) / "0001-2_255.jpg")
    check(url.startswith("https://raw.githubusercontent.com/someone/instagram-baba/main/"), url)
    check(url.endswith("docs/library/mahmoudelfakharany8/0001-2_255.jpg"), url)


def main() -> int:
    failures = []
    for fn in RESULTS:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append((fn.__name__, exc))
            print(f"  FAIL  {fn.__name__}: {exc}")
    print()
    print(f"{len(RESULTS) - len(failures)}/{len(RESULTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
