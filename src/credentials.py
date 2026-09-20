#!/usr/bin/env python3
"""Turn a short-lived Graph token into the two secrets this bot needs.

    python -m src.credentials --profile mahmoudelfakharany8

Does what SETUP.md step 7 describes by hand: exchanges the token for a
long-lived one, checks the scopes are actually present, walks your Facebook
Pages to find the linked Instagram account, and prints the secrets (plus ready
to paste `gh secret set` commands).

Nothing here is written anywhere unless you pass --write-env, and the token is
never printed in full except in the final block.
"""
import argparse
import getpass
import os
import sys
import time
from pathlib import Path

import requests

from . import profile as profile_mod

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = 45

REQUIRED_SCOPES = {
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    # Pages owned by a Business Portfolio (the New Pages Experience) do not
    # appear on /me/accounts without this, and the failure is silent: every
    # other scope reads as granted and the Pages list simply comes back empty.
    "business_management",
}

# Only needed by profiles that also mirror to a Facebook Page. Instagram
# publishing works perfectly well without it, which is exactly why its absence
# is easy to miss.
PAGE_SCOPE = "pages_manage_posts"


def required_scopes(prof=None) -> set:
    scopes = set(REQUIRED_SCOPES)
    if prof and (prof["publish"].get("facebook") or {}).get("enabled"):
        scopes.add(PAGE_SCOPE)
    return scopes


class SetupError(RuntimeError):
    pass


def _get(path: str, **params) -> dict:
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=TIMEOUT)
    try:
        payload = r.json()
    except ValueError:
        raise SetupError(f"{path}: non-JSON response {r.status_code}: {r.text[:200]}")
    if "error" in payload:
        err = payload["error"]
        raise SetupError(f"{path}: {err.get('message')} (code {err.get('code')})")
    return payload


def exchange(app_id: str, app_secret: str, short_token: str) -> str:
    payload = _get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=short_token,
    )
    token = payload.get("access_token")
    if not token:
        raise SetupError(f"No access_token in exchange response: {payload}")
    return token


def inspect(token: str) -> dict:
    data = _get("debug_token", input_token=token, access_token=token).get("data", {})
    expires = data.get("expires_at") or 0
    return {
        "scopes": set(data.get("scopes") or []),
        "expires_at": expires,
        "days_left": "never" if not expires else round((expires - time.time()) / 86400, 1),
        "type": data.get("type"),
        "app_id": data.get("app_id"),
    }


def find_instagram_accounts(token: str) -> list:
    pages = _get(
        "me/accounts",
        fields="id,name,instagram_business_account{id,username,name}",
        access_token=token,
        limit=100,
    )
    found = []
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if ig:
            found.append({
                "page_id": page["id"],
                "page_name": page.get("name", ""),
                "ig_id": ig["id"],
                "ig_username": ig.get("username", ""),
                "ig_name": ig.get("name", ""),
            })
    return found


