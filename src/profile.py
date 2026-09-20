"""Profile loading.

Everything account-specific lives in profiles/<name>.json so the same code can
drive any number of Instagram accounts. Nothing in src/ hardcodes an account,
a language, or a content pack.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "timezone": "UTC",
    "post_window": {"start_hour": 9, "end_hour": 21},
    "content": {
        "pack": "quran",
        "direction": "rtl",
        "language": "ar",
        "strip_waqf": True,
    },
    "image": {
        "width": 1080,
        "height": 1080,
        "max_font_size": 96,
        "min_font_size": 30,
        "text_box": {"width_pct": 0.82, "height_pct": 0.60},
        "line_spacing": 1.7,
        "overlay_opacity": 0.45,
        "blur_radius": 2.0,
        "vignette": 0.5,
        "shadow": True,
        "text_color": "#FFFFFF",
        "reference_color": "#E9E2D2",
        "reference_size": 34,
        "signature": "",
        "signature_size": 26,
        "signature_color": "#FFFFFF",
        "signature_opacity": 0.55,
    },
    "background": {
        "provider": "unsplash",
        "queries": ["nature"],
        "orientation": "squarish",
        "fallback_dir": "assets/backgrounds",
    },
    "caption": {"template": "{text}\n\n{reference}\n\n{hashtags}", "hashtags": []},
    "secrets": {
        "ig_user_id": "IG_USER_ID",
        "ig_access_token": "IG_ACCESS_TOKEN",
        "unsplash_access_key": "UNSPLASH_ACCESS_KEY",
        "pexels_api_key": "PEXELS_API_KEY",
        "pixabay_api_key": "PIXABAY_API_KEY",
    },
    "publish": {
        "api": "facebook",
        "api_version": "v21.0",
        "url_mode": "raw",
        "base_url": "auto",
        "posts_dir": "docs/posts",
        "library_dir": "docs/library",
        "keep_archive": True,
    },
}


def load_dotenv(path: Path | None = None) -> None:
    """Read a local .env into os.environ without overwriting real env vars.

    Convenience for running on your own machine; in CI the secrets arrive as
    real environment variables and this file won't exist.
    """
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Profile:
    def __init__(self, data: dict):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def pool_path(self) -> Path:
        pack = self.data["content"]["pack"]
        rel = self.data["content"].get("pool", f"content/{pack}/verses.json")
        return ROOT / rel

    @property
    def state_path(self) -> Path:
        return ROOT / "state" / self.name / "history.json"

    @property
    def posts_dir(self) -> Path:
        return ROOT / self.data["publish"]["posts_dir"] / self.name

    def secret(self, key: str, required: bool = True) -> str:
        """Read a secret from the environment using the profile's var names."""
        env_name = self.data["secrets"].get(key, key.upper())
        value = os.environ.get(env_name, "").strip()
        if not value and required:
            raise RuntimeError(
                f"Missing secret {env_name!r} (profile {self.name!r}, key {key!r}). "
                f"Set it as an environment variable or a GitHub Actions secret."
            )
        return value

    def base_url(self) -> str:
        """Public HTTPS base that Instagram will fetch the finished image from.

        url_mode 'raw' uses raw.githubusercontent.com, which serves a file the
        moment it is pushed - GitHub Pages can lag a minute or two behind, and
        Instagram will not wait. 'pages' uses the Pages site instead, and any
        other base_url is used verbatim.
        """
        configured = self.data["publish"].get("base_url", "auto")
        if configured and configured != "auto":
            return configured.rstrip("/")

        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if not repo or "/" not in repo:
            raise RuntimeError(
                "publish.base_url is 'auto' but GITHUB_REPOSITORY is not set. "
                "Set publish.base_url in the profile to a public HTTPS base URL."
            )
        owner, name = repo.split("/", 1)

        mode = self.data["publish"].get("url_mode", "raw")
        if mode == "pages":
            return f"https://{owner}.github.io/{name}"
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        return f"https://raw.githubusercontent.com/{owner}/{name}/{branch}"

    def public_url_for(self, path: Path) -> str:
        """Public URL for a file inside the repo."""
        rel = path.relative_to(ROOT).as_posix()
        base = self.base_url()
        mode = self.data["publish"].get("url_mode", "raw")
        if mode == "pages" and rel.startswith("docs/"):
            rel = rel[len("docs/"):]
        return f"{base}/{rel}"


def load(name: str | None = None) -> Profile:
    name = name or os.environ.get("PROFILE") or ""
    if not name:
        available = sorted(p.stem for p in (ROOT / "profiles").glob("*.json"))
        if len(available) == 1:
            name = available[0]
        else:
            raise RuntimeError(
                f"No profile selected. Pass --profile or set PROFILE. Available: {available}"
            )
    path = ROOT / "profiles" / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in (ROOT / "profiles").glob("*.json"))
        raise RuntimeError(f"No profile {name!r} in profiles/. Available: {available}")

    data = json.loads(path.read_text("utf-8"))
    data.setdefault("name", name)
    return Profile(_merge(DEFAULTS, data))
