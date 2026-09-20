"""Publish to Instagram via the official Graph API.

Two-step flow: create a media container pointing at a public image URL, then
publish the container. The image must already be reachable over HTTPS - main.py
pushes it to the repo and waits for the URL to serve before calling in here.

Meta offers two routes to the same endpoints, and profiles pick one with
publish.api:

  "facebook"  - Instagram API with Facebook Login (graph.facebook.com).
                The account must be linked to a Facebook Page.
  "instagram" - Instagram API with Instagram Login (graph.instagram.com).
                No Page needed; the account logs in directly.
"""
import time

import requests

API_HOSTS = {
    "facebook": "https://graph.facebook.com",
    "instagram": "https://graph.instagram.com",
}
API_VERSION = "v21.0"
TIMEOUT = 60


def graph_base(profile) -> str:
    api = profile["publish"].get("api", "facebook")
    host = API_HOSTS.get(api)
    if host is None:
        raise PublishError(
            f"Unknown publish.api {api!r}; expected one of {sorted(API_HOSTS)}"
        )
    version = profile["publish"].get("api_version", API_VERSION)
    return f"{host}/{version}"


class PublishError(RuntimeError):
    pass


def _raise_for_graph(response: requests.Response, step: str) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise PublishError(f"{step}: non-JSON response ({response.status_code}): "
                           f"{response.text[:300]}")
    if "error" in payload:
        err = payload["error"]
        raise PublishError(
            f"{step} failed: {err.get('message')} "
            f"(type={err.get('type')}, code={err.get('code')}, "
            f"subcode={err.get('error_subcode')})"
        )
    if not response.ok:
        raise PublishError(f"{step}: HTTP {response.status_code}: {response.text[:300]}")
    return payload


def create_container(base: str, ig_user_id: str, token: str, image_url: str,
                     caption: str) -> str:
    r = requests.post(
        f"{base}/{ig_user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=TIMEOUT,
    )
    payload = _raise_for_graph(r, "Creating media container")
    container_id = payload.get("id")
    if not container_id:
        raise PublishError(f"Creating media container: no id in response {payload}")
    return container_id


def wait_ready(base: str, token: str, container_id: str, attempts: int = 12) -> None:
    """Instagram fetches the image asynchronously; wait until it's FINISHED."""
    for attempt in range(attempts):
        r = requests.get(
            f"{base}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=TIMEOUT,
        )
        payload = _raise_for_graph(r, "Checking container status")
        status = payload.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PublishError(f"Instagram rejected the image: {payload.get('status')}")
        time.sleep(min(5 * (attempt + 1), 20))
    raise PublishError(f"Container {container_id} never became FINISHED")


def publish_container(base: str, ig_user_id: str, token: str, container_id: str) -> str:
    r = requests.post(
        f"{base}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=TIMEOUT,
    )
    payload = _raise_for_graph(r, "Publishing media")
    media_id = payload.get("id")
    if not media_id:
        raise PublishError(f"Publishing media: no id in response {payload}")
    return media_id


def permalink(base: str, token: str, media_id: str) -> str:
    try:
        r = requests.get(
            f"{base}/{media_id}",
            params={"fields": "permalink", "access_token": token},
            timeout=TIMEOUT,
        )
        return r.json().get("permalink", "")
    except Exception:  # noqa: BLE001 - cosmetic only
        return ""


def post(profile, image_url: str, caption: str) -> dict:
    base = graph_base(profile)
    ig_user_id = profile.secret("ig_user_id")
    token = profile.secret("ig_access_token")

    container_id = create_container(base, ig_user_id, token, image_url, caption)
    print(f"  container: {container_id}")
    wait_ready(base, token, container_id)
    media_id = publish_container(base, ig_user_id, token, container_id)
    print(f"  media: {media_id}")
    return {"media_id": media_id, "permalink": permalink(base, token, media_id)}


def check_token(profile) -> dict:
    """Verify credentials and report how long the token has left."""
    base = graph_base(profile)
    token = profile.secret("ig_access_token")
    ig_user_id = profile.secret("ig_user_id")

    account = requests.get(
        f"{base}/{ig_user_id}",
        params={"fields": "id,username,name,followers_count,media_count",
                "access_token": token},
        timeout=TIMEOUT,
    )
    info = _raise_for_graph(account, "Reading account")

    info.setdefault("token_days_left", "unknown")
    if profile["publish"].get("api", "facebook") != "facebook":
        # debug_token only exists on the Facebook host.
        return info

    debug = requests.get(
        f"{API_HOSTS['facebook']}/{API_VERSION}/debug_token",
        params={"input_token": token, "access_token": token},
        timeout=TIMEOUT,
    )
    try:
        data = debug.json().get("data", {})
        expires = data.get("expires_at", 0)
        info["token_expires_at"] = expires
        info["token_days_left"] = (
            "never" if expires in (0, None)
            else round((expires - time.time()) / 86400, 1)
        )
        info["token_scopes"] = data.get("scopes", [])
    except Exception:  # noqa: BLE001
        pass
    return info
