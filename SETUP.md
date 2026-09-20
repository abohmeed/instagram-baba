# Setup

One-time setup, in order. Steps 1–3 need no accounts beyond GitHub; steps 4–8
are the Meta side, which is the fiddly part; steps 9–10 build the image library
and switch it on.

Meta redesigns its developer console regularly, so the screen names below may
drift. The API facts — scope names, endpoints, token lifetimes — are stable;
trust those and follow whatever the console calls the equivalent screen.

---

## 1. Create the GitHub repository

The repo must be **public**: Instagram fetches the finished image over plain
HTTPS from `raw.githubusercontent.com`, with no auth header. Your secrets live
in GitHub Actions Secrets and are never in the repo.

```bash
cd /Users/ahmed/Documents/instagram-baba
gh repo create instagram-baba --public --source=. --remote=origin --push
```

## 2. Get a free Unsplash API key

1. Sign up at <https://unsplash.com/developers> and create an app.
2. Copy the **Access Key** (not the secret key).

A new app starts in Demo mode: 50 requests/hour. One post uses one request, so
that is plenty. Apply for production only if you want more headroom.

Prefer Pexels? Get a key at <https://www.pexels.com/api/> and set
`background.provider` to `"pexels"` in the profile.

## 3. Add fallback backgrounds (optional)

Drop a few nature photos into `assets/backgrounds/`, and the library can be
built from them with no stock API at all (`"provider": "local"` in the
profile). Less critical than it sounds: because every image is rendered up
front, a stock API outage can never cost you a post — it can only delay a
rebuild. See the README in that folder for the licensing rule.

---

## 4. Which Meta route this uses

There are two ways to reach the same publishing endpoints, chosen per profile
with `publish.api`:

| | **Facebook Login** (`"facebook"`) | **Instagram Login** (`"instagram"`) |
|---|---|---|
| Host | `graph.facebook.com` | `graph.instagram.com` |
| Facebook Page required | Yes | No |
| Scopes | `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management` | `instagram_business_basic`, `instagram_business_content_publish` |
| Docs and community answers | Plentiful | Fewer |

**@mahmoudelfakharany8 has a Facebook Page, so it uses Facebook Login** — which
is already the default in its profile, and the better-documented of the two.
The Instagram Login route exists here only for future accounts without a Page.

## 5. Confirm the Page link

You already have the Page. Just confirm the two ends are actually joined,
because a Page that merely *mentions* the account isn't linked:

1. In the Instagram app, signed in as **@mahmoudelfakharany8**:
   **Settings → Accounts Centre → Connected experiences → Accounts** should
   list the Page. (Older builds: **Settings → Account → Sharing to other apps**.)
2. **Settings → Account type and tools** should say Professional.

Step 7 verifies this for real — if the link is missing, the helper says so in
as many words.

## 6. Create the Meta app

1. Go to <https://developers.facebook.com/apps> and create an app.
   Choose the **Business** type when asked.
2. Add the **Instagram** product, and pick the **Instagram API with Facebook
   Login** setup.
3. Note the **App ID** and **App Secret** from **App settings → Basic**.

You do **not** need App Review or a privacy policy to post to an account you
own: the app can stay in Development mode as long as your own user is listed
under **App roles** (admin/developer/tester). App Review is only needed to act
on accounts belonging to other people.

## 7. Get the token and the Instagram user ID

