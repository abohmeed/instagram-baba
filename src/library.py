"""The pre-rendered image library.

Every image the account will ever post is rendered up front, in one build, and
committed to the repo. The daily job then does no image work at all: it picks
an entry that is already public, and calls the Graph API. That removes the
stock-photo API, the renderer, fonts and a git push from the daily critical
path, and it lets you review the whole library before a single post goes out.

Layout:
    docs/library/<profile>/<id>-<ref>.jpg   the images (public, served by raw)
    state/<profile>/library.json            manifest: id -> ref, caption, credit
    state/<profile>/history.json            what has actually been posted

A build is an "edition". Rebuilding replaces the previous edition's files so
the working tree holds exactly one library rather than growing without bound.
"""
import json
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from . import background, caption as caption_mod, content, render

ROOT = Path(__file__).resolve().parents[1]


def manifest_path(profile) -> Path:
    return ROOT / "state" / profile.name / "library.json"


def library_dir(profile) -> Path:
    return ROOT / profile["publish"].get("library_dir", "docs/library") / profile.name


def load(profile) -> dict:
    path = manifest_path(profile)
    if not path.exists():
        raise RuntimeError(
            f"No library for {profile.name}. Build one first:\n"
            f"  python -m src.library --profile {profile.name} --build"
        )
    data = json.loads(path.read_text("utf-8"))
    if not data.get("items"):
        raise RuntimeError(f"Library manifest at {path} is empty.")
    return data


def save(profile, data: dict) -> Path:
    path = manifest_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return path


def cycle_state(profile, manifest: dict, history: dict) -> dict:
    """Where we are in the current pass through the library."""
    posted = [p for p in history.get("posts", []) if p.get("status") == "posted"]
    size = len(manifest["items"])
    done = len(posted)
    return {
        "size": size,
        "posted_total": done,
        "cycle": done // size if size else 0,
        "used_in_cycle": done % size if size else 0,
        "remaining": size - (done % size) if size else 0,
        "complete": bool(size) and done > 0 and done % size == 0,
    }


def choose(profile, manifest: dict, history: dict, rng: random.Random | None = None) -> dict:
    """Pick an entry not yet used in the current pass through the library."""
    rng = rng or random.Random()
    state = cycle_state(profile, manifest, history)
    posted = [p for p in history.get("posts", []) if p.get("status") == "posted"]
    cycle_start = state["cycle"] * state["size"]
    used = {p.get("library_id") for p in posted[cycle_start:]}

    candidates = [i for i in manifest["items"] if i["id"] not in used]
    if not candidates:
        candidates = list(manifest["items"])
    return rng.choice(candidates)


