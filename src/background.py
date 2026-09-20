"""Background image sourcing.

Providers are pluggable via profile.background.provider. Every provider falls
back to the profile's local fallback_dir so a post is never skipped just
because a stock API had a bad day.
"""
import io
import random
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30


class BackgroundError(RuntimeError):
    pass


# Stock search is keyword-matched, not subject-matched: "olive trees" on Pexels
# returns a bowl of olive dip. A plate of food under a verse is the kind of
# mistake nobody notices until it is on the account, so reject on the caption
# metadata both providers return. Over-rejecting is cheap - there are tens of
# thousands of landscapes behind these queries.
OFF_SUBJECT = [
    # food and drink
    "food", "plate", "bowl", "dish", "meal", "salad", "bread", "cheese", "sauce",
    "dip", "snack", "breakfast", "lunch", "dinner", "restaurant", "kitchen",
    "coffee", "drink", "cocktail", "wine", "fruit bowl", "cuisine", "recipe",
    # people as the subject
    "woman", "women", "man ", "men ", "girl", "boy", "portrait", "selfie",
    "model", "couple", "family", "child", "baby", "person holding", "face",
    "posing", "smiling", "wedding", "bride", "groom", "party",
    # interiors, urban and tech
    "indoor", "interior", "room", "office", "desk", "laptop", "computer",
    "phone", "keyboard", "chair", "sofa", "bedroom", "bathroom", "shop",
    "store", "market", "car", "vehicle", "traffic", "street", "highway",
    "road ", "parking", "building", "skyscraper", "construction", "factory",
    # religious imagery of other traditions, and anything figurative
    "church", "cathedral", "temple", "statue", "sculpture", "painting",
    "graffiti", "tattoo",
    # grim imagery, which is the last thing a memorial account should carry
    "skull", "skeleton", "bones", "bone ", "dead", "death", "grave",
    "cemetery", "tomb", "coffin", "funeral", "carcass", "decay", "rotting",
]


# A blocklist only catches what a caption happens to mention - a photo of a
# concrete street described as "urban architecture" slips through every term
# above. So when a description exists, also require positive evidence that the
# subject is the natural world.
ON_SUBJECT = [
    "forest", "tree", "wood", "jungle", "pine", "palm", "olive",
    "mountain", "hill", "valley", "cliff", "canyon", "rock", "peak", "summit",
    "sky", "cloud", "sunset", "sunrise", "dusk", "dawn", "star", "moon",
    "sea", "ocean", "lake", "river", "stream", "waterfall", "water", "wave",
    "beach", "shore", "coast", "island",
    "desert", "sand", "dune", "field", "meadow", "grass", "prairie", "steppe",
    "flower", "bloom", "blossom", "leaf", "leaves", "foliage", "garden",
    "snow", "ice", "glacier", "rain", "mist", "fog", "haze", "storm",
    "landscape", "nature", "natural", "scenery", "scenic", "horizon",
    "autumn", "spring", "summer", "winter", "wilderness", "countryside",
    "path", "trail", "hillside", "plant", "moss", "fern", "reed",
]


def _is_on_subject(text: str) -> bool:
    """Judge a photo by its own description: is the subject the natural world?"""
    if not text:
        return True  # nothing to judge by; the query already steered it
    lowered = f" {text.lower()} "
    if any(term in lowered for term in OFF_SUBJECT):
        return False
    return any(term in lowered for term in ON_SUBJECT)


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


def _pixabay(profile, query: str, rng: random.Random) -> tuple[Image.Image, dict]:
    photos = _pixabay_search(profile, query, page=1, per_page=60)
    if not photos:
        raise BackgroundError(f"Pixabay returned no photos for {query!r}")
    photo = rng.choice(photos)
    return _download(photo["url"]), {
        "provider": "pixabay", "query": query, "id": photo.get("id"),
        "author": photo.get("author"), "author_url": photo.get("author_url"),
        "link": photo.get("link"),
    }