Open the **Graph API Explorer**
(<https://developers.facebook.com/tools/explorer/>):

1. Select your app, then **User Token**.
2. Tick these five permissions:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `business_management`.

   Add `pages_manage_posts` as well if the profile also mirrors to a Facebook
   Page — see *Also posting to the Facebook Page* below.

   **`business_management` is not optional if your Page belongs to a Business
   Portfolio**, which it does by default for anything created in recent years.
   Without it, `/me/accounts` returns an empty list instead of an error — every
   other scope reads as granted and it looks as though you have no Pages at
   all. This cost us half an hour; don't skip it.
3. **Generate Access Token** and approve. That token is short-lived (~1 hour) —
   that's fine, the next command trades it in.

Then let the helper do the rest:

```bash
python -m src.credentials --profile mahmoudelfakharany8 --write-env
```

It prompts for the App ID, App Secret and that short-lived token, then:

- exchanges it for a long-lived token (~60 days),
- **checks the four scopes are really present** — the single most common
  cause of a confusing failure later,
- walks your Pages to find the linked Instagram account and matches it against
  the profile's `username`,
- prints ready-to-paste `gh secret set` commands,
- with `--write-env`, writes a gitignored `.env` so local runs just work.

If the Page link is missing or a scope wasn't granted, it tells you which and
stops, rather than handing you credentials that fail at midnight.

<details>
<summary>Doing it by hand instead</summary>

```bash
# 1. exchange for a long-lived token
curl -s "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token&client_id=$APP_ID\
&client_secret=$APP_SECRET&fb_exchange_token=$SHORT_TOKEN"

# 2. find the Instagram user ID behind the Page
curl -s "https://graph.facebook.com/v21.0/me/accounts\
?fields=id,name,instagram_business_account{id,username}&access_token=$TOKEN"
```

`instagram_business_account.id` is `IG_USER_ID` — a 17-digit number, not the
handle.
</details>

### Verify before going further

```bash
export IG_USER_ID="..." IG_ACCESS_TOKEN="..."
python -m src.main --profile mahmoudelfakharany8 --check-token
```

You should see `@mahmoudelfakharany8` and the days left on the token. If this
fails, everything downstream will too — fix it here.

## 8. Add the GitHub Secrets

The helper in step 7 prints these as `gh secret set` commands, or add them at
**Settings → Secrets and variables → Actions → New repository secret:**

| Secret | Value |
|---|---|
| `IG_USER_ID` | the 17-digit Instagram user ID |
| `IG_ACCESS_TOKEN` | the long-lived token |
| `UNSPLASH_ACCESS_KEY` | your Unsplash Access Key |
| `SCHEDULE_SALT` | any random string, e.g. `openssl rand -hex 16` |

`SCHEDULE_SALT` makes the daily posting time unguessable from the outside. It's
optional — without it the schedule still varies daily, just predictably.

---

## 9. Build the image library

This is the one-time render of every image the account will post. It needs the
Unsplash key from step 2 and takes roughly 15–25 minutes for ~310 images.

**Actions → build library → Run workflow**, profile `mahmoudelfakharany8`,
`per_verse` `1`, and tick **force** (the first build has no cycle to wait for).

It commits `docs/library/mahmoudelfakharany8/` and the manifest.

Then **review it**. Browse `docs/library/mahmoudelfakharany8/` on GitHub — the
filenames carry the reference, so `0117-25_70.jpg` is 25:70. Anything you
don't want: remove the reference from `content/quran/allowlist.json`, re-run
`build_pool.py`, and rebuild.

To build locally instead:

```bash
export UNSPLASH_ACCESS_KEY="..."
python -m src.library --profile mahmoudelfakharany8 --build
git add docs/library state && git commit -m "library: edition 1" && git push
```

`--per-verse 2` renders each verse twice on different backgrounds, doubling
the library and the repo size.

## 10. Dry run, then go live

A dry run picks tomorrow's entry and prints it without posting:

```bash
python -m src.main --profile mahmoudelfakharany8 --force
```

Then one real post, on demand:

**Actions → daily post → Run workflow**, tick **live** and **force**.

Once you're happy, do nothing — the hourly schedule is already running, and it
posts once a day at a random time between 09:00 and 21:00 Cairo.

```bash
# any time, to see where the cycle is
python -m src.main --profile mahmoudelfakharany8 --status
```

### Optional: browsable archive

**Settings → Pages → Source: Deploy from a branch → `main` / `/docs`** gives you
`https://<you>.github.io/instagram-baba/posts/mahmoudelfakharany8/` listing every
image posted. The bot doesn't depend on this; it reads from
`raw.githubusercontent.com`, which serves immediately after a push.

---

## Also posting to the Facebook Page

The same image can go to a Facebook Page on the same run. Instagram stays the
primary destination: it posts first, and the day is recorded on its result.

Turn it on in the profile:

```json
"publish": {
  "facebook": {
    "enabled": true,
    "page_id": "106304495376583",
    "caption_variant": "facebook"
  }
}
```

Leave `page_id` empty and it uses the token's only Page, erroring if there is
more than one.

**No new secret is needed.** Meta will hand out a Page token derived from
`IG_ACCESS_TOKEN` (`GET /<page-id>?fields=access_token`), and when the source
is a system user token, that Page token never expires either. Set `FB_PAGE_ID`
or `FB_PAGE_TOKEN` only if the Page is administered separately from the
Instagram account.

**One scope must be added: `pages_manage_posts`.** Everything else can be
correct and publishing still fails without it — Instagram keeps working, so
nothing else gives the game away. The system user token you already have does
not carry it, so regenerate it (*Or stop refreshing entirely*, step 6, with
`pages_manage_posts` ticked) and set the secret again.

Check before trusting it:

```bash
python -m src.main --profile mahmoudelfakharany8 --check-token
```

It names the Page and prints `can post : yes` once the scope is there.
`token-check.yml` runs the same check weekly.

### The Facebook caption

Twelve hashtags read as spam outside Instagram, so the Page gets its own
shorter caption. The verse and the reference are identical; only the tags
differ:

```json
"caption": {
  "hashtags": ["#قرآن", "..."],
  "hashtag_count": 12,
  "variants": {
    "facebook": { "hashtags": ["#قرآن", "#آية_اليوم", "#صدقة_جارية"],
                  "hashtag_count": 3 }
  }
}
```

A variant overlays the caption block, so it only states what differs. Captions
live in the library manifest, so after changing one:

```bash
python -m src.library --profile mahmoudelfakharany8 --recaption
```

That rewrites the manifest alone — no rendering, no downloads, no API calls.
An entry with no variant caption (a library built before this existed) posts
the Instagram caption rather than failing.

### When the Page fails

A Page error after Instagram has posted is printed and recorded in
`history.json`, and the run still exits 0. Instagram is the record of truth for
the day, and a broken Page must not turn a working streak into a daily failure
email. The weekly token check is what tells you the Page is unhappy.

## Keeping it running

**The token expires every 60 days.** This is the single thing most likely to
break the streak. `.github/workflows/token-check.yml` runs every Monday and
fails the workflow — which emails you — once fewer than 14 days remain.

### Refreshing (60-day cycle)

A long-lived token can be traded for a fresh 60-day one right up until it
expires. No browser, no re-consent — the clock just restarts:

```bash
python -m src.credentials --profile mahmoudelfakharany8 \
    --refresh --write-env --set-github-secret <owner>/<repo>
```

It verifies the new token still carries all the scopes before writing it
anywhere, and pushes it straight into GitHub Actions secrets.

### Or stop refreshing entirely (recommended)

A **System User** token issued from the Business Portfolio can be set never to
expire, which removes this chore for good.

1. <https://business.facebook.com/settings> → the portfolio that owns the Page
2. **Accounts → Apps → Add → Connect an app ID** and pick your app. This is a
   prerequisite: Meta refuses to create a system user until an app belongs to
   the portfolio, and it transfers app ownership to the portfolio.
3. **Users → System users → Add** — name it `quran-poster`, role **Employee**.
   Employee is enough; Admin would grant business-wide control for no benefit.
4. **Assign assets → Facebook Pages** → your Page → enable **Content** only.
5. **Assign assets → Apps** → your app → enable **Develop app** only. Without
   an app role the token wizard stops at "No permissions available".
6. **Generate token** → select the app → expiry **Never** → tick
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `business_management`, and — if you mirror to the
   Page — `pages_manage_posts`
7. Copy it, then `./scripts/set-secret.sh IG_ACCESS_TOKEN` (reads the
   clipboard, so the token never lands in a terminal or a transcript), and
   `gh secret set IG_ACCESS_TOKEN --repo <owner>/<repo> --body "$IG_ACCESS_TOKEN"`

`IG_USER_ID` does not change. Verify with `--check-token`; the token line
should read `never expires`.

**You do not need to assign the Instagram account as an asset.** Meta greys
those toggles out unless you log in to Instagram, which looks like a blocker —
it isn't. Publishing reaches the account through the Page's
`instagram_business_account` edge, so the Page grant alone is sufficient.
Verified by creating a media container and leaving it unpublished.

After switching, `token-check.yml` stops being a countdown and becomes a
canary for the token being revoked. Keep it.

### Rotating the App Secret

The App Secret is only used to *mint* tokens, and it lives in your local
`.env` — it is **not** a GitHub Actions secret, so rotating it does not touch
the posting schedule.

1. <https://developers.facebook.com/apps> → your app → **App settings → Basic**
2. **App Secret → Reset**
3. Update `META_APP_SECRET` in `.env`
4. Immediately confirm tokens still work:
   `python -m src.credentials --profile <name> --refresh`

If that refresh fails after a reset, mint a fresh token from the Graph API
Explorer as in step 7 — the account and `IG_USER_ID` are unaffected either way.
Do the reset at a time when you can follow it with the verification, not
just before going away.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `(#200) Requires instagram_content_publish permission` | Scope missing from the token. Regenerate with all four scopes. |
| `Unsupported get request ... object does not exist` on `IG_USER_ID` | You used the Page ID or the handle. It must be `instagram_business_account.id`. |
| `The user is not an Instagram Business` | Account is still Personal, or not linked to the Page. |
| `No Page has a linked Instagram account`, but you *do* have a Page | Almost always a missing `business_management` scope — a Business Portfolio Page is invisible to `/me/accounts` without it, and the call succeeds with an empty list rather than failing. Add the scope, regenerate, rerun. Check the Page is ticked under **Facebook Settings → Business Integrations → your app → View and edit**. |
| `Media ID is not available` | Instagram couldn't fetch the image URL. The repo must be public, and the push must have landed — the run logs print the URL; open it. |
| Container stuck at `IN_PROGRESS` | Usually a slow image fetch. The runner retries for ~2 minutes before giving up. |
| `Application request limit reached` | Content publishing is capped at 50 posts per 24h. One a day is nowhere near it. |
| Nothing posts, workflow is green | Expected: most hourly runs exit early because the random target time hasn't arrived. Look for the run near the target time in the logs. |
| `No library for <profile>` | The library hasn't been built, or the build didn't get committed. See step 9. |
| `... is in the manifest but missing on disk` | The manifest and `docs/library/` are out of sync — rebuild. |
| Library build stops early with a rate-limit error | Unsplash Demo mode allows 50 API calls/hour. The bulk build uses far fewer, but applying for production access (free, at your app's page) raises it to 5000/hour. |
