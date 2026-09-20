# instagram-baba

Posts one verse of the Qur'an a day to Instagram — and to a Facebook Page, if
the profile asks for one — set in Uthmani script over a darkened nature
photograph, at a random time each day.

Built for **@mahmoudelfakharany8**, a memorial account. Nothing about Hell or
punishment is ever posted — see [Content safety](#content-safety).

Nothing in `src/` is specific to that account. Everything account-shaped lives
in `profiles/*.json`, so the same code runs any number of Instagram accounts,
in any language, from any content pack. See [Running another account](#running-another-account).

```
ONCE  ─────────────────────────────────────────────────────────────────────
  allowlist ─┐                      ┌─ stock photo API
             ├─► build_pool ─┐      │
  Quran.com ─┘               ├─► build library ─► docs/library/<profile>/*.jpg
                             │                    state/<profile>/library.json
        safety filter ───────┘                              │
                                                     git commit (public)

DAILY ─────────────────────────────────────────────────────────────────────
  hourly cron ─► due? ─► pick unused entry ─► Graph API ─┬─► Instagram
                          (no rendering, no photo API,   └─► Facebook Page
                           no push)                          (optional)
```

## How it runs

**Every image is rendered up front, once, and committed.** `build-library`
renders one image per verse — currently ~310 — fetches a distinct background
for each, and pushes the lot. The daily job never renders anything.

That's the important design choice. The daily critical path is a manifest
lookup and two Graph API calls: no stock-photo API to be down, no fonts to
install, no git push to race, and nothing to go wrong at 6pm that you'd only
notice the next morning. It also means you can look at all 310 images before
the first one is posted.

GitHub Actions runs `daily-post` **every hour**. Each run derives one
unpredictable target time for the day from `SHA256(profile | date | salt)`,
mapped into the profile's window (09:00–21:00 Africa/Cairo). Runs before that
time exit in about a second; the first run at or after it posts.

Deriving rather than storing the target means all 24 runs agree without any
shared state, and the time is different every day and different per account.

Selection walks the library in a random order and never repeats until every
image has been posted — about ten months at one a day. When the cycle
completes, the monthly `build-library` run re-renders everything with fresh
backgrounds, so the second pass through the same verses doesn't look like the
first. A rebuild replaces the previous edition's files rather than adding to
them, so the working tree holds exactly one library.

Images are served from `raw.githubusercontent.com`, which needs the repo to be
public. `docs/` doubles as a browsable archive if you enable Pages.

**A second destination is one POST.** With `publish.facebook.enabled` a profile
also posts the same image to a Facebook Page, from the same public URL and with
its own caption — the same verse, fewer hashtags, since a wall of tags reads as
spam outside Instagram. No extra secret: the Page token is derived from the
Instagram one. Instagram goes first and the day is recorded on its result, so a
Page failure is logged and the run still succeeds. See
[SETUP.md](SETUP.md#also-posting-to-the-facebook-page).

## Content safety

The account is a memorial, so the tone matters more than the variety.

1. **A curated allowlist.** `content/quran/allowlist.json` lists 313 references
   — mercy, patience, gratitude, creation, du'a. Nothing else is ever eligible.
   Candidates were *proposed* by `content/quran/discover.py`, which reads all
   6,236 ayat and narrows them mechanically (safety filter, then a
   needs-context filter for legal rulings, battle narrative and polemic, then a
   length window, then theme ranking). Every proposal was then reviewed by
   hand before it entered the list — the scanner suggests, it never decides.
2. **A keyword filter over the fetched text.** `src/safety.py` blocks any
   passage mentioning the Fire, punishment, or divine wrath, and catches a
   mistaken reference before it reaches the pool. Over-blocking is the safe
   failure here, so matching is substring-based, with a short list of verified
   exceptions (تَبَارَكَ is not تَبَار).
3. **A human read.** `content/quran/pool_review.txt` prints every accepted
   passage and every rejection with its reason. Read it once; re-read it
   whenever you edit the allowlist.

Of 313 references, 310 make it through. The three rejections are all correct:
**14:7** and **57:20** mention عَذَاب, and **Al-Fatiha** contains
ٱلْمَغْضُوبِ عَلَيْهِمْ. Al-Fatiha is a judgement call — if you want it,
remove `المغضوب` from the block list knowingly.

**Quranic text is never typed by hand in this repo.** `build_pool.py` fetches
it from the Quran.com API (Uthmani/Hafs), with alquran.cloud as a fallback.
Hand-transcription risks silent errors in scripture; a fetch does not.

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Rebuild the verse pool after editing the allowlist
python content/quran/build_pool.py

# Propose new verses to add to the allowlist (writes nothing)
python content/quran/discover.py --limit 300

# Build the image library - one image per verse. Do this once.
python -m src.library --profile mahmoudelfakharany8 --build

# Where the cycle is, and how long until it recycles
python -m src.library --profile mahmoudelfakharany8 --status

# Rewrite captions in the manifest after a template or hashtag change.
# Manifest only: no rendering, no downloads, no API calls.
python -m src.library --profile mahmoudelfakharany8 --recaption

# Render six throwaway samples to iterate on the design
python -m src.main --profile mahmoudelfakharany8 --preview 6

# Pick tomorrow's post from the library, stopping short of Instagram
python -m src.main --profile mahmoudelfakharany8 --force

# One-time: trade a short-lived Meta token for a long-lived one and
# discover the Instagram user ID behind your Facebook Page
python -m src.credentials --profile mahmoudelfakharany8 --write-env

# Check credentials, token lifetime, and that the Page can be posted to
python -m src.main --profile mahmoudelfakharany8 --check-token

# Renew the 60-day token in place (no browser) and push it to GitHub
python -m src.credentials --profile mahmoudelfakharany8 \
    --refresh --write-env --set-github-secret <owner>/<repo>

# Post for real
python -m src.main --profile mahmoudelfakharany8 --live --force

python -m tests.run
```

Posting is opt-in: without `--live` (or `LIVE=true`) nothing reaches Instagram
or Facebook.

## Layout

```
profiles/              one JSON per Instagram account — everything tunable
content/quran/         allowlist, build script, generated pool, review file
content/quotes/        a second pack, to show the pipeline isn't Quran-specific
content/quran/discover.py   scans all 6236 ayat to propose new candidates
src/
  main.py              the daily job: pick from the library and post
  library.py           builds the library, tracks the cycle
  schedule.py          the derived random daily posting time
  content.py           pool loading, history
  background.py        Unsplash / Pexels / local, single and bulk
  render.py            image composition, Arabic layout, balanced wrapping
  caption.py           caption from the profile's template
  publish.py           Instagram Graph API
  facebook.py          the optional Facebook Page mirror
  credentials.py       one-time token exchange and account discovery
  safety.py            the Hell/punishment and needs-context filters
  arabic.py            normalisation, numerals, waqf stripping
state/<profile>/       library.json (the manifest) and history.json
docs/library/<profile>/ every image, rendered up front
```

## Running another account

1. Copy a profile: `cp profiles/example-english.json profiles/my-account.json`.
2. Edit it — timezone, window, image size, fonts, colours, background queries,
   caption template, hashtags, whether it mirrors to a Facebook Page, and the
   **names** of the environment variables holding its secrets.
3. Point `content.pack` / `content.pool` at a JSON file of
   `{ref, text, ...}` records. Any field in a record is available to the
   caption template.
4. Add the profile name to the `matrix.profile` list in
   `.github/workflows/daily-post.yml` and `token-check.yml`, and add its
   secrets to the `env:` block.
5. Add the secrets in GitHub.

Each account gets its own derived posting time, its own history, and its own
archive folder. `profiles/example-english.json` is a working example: a
different language, direction, aspect ratio, provider and content pack.

## Notes on the implementation

- **Arabic shaping** is done by libraqm, bundled in Pillow's wheels, which
  handles the bidi reordering and contextual forms including dense Uthmani
  diacritics. `arabic-reshaper` + `python-bidi` are a fallback for Pillow
  builds without Raqm.
- **Line breaking** wraps greedily, then re-wraps at the narrowest width that
  keeps the same line count, so the last line isn't a lone orphan word.
- **Numerals** in captions are Arabic-Indic. A Latin range like `5-6` gets
  reordered to `6-5` by the bidi algorithm inside right-to-left text; `٥-٦`
  doesn't.
- **Waqf marks** (`ۖ ۚ`) are stripped from the artwork but kept in the caption.
  They're recitation aids, and they strand awkwardly at line breaks.
- **Selection** never repeats an image until the whole library has been
  through, then starts a fresh cycle. A failed post doesn't consume its entry,
  because history only records what actually published.
- **Bulk background fetching** uses the providers' *search* endpoints with
  paging — 30–80 photos per request — so building 310 images costs a handful
  of API calls rather than 310, and stays inside the free tier.

Setup instructions: [SETUP.md](SETUP.md).