def _pixabay_search(profile, query: str, page: int, per_page: int) -> list:
    key = profile.secret("pixabay_api_key")
    r = requests.get(
        "https://pixabay.com/api/",
        params={
            "key": key, "q": query, "image_type": "photo", "safesearch": "true",
            "per_page": min(max(per_page, 3), 200), "page": page,
            "orientation": {"portrait": "vertical"}.get(
                profile["background"].get("orientation", "squarish"), "horizontal"
            ),
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return [
        {"id": h.get("id"),
         "url": h.get("largeImageURL") or h.get("webformatURL"),
         "author": h.get("user"),
         "author_url": f"https://pixabay.com/users/{h.get('user')}-{h.get('user_id')}/",
         "link": h.get("pageURL"), "download_location": None}
        for h in (r.json().get("hits") or [])
        if _is_on_subject(h.get("tags"))
    ]


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


def _unsplash_search(profile, query: str, page: int, per_page: int) -> list:
    key = profile.secret("unsplash_access_key")
    r = requests.get(
        "https://api.unsplash.com/search/photos",
        params={
            "query": query, "page": page, "per_page": per_page,
            "orientation": profile["background"].get("orientation", "squarish"),
            "content_filter": "high",
        },
        headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("results") or []


def _pexels_search(profile, query: str, page: int, per_page: int) -> list:
    key = profile.secret("pexels_api_key")
    r = requests.get(
        "https://api.pexels.com/v1/search",
        params={
            "query": query, "page": page, "per_page": min(per_page, 80),
            "orientation": {"squarish": "square", "portrait": "portrait"}.get(
                profile["background"].get("orientation", "squarish"), "square"
            ),
        },
        headers={"Authorization": key}, timeout=TIMEOUT,
    )
    r.raise_for_status()
    return [
        {"id": p.get("id"), "url": p["src"]["large2x"], "author": p.get("photographer"),
         "author_url": p.get("photographer_url"), "link": p.get("url"),
         "download_location": None, "alt": p.get("alt")}
        for p in (r.json().get("photos") or [])
        if _is_on_subject(p.get("alt"))
    ]


def collect(profile, count: int, rng: random.Random | None = None) -> list:
    """Gather metadata for `count` distinct photos, for a bulk library build.

    Uses the providers' *search* endpoints with paging rather than one API call
    per photo: 30-80 results come back per request, so a 300-image library costs
    a handful of calls instead of 300 and stays inside a free tier.
    """
    rng = rng or random.Random()
    cfg = profile["background"]
    queries = list(cfg.get("queries") or ["nature"])
    rng.shuffle(queries)

    # provider may be a single name or a list. A list is about *variety*, not
    # reliability: 300 photos from one stock library share a recognisable look,
    # and mixing sources makes the grid read less templated.
    providers = cfg.get("provider", "unsplash")
    if isinstance(providers, list):
        return _collect_many(profile, providers, count, queries, rng)
    provider = providers

    if provider == "local":
        folder = ROOT / cfg.get("fallback_dir", "assets/backgrounds")
        files = sorted(
            p for p in folder.glob("**/*")
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if not files:
            raise BackgroundError(f"No images in {folder} to build a library from.")
        rng.shuffle(files)
        return [
            {"provider": "local", "id": f.name, "url": None,
             "file": str(f), "query": "local", "download_location": None}
            for f in (files * (count // len(files) + 1))[:count]
        ]

    per_page = {"unsplash": 30, "pexels": 80, "pixabay": 200}.get(provider, 30)
    search = {"unsplash": _unsplash_search, "pexels": _pexels_search,
              "pixabay": _pixabay_search}.get(provider)
    if search is None:
        raise BackgroundError(f"Provider {provider!r} cannot be used for a bulk build")

    found, seen, errors = [], set(), []
    for page in range(1, 6):
        for query in queries:
            if len(found) >= count:
                break
            try:
                results = search(profile, query, page, per_page)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{query} p{page}: {exc}")
                continue
            for photo in results:
                if provider == "unsplash":
                    described = " ".join(filter(None, [
                        photo.get("description"), photo.get("alt_description"),
                        " ".join(t.get("title", "") for t in (photo.get("tags") or [])),
                    ]))
                    if not _is_on_subject(described):
                        continue
                    photo = {
                        "id": photo.get("id"),
                        "url": (photo.get("urls") or {}).get("regular"),
                        "author": (photo.get("user") or {}).get("name"),
                        "author_url": ((photo.get("user") or {}).get("links") or {}).get("html"),
                        "link": (photo.get("links") or {}).get("html"),
                        "download_location": (photo.get("links") or {}).get("download_location"),
                    }
                key = photo.get("id")
                if not key or key in seen or not photo.get("url"):
                    continue
                seen.add(key)
                photo["query"] = query
                photo["provider"] = provider
                found.append(photo)
            time.sleep(0.4)
        if len(found) >= count:
            break

    if not found:
        raise BackgroundError(
            f"{provider} returned no photos at all. " + "; ".join(errors[:3])
        )
    rng.shuffle(found)
    return found[:count]


def _collect_many(profile, providers: list, count: int, queries: list,
                  rng: random.Random) -> list:
    """Split the target across several providers, skipping unusable ones."""
    usable, skipped = [], []
    for name in providers:
        try:
            if name != "local":
                key = {"unsplash": "unsplash_access_key", "pexels": "pexels_api_key",
                       "pixabay": "pixabay_api_key"}.get(name)
                if key and not profile.secret(key, required=False):
                    skipped.append(f"{name} (no key)")
                    continue
            usable.append(name)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{name} ({exc})")

    if skipped:
        print(f"  skipping {', '.join(skipped)}")
    if not usable:
        raise BackgroundError(
            f"None of {providers} is usable - no API keys are set for any of them."
        )

    collected, seen, working = [], set(), []

    def take(name: str, want: int) -> int:
        sub = dict(profile.data)
        sub["background"] = {**profile["background"], "provider": name}
        try:
            got = collect(type(profile)(sub), want, rng)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name} produced nothing ({str(exc)[:120]})")
            return 0
        added = 0
        for photo in got:
            marker = (photo.get("provider"), photo.get("id"))
            if marker in seen:
                continue
            seen.add(marker)
            collected.append(photo)
            added += 1
        return added

    share = -(-count // len(usable))  # ceil, so rounding never under-fills
    for name in usable:
        added = take(name, share)
        print(f"  {name}: {added} photos")
        if added:
            working.append(name)

    # A provider that is down or rate-limited would otherwise leave the library
    # short and force backgrounds to repeat. Top up from whatever did work.
    for name in working:
        if len(collected) >= count:
            break
        shortfall = count - len(collected)
        print(f"  topping up {shortfall} from {name}")
        take(name, shortfall + len(seen))

    rng.shuffle(collected)
    return collected[:count]


def download(photo: dict, profile=None) -> Image.Image:
    """Fetch one photo's pixels, and tell Unsplash it was used."""
    if photo.get("file"):
        return Image.open(photo["file"]).convert("RGB")
    image = _download(photo["url"])
    location = photo.get("download_location")
    if location and profile is not None:
        # Unsplash's API guidelines ask for this ping; it is best-effort, and a
        # rate-limited ping must never cost us a library image.
        try:
            key = profile.secret("unsplash_access_key", required=False)
            if key:
                requests.get(location, headers={"Authorization": f"Client-ID {key}"},
                             timeout=10)
        except Exception:  # noqa: BLE001
            pass
    return image


PROVIDERS = {"unsplash": _unsplash, "pexels": _pexels, "pixabay": _pixabay}


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
