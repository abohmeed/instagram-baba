"""Decide whether *now* is this profile's randomly-chosen posting moment.

GitHub Actions cron cannot fire at a random time, so the workflow runs hourly
and this module picks one deterministic-but-unpredictable target time per local
day. Every run before the target is a no-op; the first run at or after it posts.
Because the target is derived from the date (and an optional secret salt), all
runs on the same day agree on it even though nothing is stored between runs.
"""
import hashlib
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def local_now(profile) -> datetime:
    return datetime.now(ZoneInfo(profile["timezone"]))


def target_time(profile, now: datetime) -> datetime:
    window = profile["post_window"]
    start, end = int(window["start_hour"]), int(window["end_hour"])
    if not 0 <= start < end <= 24:
        raise RuntimeError(f"Invalid post_window {start}-{end} for {profile.name}")

    salt = os.environ.get("SCHEDULE_SALT", "")
    seed = f"{profile.name}|{now.date().isoformat()}|{salt}"
    digest = hashlib.sha256(seed.encode()).digest()

    span_minutes = (end - start) * 60
    offset = int.from_bytes(digest[:4], "big") % span_minutes

    return now.replace(
        hour=start + offset // 60,
        minute=offset % 60,
        second=0,
        microsecond=0,
    )


def is_due(profile, now: datetime | None = None) -> tuple[bool, datetime, datetime]:
    """Return (due, now, target) in the profile's local timezone."""
    now = now or local_now(profile)
    target = target_time(profile, now)
    return now >= target, now, target
