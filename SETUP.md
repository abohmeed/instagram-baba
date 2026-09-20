# Setup

One-time setup, in order. Steps 1–3 need no accounts beyond GitHub; steps 4–8
are the Meta side, which is the fiddly part.

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

## 3. Add fallback backgrounds (recommended)

Drop a few nature photos into `assets/backgrounds/`. They are used only when
the stock API fails, so a post is never skipped. See the README in that folder
for the licensing rule.

---

## 4. Which Meta route this uses

There are two ways to reach the same publishing endpoints, chosen per profile
with `publish.api`:

| | **Facebook Login** (`"facebook"`) | **Instagram Login** (`"instagram"`) |
|---|---|---|
| Host | `graph.facebook.com` | `graph.instagram.com` |
| Facebook Page required | Yes | No |
| Scopes | `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` | `instagram_business_basic`, `instagram_business_content_publish` |
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
2. Tick these four permissions:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`.
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

## 9. Dry run, then go live

Render six samples in CI without posting anything:

**Actions → preview → Run workflow**, profile `mahmoudelfakharany8`, count `6`.
Download the artifact and look at the images and captions.

Then a single real post, on demand:

**Actions → daily post → Run workflow**, tick **live** and **force**.

Once you're happy, do nothing — the hourly schedule is already running, and it
posts once a day at a random time between 09:00 and 21:00 Cairo.

### Optional: browsable archive

**Settings → Pages → Source: Deploy from a branch → `main` / `/docs`** gives you
`https://<you>.github.io/instagram-baba/posts/mahmoudelfakharany8/` listing every
image posted. The bot doesn't depend on this; it reads from
`raw.githubusercontent.com`, which serves immediately after a push.

---

## Keeping it running

**The token expires every 60 days.** This is the single thing most likely to
break the streak. `.github/workflows/token-check.yml` runs every Monday and
fails the workflow — which emails you — once fewer than 14 days remain.

To refresh, re-run the exchange with the *current* long-lived token:

```bash
curl -s "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=$APP_ID\
&client_secret=$APP_SECRET\
&fb_exchange_token=$CURRENT_LONG_LIVED_TOKEN"
```

Update the `IG_ACCESS_TOKEN` secret with the result. Takes a minute.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `(#200) Requires instagram_content_publish permission` | Scope missing from the token. Regenerate with all four scopes. |
| `Unsupported get request ... object does not exist` on `IG_USER_ID` | You used the Page ID or the handle. It must be `instagram_business_account.id`. |
| `The user is not an Instagram Business` | Account is still Personal, or not linked to the Page. |
| `Media ID is not available` | Instagram couldn't fetch the image URL. The repo must be public, and the push must have landed — the run logs print the URL; open it. |
| Container stuck at `IN_PROGRESS` | Usually a slow image fetch. The runner retries for ~2 minutes before giving up. |
| `Application request limit reached` | Content publishing is capped at 50 posts per 24h. One a day is nowhere near it. |
| Nothing posts, workflow is green | Expected: most hourly runs exit early because the random target time hasn't arrived. Look for the run near the target time in the logs. |
