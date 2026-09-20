"""Content pool loading and non-repeating selection.

Generic: a "pool" is a JSON file with a list of records. Each record needs
`ref` and `text`; everything else (surah_name, theme, ...) is passed through to
the caption template, so a non-Quran pack works with the same code.
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path


def load_pool(path: Path) -> list:
    if not path.exists():
        raise RuntimeError(
            f"Content pool not found at {path}. Build it first "
            f"(e.g. python content/quran/build_pool.py)."
        )
    data = json.loads(path.read_text("utf-8"))
    items = data["verses"] if isinstance(data, dict) else data
    if not items:
        raise RuntimeError(f"Content pool at {path} is empty.")
    return items


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"posts": []}
    return json.loads(path.read_text("utf-8"))


def save_history(path: Path, history: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", "utf-8")


def posted_on(history: dict, local_date: str) -> dict | None:
    for post in history["posts"]:
        if post.get("date") == local_date and post.get("status") == "posted":
            return post
    return None


def choose(pool: list, history: dict, rng: random.Random | None = None) -> dict:
    """Pick an item that hasn't been posted in the current cycle.

    Once every item has been used the cycle resets, so the account never stops
    and never repeats until the whole pool has been through.
    """
    rng = rng or random.Random()
    used = {p["ref"] for p in history["posts"] if p.get("status") == "posted"}

    # A "cycle" is one full pass through the pool. Count how many complete
    # passes have happened and only exclude items used in the current pass.
    cycle_size = len(pool)
    posted_count = len([p for p in history["posts"] if p.get("status") == "posted"])
    cycle_index = posted_count // cycle_size if cycle_size else 0
    cycle_start = cycle_index * cycle_size
    current_cycle = {
        p["ref"]
        for p in [q for q in history["posts"] if q.get("status") == "posted"][cycle_start:]
    }

    candidates = [item for item in pool if item["ref"] not in current_cycle]
    if not candidates:
        candidates = list(pool)
    return rng.choice(candidates)


def record(history: dict, entry: dict) -> dict:
    entry.setdefault("recorded_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    history["posts"].append(entry)
    return history