def _refresh(args, prof) -> int:
    """Renew a long-lived token in place - no Graph API Explorer round trip.

    A long-lived token can be exchanged for a fresh 60-day one right up until
    it expires, so this needs no browser and no re-consent. Run it any time
    before the deadline; the clock restarts from the day you run it.
    """
    import subprocess

    current = os.environ.get(
        (prof["secrets"]["ig_access_token"] if prof else "IG_ACCESS_TOKEN"), ""
    ).strip()
    if not current:
        print("error: no current token in the environment or .env", file=sys.stderr)
        return 2

    app_id = args.app_id or os.environ.get("META_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("META_APP_SECRET", "")
    if not (app_id and app_secret):
        app_id = app_id or input("Meta App ID: ").strip()
        app_secret = app_secret or getpass.getpass("Meta App Secret: ").strip()

    before = inspect(current)
    print(f"Current token: {before['days_left']} days left")

    try:
        token = exchange(app_id, app_secret, current)
    except SetupError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        print("If the token has already expired, or the app secret was reset since it\n"
              "was issued, generate a new one instead:\n"
              "  python -m src.credentials --profile <name> --write-env", file=sys.stderr)
        return 1

    after = inspect(token)
    print(f"New token    : {after['days_left']} days left")

    missing = required_scopes(prof) - after["scopes"]
    if missing:
        print(f"\n  ! The refreshed token is missing: {', '.join(sorted(missing))}")
        return 1

    if args.write_env:
        env_path = Path(profile_mod.ROOT) / ".env"
        existing = {}
        if env_path.exists():
            for line in env_path.read_text("utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        existing[prof["secrets"]["ig_access_token"] if prof else "IG_ACCESS_TOKEN"] = token
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n", "utf-8"
        )
        env_path.chmod(0o600)
        print(f"Wrote {env_path.name}")

    name = prof["secrets"]["ig_access_token"] if prof else "IG_ACCESS_TOKEN"
    if args.set_github_secret:
        result = subprocess.run(
            ["gh", "secret", "set", name, "--repo", args.set_github_secret,
             "--body", token],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"\n  ! gh secret set failed: {result.stderr.strip()}", file=sys.stderr)
            print(f"  Set it by hand:\n    gh secret set {name} "
                  f"--repo {args.set_github_secret} --body '<token>'", file=sys.stderr)
            return 1
        print(f"Updated {name} in {args.set_github_secret}")
    else:
        print(f"\nNow update the GitHub secret:\n"
              f"  gh secret set {name} --repo <owner>/<repo> --body '<the new token>'\n"
              f"or rerun with --set-github-secret <owner>/<repo>.")
    return 0


def main(argv=None) -> int:
    # Must happen before the parser is built: argparse evaluates its defaults
    # from os.environ at construction time.
    profile_mod.load_dotenv()

    parser = argparse.ArgumentParser(
        description="Exchange a short-lived token and discover the Instagram user ID."
    )
    parser.add_argument("--profile", help="profile name, used to pick the right account")
    parser.add_argument("--app-id", default=os.environ.get("META_APP_ID", ""))
    parser.add_argument("--app-secret", default=os.environ.get("META_APP_SECRET", ""))
    parser.add_argument("--token", default=os.environ.get("META_SHORT_TOKEN", ""),
                        help="short-lived User token from the Graph API Explorer")
    parser.add_argument("--write-env", action="store_true",
                        help="also write the secrets to a gitignored .env for local runs")
    parser.add_argument("--refresh", action="store_true",
                        help="renew the CURRENT long-lived token for another 60 days "
                             "(no browser step; uses IG_ACCESS_TOKEN from the env/.env)")
    parser.add_argument("--set-github-secret", metavar="OWNER/REPO",
                        help="push the refreshed token straight to that repo's "
                             "Actions secrets with gh")
    args = parser.parse_args(argv)

    prof = None
    if args.profile:
        try:
            prof = profile_mod.load(args.profile)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if args.refresh:
        return _refresh(args, prof)

    app_id = args.app_id or input("Meta App ID: ").strip()
    app_secret = args.app_secret or getpass.getpass("Meta App Secret: ").strip()
    short_token = args.token or getpass.getpass("Short-lived User token: ").strip()
    if not (app_id and app_secret and short_token):
        print("error: app id, app secret and token are all required", file=sys.stderr)
        return 2

    try:
        print("\nExchanging for a long-lived token...")
        token = exchange(app_id, app_secret, short_token)
        info = inspect(token)
        print(f"  valid for {info['days_left']} days")

        missing = required_scopes(prof) - info["scopes"]
        if missing:
            print(f"\n  ! Token is missing: {', '.join(sorted(missing))}")
            print("    Regenerate it in the Graph API Explorer with every scope")
            print("    ticked, then run this again. Publishing will fail without them.")
            if missing == {PAGE_SCOPE}:
                print(f"    ({PAGE_SCOPE} is only for the Facebook Page mirror;")
                print("     Instagram alone would be fine.)")
            return 1
        print(f"  scopes ok ({len(info['scopes'])} granted)")

        print("\nLooking for Instagram accounts on your Pages...")
        accounts = find_instagram_accounts(token)
        if not accounts:
            print("\n  ! No Page has a linked Instagram account.")
            print("    Two things cause this:")
            print("    1. The Page is owned by a Business Portfolio and the token is")
            print("       missing business_management - add it in the Graph API Explorer")
            print("       and regenerate. /me/accounts comes back empty rather than")
            print("       erroring, so this looks like a missing Page.")
            print("    2. The Page really isn't linked to the Instagram account. In the")
            print("       Instagram app: Settings -> Accounts Centre -> Connected")
            print("       experiences -> Accounts, and add the Facebook Page.")
            return 1

        for acc in accounts:
            print(f"  @{acc['ig_username']:<24} ig_id={acc['ig_id']}  "
                  f"page={acc['page_name']!r}")

        wanted = (prof.get("username") or prof.name) if prof else None
        chosen = next((a for a in accounts if a["ig_username"] == wanted), None)
        if chosen is None:
            if wanted:
                print(f"\n  ! None of these is @{wanted}.")
                print("    Check you generated the token as the user who admins that Page.")
                return 1
            if len(accounts) > 1:
                print("\n  ! Several accounts found; rerun with --profile to pick one.")
                return 1
            chosen = accounts[0]

        print(f"\nSelected @{chosen['ig_username']}")

    except SetupError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    repo = os.environ.get("GITHUB_REPOSITORY", "<owner>/<repo>")
    names = prof["secrets"] if prof else {
        "ig_user_id": "IG_USER_ID", "ig_access_token": "IG_ACCESS_TOKEN"
    }

    print("\n" + "=" * 70)
    print("Set these as GitHub Actions secrets:\n")
    print(f"  gh secret set {names['ig_user_id']} --body '{chosen['ig_id']}'")
    print(f"  gh secret set {names['ig_access_token']} --body '{token}'")
    print(f"\n  # and, if you haven't yet:")
    print(f"  gh secret set SCHEDULE_SALT --body \"$(openssl rand -hex 16)\"")
    print("=" * 70)
    print(f"\nToken expires in {info['days_left']} days "
          f"- token-check.yml will email you before then.")

    if args.write_env:
        env_path = Path(profile_mod.ROOT) / ".env"
        lines = [
            f"{names['ig_user_id']}={chosen['ig_id']}",
            f"{names['ig_access_token']}={token}",
        ]
        existing = {}
        if env_path.exists():
            for line in env_path.read_text("utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        for line in lines:
            k, v = line.split("=", 1)
            existing[k] = v
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n", "utf-8"
        )
        env_path.chmod(0o600)
        print(f"\nWrote {env_path.name} (gitignored) - local runs will pick it up.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
