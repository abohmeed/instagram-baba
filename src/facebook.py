"""Mirror the day's image to a Facebook Page.

Instagram is the primary destination; this is a second one for the same file.
The Page takes the finished image directly from its public URL, so there is no
container/publish dance here - one POST to /{page-id}/photos does it.

Credentials: nothing new is needed for a system user token. Meta will hand out
a Page token derived from it (GET /{page-id}?fields=access_token), and for a
system user that Page token never expires either, so the profile's existing
ig_access_token is enough. A profile can still name an explicit fb_page_token
secret if the Page is administered separately from the Instagram account.

The one thing the token must carry is the pages_manage_posts scope. Everything
else about the setup can be right and publishing will still fail without it.
"""
import requests

from .publish import API_HOSTS, API_VERSION, PublishError, _raise_for_graph

TIMEOUT = 60
GRAPH = f"{API_HOSTS['facebook']}/{API_VERSION}"

# Publishing to a Page needs this on top of the Instagram scopes.
PAGE_SCOPE = "pages_manage_posts"


def config(profile) -> dict:
    return profile["publish"].get("facebook") or {}


def enabled(profile) -> bool:
    return bool(config(profile).get("enabled"))


def caption_for(profile, item: dict) -> str:
    """The Page's own caption, falling back to the Instagram one.

    Built at library time and stored in the manifest, so what you reviewed is
    what goes out. Libraries built before this existed only have the Instagram
    caption; those post it unchanged rather than failing.
    """
    variant = config(profile).get("caption_variant", "facebook")
    return (item.get("captions") or {}).get(variant) or item["caption"]


def discover_page(token: str) -> dict:
    """Find the Page this token administers, when the profile names none."""
    r = requests.get(
        f"{GRAPH}/me/accounts",
        params={"fields": "id,name", "access_token": token, "limit": 100},
        timeout=TIMEOUT,
    )
    pages = _raise_for_graph(r, "Listing Pages").get("data", [])
    if not pages:
        raise PublishError(
            "No Facebook Page is visible to this token. If the Page belongs to a "
            "Business Portfolio the token also needs business_management; see "
            "SETUP.md."
        )
    if len(pages) > 1:
        names = ", ".join(f"{p['name']!r} ({p['id']})" for p in pages)
        raise PublishError(
            f"This token administers {len(pages)} Pages, so the profile must say "
            f"which one: set publish.facebook.page_id. Found: {names}"
        )
    return pages[0]


def page_token(profile, page_id: str) -> str:
    """The Page's own access token, derived from the profile's token.

    Explicit beats derived: a profile that names an fb_page_token secret and
    has it set in the environment uses that and never asks Meta.
    """
    explicit = profile.secret("fb_page_token", required=False)
    if explicit:
        return explicit

    r = requests.get(
        f"{GRAPH}/{page_id}",
        params={"fields": "access_token",
                "access_token": profile.secret("ig_access_token")},
        timeout=TIMEOUT,
    )
    payload = _raise_for_graph(r, "Reading the Page token")
    token = payload.get("access_token")
    if not token:
        raise PublishError(
            f"Meta returned no access_token for Page {page_id}. The token's user "
            f"is probably not an admin of it, or the token is missing "
            f"pages_show_list."
        )
    return token


def resolve(profile) -> tuple:
    """(page_id, page_token) for this profile."""
    page_id = str(config(profile).get("page_id") or "").strip()
    if not page_id:
        page_id = profile.secret("fb_page_id", required=False)
    if not page_id:
        page_id = discover_page(profile.secret("ig_access_token"))["id"]
    return page_id, page_token(profile, page_id)


def post(profile, image_url: str, caption: str) -> dict:
    page_id, token = resolve(profile)
    r = requests.post(
        f"{GRAPH}/{page_id}/photos",
        data={"url": image_url, "caption": caption, "access_token": token},
        timeout=TIMEOUT,
    )
    payload = _raise_for_graph(r, "Posting to the Facebook Page")
    post_id = payload.get("post_id") or payload.get("id")
    if not post_id:
        raise PublishError(f"Posting to the Facebook Page: no id in {payload}")
    return {
        "page_id": page_id,
        "photo_id": payload.get("id", ""),
        "post_id": post_id,
        "permalink": f"https://www.facebook.com/{post_id}",
    }


def check(profile) -> dict:
    """Read-only preflight: name the Page and say whether it can be posted to."""
    token = profile.secret("ig_access_token")
    page_id = str(config(profile).get("page_id") or "").strip() \
        or profile.secret("fb_page_id", required=False)

    if page_id:
        r = requests.get(
            f"{GRAPH}/{page_id}",
            params={"fields": "id,name", "access_token": token}, timeout=TIMEOUT,
        )
        page = _raise_for_graph(r, "Reading the Page")
    else:
        page = discover_page(token)

    info = {"page_id": page.get("id"), "page_name": page.get("name", "")}

    debug = requests.get(
        f"{GRAPH}/debug_token",
        params={"input_token": page_token(profile, info["page_id"]),
                "access_token": token},
        timeout=TIMEOUT,
    )
    data = _raise_for_graph(debug, "Inspecting the Page token").get("data", {})
    scopes = data.get("scopes") or []
    info["token_scopes"] = scopes
    info["token_expires_at"] = data.get("expires_at")
    info["can_post"] = PAGE_SCOPE in scopes
    return info
