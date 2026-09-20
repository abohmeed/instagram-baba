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

## 4. Decide which Meta route to use

There are two ways to reach the same publishing endpoints. Pick one and set
`publish.api` in your profile to match.

| | **Facebook Login** (`"facebook"`) | **Instagram Login** (`"instagram"`) |
|---|---|---|
| Profile setting | `"api": "facebook"` (default) | `"api": "instagram"` |
| Host | `graph.facebook.com` | `graph.instagram.com` |
| Facebook Page required | **Yes** | No |
| Scopes | `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` | `instagram_business_basic`, `instagram_business_content_publish` |
| Docs, examples, StackOverflow answers | Plentiful | Fewer |

If you already have (or don't mind creating) a Facebook Page, take the
Facebook Login route — it is far better documented, and it is what tripped
people up historically only because of the Page requirement. If you'd rather
not touch Facebook Pages at all, take the Instagram Login route.

The rest of this guide follows **Facebook Login**. Notes for the other route
are marked *(Instagram Login)*.

## 5. Link the account to a Facebook Page

*(Instagram Login: skip this step entirely.)*

1. Create a Facebook Page for the account if there isn't one:
   <https://www.facebook.com/pages/create>. It can be minimal.
2. In the Instagram app on your phone, sign in as **@mahmoudelfakharany8**, then:
   **Settings → Accounts Centre → Connected experiences → Accounts** and add
   the Page. (Older builds: **Settings → Account → Sharing to other apps**.)
3. Confirm the account is **Professional** (Business or Creator). You said it
   already is — verify under **Settings → Account type and tools**.

## 6. Create the Meta app

1. Go to <https://developers.facebook.com/apps> and create an app.
   Choose the **Business** type when asked.
2. Add the **Instagram** product to the app.
   *(Instagram Login: choose the "Instagram API with Instagram Login" setup;
   Facebook Login: the "Instagram API with Facebook Login" setup.)*
3. Note the **App ID** and **App Secret** from **App settings → Basic**.

You do **not** need App Review or a privacy policy to post to an account you
own: the app can stay in Development mode as long as your own user is listed
under **App roles** (admin/developer/tester). App Review is only needed to act
on accounts belonging to other people.

## 7. Get a long-lived access token and the Instagram user ID

Use the **Graph API Explorer** (<https://developers.facebook.com/tools/explorer/>):

1. Select your app, then **User Token**.
2. Add these permissions:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`.
   *(Instagram Login: `instagram_business_basic`, `instagram_business_content_publish`.)*
3. Click **Generate Access Token** and approve. You now have a **short-lived**
   token (about 1 hour).

Exchange it for a long-lived one (about 60 days):

```bash
SHORT_TOKEN="paste-the-short-lived-token"
APP_ID="your-app-id"
APP_SECRET="your-app-secret"

curl -s "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=$APP_ID\
&client_secret=$APP_SECRET\
&fb_exchange_token=$SHORT_TOKEN"
```

Copy `access_token` from the response — that's `IG_ACCESS_TOKEN`.

Now find the Instagram user ID:

```bash
TOKEN="paste-the-long-lived-token"

# 1. List your Pages
curl -s "https://graph.facebook.com/v21.0/me/accounts?access_token=$TOKEN"

# 2. Ask the Page for its linked Instagram account
PAGE_ID="page-id-from-step-1"
curl -s "https://graph.facebook.com/v21.0/$PAGE_ID\
?fields=instagram_business_account&access_token=$TOKEN"
```

The `instagram_business_account.id` is `IG_USER_ID` — a 17-digit number, not
the handle.

*(Instagram Login: the token exchange endpoint is
`https://graph.instagram.com/access_token?grant_type=ig_exchange_token`, and
`GET https://graph.instagram.com/v21.0/me?fields=id,username` returns the
Instagram user ID directly.)*

### Verify before going further

```bash
export IG_USER_ID="..." IG_ACCESS_TOKEN="..."
python -m src.main --profile mahmoudelfakharany8 --check-token
```

You should see `@mahmoudelfakharany8` and the days left on the token. If this
fails, everything downstream will too — fix it here.

## 8. Add the GitHub Secrets

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