def build(profile, per_verse: int = 1, rng: random.Random | None = None,
          keep_existing: bool = False) -> dict:
    """Render the whole library and write the manifest."""
    rng = rng or random.Random()
    pool = content.load_pool(profile.pool_path)
    target = len(pool) * max(1, per_verse)

    out_dir = library_dir(profile)
    previous = load(profile) if manifest_path(profile).exists() else None
    edition = (previous or {}).get("edition", 0) + 1

    if out_dir.exists() and not keep_existing:
        # One library on disk at a time, so the working tree stays bounded.
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building edition {edition} for {profile.name}: "
          f"{len(pool)} verses x {per_verse} = {target} images")

    print(f"  collecting {target} backgrounds from "
          f"{profile['background'].get('provider')}...")
    photos = background.collect(profile, target, rng)
    print(f"  got {len(photos)} distinct photos")
    if len(photos) < target:
        print(f"  ! only {len(photos)} available; backgrounds will repeat")

    items, failures = [], []
    started = time.time()
    index = 0
    for round_no in range(max(1, per_verse)):
        order = list(pool)
        rng.shuffle(order)
        for verse in order:
            index += 1
            item_id = f"{index:04d}"
            photo = photos[(index - 1) % len(photos)]
            try:
                image = background.download(photo, profile)
                reference = caption_mod.reference_text(profile, verse)
                composed = render.compose(profile, verse, image, reference)
                out_path = out_dir / f"{item_id}-{verse['ref'].replace(':', '_')}.jpg"
                render.save(composed, out_path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{verse['ref']}: {exc}")
                continue

            items.append({
                "id": item_id,
                "ref": verse["ref"],
                "theme": verse.get("theme", ""),
                "surah_name": verse.get("surah_name", ""),
                "file": str(out_path.relative_to(ROOT)),
                "caption": caption_mod.build(profile, verse, rng),
                "background": {
                    "provider": photo.get("provider"),
                    "id": photo.get("id"),
                    "query": photo.get("query"),
                    "author": photo.get("author"),
                    "author_url": photo.get("author_url"),
                    "link": photo.get("link"),
                    # Kept so the library can be re-rendered later without the
                    # stock API: CDN downloads aren't metered by the API key,
                    # but recovering this URL from a photo id costs one API
                    # call each, which for 310 images is worse than a rebuild.
                    "url": photo.get("url"),
                    "file": photo.get("file"),
                },
            })
            if index % 25 == 0:
                rate = index / max(time.time() - started, 1)
                print(f"  {index}/{target} rendered ({rate:.1f}/s)")

    if not items:
        raise RuntimeError("Library build produced no images. " + "; ".join(failures[:3]))

    data = {
        "profile": profile.name,
        "edition": edition,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "per_verse": per_verse,
        "count": len(items),
        "items": items,
    }
    save(profile, data)

    total_mb = sum((ROOT / i["file"]).stat().st_size for i in items) / 1_048_576
    print(f"\nEdition {edition}: {len(items)} images, {total_mb:.0f} MB")
    if failures:
        print(f"{len(failures)} failed:")
        for f in failures[:10]:
            print(f"  {f}")
    return data


def rerender(profile, rng: random.Random | None = None) -> dict:
    """Redraw every image on its existing background, with no stock API calls.

    For text and layout changes - a new dedication line, a font tweak, an
    edited caption - where the photographs should stay as they are. Downloads
    come from the provider's CDN, which the API rate limit does not cover.
    """
    rng = rng or random.Random()
    manifest = load(profile)
    pool = {v["ref"]: v for v in content.load_pool(profile.pool_path)}

    without_source = [i for i in manifest["items"]
                      if not (i["background"].get("url") or i["background"].get("file"))]
    if without_source:
        raise RuntimeError(
            f"{len(without_source)} of {len(manifest['items'])} entries predate "
            f"background URLs being recorded, so they cannot be re-rendered "
            f"without re-fetching from the API. Run a full --build instead; "
            f"from then on --rerender will work."
        )

    print(f"Re-rendering {len(manifest['items'])} images on their existing backgrounds")
    started, failures = time.time(), []
    for n, item in enumerate(manifest["items"], 1):
        verse = pool.get(item["ref"])
        if verse is None:
            failures.append(f"{item['ref']}: no longer in the pool")
            continue
        try:
            image = background.download(item["background"], profile)
            composed = render.compose(
                profile, verse, image, caption_mod.reference_text(profile, verse)
            )
            render.save(composed, ROOT / item["file"])
            item["caption"] = caption_mod.build(profile, verse, rng)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{item['ref']}: {exc}")
            continue
        if n % 25 == 0:
            print(f"  {n}/{len(manifest['items'])} "
                  f"({n / max(time.time() - started, 1):.1f}/s)")

    manifest["rerendered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(profile, manifest)
    print(f"\nRe-rendered {len(manifest['items']) - len(failures)} images "
          f"(edition {manifest['edition']} kept)")
    if failures:
        print(f"{len(failures)} failed:")
        for f in failures[:10]:
            print(f"  {f}")
    return manifest


def main(argv=None) -> int:
    import argparse
    from . import profile as profile_mod

    parser = argparse.ArgumentParser(description="Build or inspect the image library.")
    parser.add_argument("--profile")
    parser.add_argument("--build", action="store_true", help="render the library")
    parser.add_argument("--rerender", action="store_true",
                        help="redraw on the existing backgrounds (no stock API calls)")
    parser.add_argument("--per-verse", type=int, default=1,
                        help="images per verse (different backgrounds)")
    parser.add_argument("--status", action="store_true",
                        help="show library size and where the cycle is")
    parser.add_argument("--rebuild-if-complete", action="store_true",
                        help="rebuild only when the current cycle has finished")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    profile_mod.load_dotenv()
    prof = profile_mod.load(args.profile)
    rng = random.Random(args.seed)

    if args.status or args.rebuild_if_complete:
        history = content.load_history(ROOT / "state" / prof.name / "history.json")
        try:
            manifest = load(prof)
        except RuntimeError as exc:
            print(exc)
            if args.rebuild_if_complete:
                build(prof, args.per_verse, rng)
                return 0
            return 1
        state = cycle_state(prof, manifest, history)
        print(f"Library  : edition {manifest['edition']}, {state['size']} images")
        print(f"Built    : {manifest['built_at']}")
        print(f"Posted   : {state['posted_total']} total, "
              f"{state['used_in_cycle']} in this cycle")
        print(f"Remaining: {state['remaining']} before it recycles")
        if args.rebuild_if_complete:
            if state["complete"]:
                print("\nCycle complete - rebuilding with fresh backgrounds.")
                build(prof, manifest.get("per_verse", 1), rng)
            else:
                print("\nCycle still running - nothing to do.")
        return 0

    if args.rerender:
        rerender(prof, rng)
        return 0

    if args.build:
        build(prof, args.per_verse, rng)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
