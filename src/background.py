"""Background image sourcing.

Providers are pluggable via profile.background.provider. Every provider falls
back to the profile's local fallback_dir so a post is never skipped just
because a stock API had a bad day.
"""
import io
import random
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30


class BackgroundError(RuntimeError):
    pass


def _download(url: str, headers: dict | None = None) -> Image.Image:
    r = requests.get(url, headers=headers or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def _unsplash(profile, query: str, rng: random.Random) -> tuple[Image.Image, dict]:
    key = profile.secret("unsplash_access_key")
    r = requests.get(
        "https://api.unsplash.com/photos/random",
        params={
            "query": query,
            "orientation": profile["background"].get("orientation", "squarish"),
            "content_filter": "high",
        },
        headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    photo = r.json()
    if isinstance(photo, list):
        photo = rng.choice(photo)

    image = _download(photo["urls"]["regular"])
    credit = {
        "provider": "unsplash",
        "query": query,
        "id": photo.get("id"),
        "author": (photo.get("user") or {}).get("name"),
        "author_url": ((photo.get("user") or {}).get("links") or {}).get("html"),
        "link": (photo.get("links") or {}).get("html"),
    }

    # Unsplash API guidelines require triggering the download endpoint.
    try:
        dl = ((photo.get("links") or {}).get("download_location"))
        if dl:
            requests.get(dl, headers={"Authorization": f"Client-ID {key}"}, timeout=10)
    except Exception:  # noqa: BLE001 - best effort, never block a post
        pass

    return image, credit


def _pexels(profile, query: str, rng: random.Random) -> tuple[Image.Image, dict]:
    key = profile.secret("pexels_api_key")
    r = requests.get(
        "https://api.pexels.com/v1/search",
        params={
            "query": query,
            "orientation": {"squarish": "square", "portrait": "portrait"}.get(
                profile["background"].get("orientation", "squarish"), "square"
            ),
            "per_page": 40,
        },
        headers={"Authorization": key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    photos = r.json().get("photos") or []
    if not photos:
        raise BackgroundError(f"Pexels returned no photos for {query!r}")
    photo = rng.choice(photos)
    image = _download(photo["src"]["large2x"])
    credit = {
        "provider": "pexels",
        "query": query,
        "id": photo.get("id"),
        "author": photo.get("photographer"),
        "author_url": photo.get("photographer_url"),
        "link": photo.get("url"),
    }
    return image, credit


def _local(profile, rng: random.Random) -> tuple[Image.Image, dict]:
    folder = ROOT / profile["background"].get("fallback_dir", "assets/backgrounds")
    files = sorted(
        p for p in folder.glob("**/*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not files:
        raise BackgroundError(
            f"No fallback images in {folder}. Add a few nature photos there so a "
            f"post is never skipped when the stock API fails."
        )
    chosen = rng.choice(files)
    return Image.open(chosen).convert("RGB"), {
        "provider": "local",
        "file": str(chosen.relative_to(ROOT)),
    }


PROVIDERS = {"unsplash": _unsplash, "pexels": _pexels}


def fetch(profile, rng: random.Random | None = None) -> tuple[Image.Image, dict]:
    """Return (image, credit). Falls back to the local folder on any failure."""
    rng = rng or random.Random()
    cfg = profile["background"]
    provider = cfg.get("provider", "unsplash")

    if provider == "local":
        return _local(profile, rng)

    fn = PROVIDERS.get(provider)
    if fn is None:
        raise BackgroundError(f"Unknown background provider {provider!r}")

    queries = list(cfg.get("queries") or ["nature"])
    rng.shuffle(queries)
    errors = []
    for query in queries[:3]:
        try:
            return fn(profile, query, rng)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{query}: {exc}")

    print(f"  ! {provider} failed ({'; '.join(errors)}); using local fallback")
    return _local(profile, rng)
