#!/usr/bin/env python3
"""Daily post runner.

    python -m src.main --profile mahmoudelfakharany8 --dry-run
    python -m src.main --profile mahmoudelfakharany8 --preview 3
    python -m src.main --profile mahmoudelfakharany8 --check-token
    python -m src.main --profile mahmoudelfakharany8            # live

Posting is opt-in: without --live (or LIVE=true) the run renders the image and
prints the caption but never touches Instagram.
"""
import argparse
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import requests

from . import background, caption as caption_mod, content, profile as profile_mod
from . import publish as publish_mod, render, schedule

ROOT = Path(__file__).resolve().parents[1]


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def push_to_repo(paths: list, message: str) -> bool:
    """Commit and push the rendered image + state so the URL goes public."""
    rel = [str(p.relative_to(ROOT)) for p in paths]
    add = _git("add", "--", *rel)
    if add.returncode != 0:
        print(f"  ! git add failed: {add.stderr.strip()}")
        return False

    status = _git("status", "--porcelain", "--", *rel)
    if not status.stdout.strip():
        print("  nothing new to commit")
        return True

    if os.environ.get("CI"):
        _git("config", "user.name", os.environ.get("GIT_USER_NAME", "quran-poster-bot"))
        _git("config", "user.email",
             os.environ.get("GIT_USER_EMAIL", "actions@users.noreply.github.com"))

    commit = _git("commit", "-m", message)
    if commit.returncode != 0:
        print(f"  ! git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
        return False

    for attempt in range(3):
        push = _git("push")
        if push.returncode == 0:
            return True
        print(f"  ! git push attempt {attempt + 1} failed: {push.stderr.strip()}")
        _git("pull", "--rebase")
        time.sleep(3)
    return False


def wait_for_url(url: str, attempts: int = 20, delay: int = 6) -> bool:
    """Poll until the pushed image is actually served."""
    for attempt in range(attempts):
        try:
            r = requests.get(url, timeout=20, stream=True)
            if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
                return True
        except Exception:  # noqa: BLE001
            pass
        if attempt == 0:
            print(f"  waiting for {url} to go live...")
        time.sleep(delay)
    return False


def render_one(profile, item: dict, rng: random.Random, out_path: Path) -> dict:
    bg, credit = background.fetch(profile, rng)
    src = credit.get("file") or f"{credit.get('provider')}:{credit.get('id')}"
    print(f"  background: {src} ({credit.get('query', '-')})")

    reference = caption_mod.reference_text(profile, item)
    image = render.compose(profile, item, bg, reference)
    render.save(image, out_path)
    print(f"  image: {out_path.relative_to(ROOT)}  ({out_path.stat().st_size // 1024} KB)")
    return credit


def cmd_preview(profile, args) -> int:
    pool = content.load_pool(profile.pool_path)
    rng = random.Random(args.seed)
    out_dir = ROOT / "out" / profile.name
    picks = rng.sample(pool, min(args.preview, len(pool)))
    for i, item in enumerate(picks, 1):
        print(f"\n[{i}/{len(picks)}] {item['ref']}  {item.get('theme', '')}")
        path = out_dir / f"preview-{i:02d}-{item['ref'].replace(':', '_')}.jpg"
        render_one(profile, item, rng, path)
        text = caption_mod.build(profile, item, rng)
        path.with_suffix(".txt").write_text(text, "utf-8")
    print(f"\nWrote {len(picks)} previews to {out_dir.relative_to(ROOT)}")
    return 0


def cmd_check_token(profile) -> int:
    info = publish_mod.check_token(profile)
    print(f"  account  : @{info.get('username')} ({info.get('name')})")
    print(f"  ig_user  : {info.get('id')}")
    print(f"  media    : {info.get('media_count')}   followers: {info.get('followers_count')}")
    print(f"  token    : {info.get('token_days_left')} days left")
    print(f"  scopes   : {', '.join(info.get('token_scopes') or []) or 'unknown'}")
    days = info.get("token_days_left")
    if isinstance(days, (int, float)) and days < 14:
        print("\n  ! Token expires soon - refresh it (see SETUP.md, step 7).")
        return 1
    return 0


def cmd_run(profile, args) -> int:
    live = args.live or _env_flag("LIVE")
    mode = "LIVE" if live else "DRY RUN"
    print(f"Profile: {profile.name}   [{mode}]")

    due, now, target = schedule.is_due(profile)
    local_date = now.date().isoformat()
    print(f"  now    : {now:%Y-%m-%d %H:%M} {profile['timezone']}")
    print(f"  target : {target:%H:%M}")

    history = content.load_history(profile.state_path)
    already = content.posted_on(history, local_date)
    if already and not args.force:
        print(f"  already posted today: {already['ref']} -> {already.get('permalink', '')}")
        return 0

    if not due and not args.force:
        print("  not due yet - exiting quietly")
        return 0

    pool = content.load_pool(profile.pool_path)
    rng = random.Random()
    item = content.choose(pool, history, rng)
    print(f"  verse  : {item['ref']}  {item.get('surah_name', '')}  ({item.get('theme', '')})")

    # A dry run stays out of docs/, which is the published archive.
    out_dir = profile.posts_dir if live else ROOT / "out" / profile.name
    out_path = out_dir / f"{local_date}-{item['ref'].replace(':', '_')}.jpg"
    credit = render_one(profile, item, rng, out_path)

    text = caption_mod.build(profile, item, rng)
    print("\n--- caption ---")
    print(text)
    print("---------------\n")

    if not live:
        preview = ROOT / "out" / profile.name / f"{local_date}-caption.txt"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(text, "utf-8")
        print("Dry run: nothing posted. Pass --live (or set LIVE=true) to publish.")
        return 0

    entry = {
        "date": local_date,
        "ref": item["ref"],
        "theme": item.get("theme", ""),
        "image": str(out_path.relative_to(ROOT)),
        "background": credit,
        "status": "pending",
    }

    if args.push:
        message = f"post({profile.name}): {local_date} {item['ref']}"
        if not push_to_repo([out_path], message):
            print("  ! could not publish the image to the repo; aborting")
            return 1

    image_url = profile.public_url_for(out_path)
    print(f"  url    : {image_url}")
    if args.push and not wait_for_url(image_url):
        print("  ! image URL never became reachable; aborting before Instagram sees it")
        return 1

    result = publish_mod.post(profile, image_url, text)
    entry.update(status="posted", url=image_url, **result)
    print(f"  posted : {result.get('permalink') or result['media_id']}")

    content.record(history, entry)
    content.save_history(profile.state_path, history)

    if args.push:
        push_to_repo([profile.state_path], f"state({profile.name}): {local_date} posted")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Post a daily verse image to Instagram.")
    parser.add_argument("--profile", help="profile name in profiles/ (or set PROFILE)")
    parser.add_argument("--live", action="store_true", help="actually post (default: dry run)")
    parser.add_argument("--force", action="store_true",
                        help="ignore the schedule and the already-posted-today check")
    parser.add_argument("--no-push", dest="push", action="store_false", default=True,
                        help="don't commit/push the image (needs another public URL)")
    parser.add_argument("--preview", type=int, metavar="N",
                        help="render N sample images without posting or recording")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for --preview")
    parser.add_argument("--check-token", action="store_true",
                        help="verify Instagram credentials and token lifetime")
    args = parser.parse_args(argv)
    profile_mod.load_dotenv()

    try:
        prof = profile_mod.load(args.profile)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.check_token:
            return cmd_check_token(prof)
        if args.preview:
            return cmd_preview(prof, args)
        return cmd_run(prof, args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
