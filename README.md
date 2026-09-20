# instagram-baba

Posts one verse of the Qur'an a day to Instagram, set in Uthmani script over a
darkened nature photograph, at a random time each day.

Built for **@mahmoudelfakharany8**, a memorial account. Nothing about Hell or
punishment is ever posted — see [Content safety](#content-safety).

Nothing in `src/` is specific to that account. Everything account-shaped lives
in `profiles/*.json`, so the same code runs any number of Instagram accounts,
in any language, from any content pack. See [Running another account](#running-another-account).

```
                 curated refs          Quran.com API
                      │                      │
                      └──────► build_pool ◄──┘
                                   │
   stock photo API ──┐             ▼
                     ├──────► render ──► docs/posts/<profile>/<date>.jpg
   local fallback  ──┘             │              │
                                   │              ├──► git push (public URL)
                      caption ◄────┘              │
                                   │              ▼
                                   └────────► Graph API ──► Instagram
```

## How it runs

GitHub Actions runs `daily-post` **every hour**. Each run derives one
unpredictable target time for the day from `SHA256(profile | date | salt)`,
mapped into the profile's window (09:00–21:00 Africa/Cairo). Runs before that
time exit in about a second; the first run at or after it posts.

Deriving rather than storing the target means all 24 runs agree without any
shared state, and the time is different every day and different per account.

The finished image is committed to the repo and served from
`raw.githubusercontent.com` — Instagram needs a public HTTPS URL, and raw
serves a file the instant it's pushed, whereas GitHub Pages can lag a minute
or two behind. `docs/` doubles as a browsable archive if you enable Pages.

## Content safety

The account is a memorial, so the tone matters more than the variety.

1. **A curated allowlist.** `content/quran/allowlist.json` lists ~127 references
   by hand — mercy, patience, gratitude, creation, du'a. Nothing else is ever
   eligible.
2. **A keyword filter over the fetched text.** `src/safety.py` blocks any
   passage mentioning the Fire, punishment, or divine wrath, and catches a
   mistaken reference before it reaches the pool. Over-blocking is the safe
   failure here, so matching is substring-based, with a short list of verified
   exceptions (تَبَارَكَ is not تَبَار).
3. **A human read.** `content/quran/pool_review.txt` prints every accepted
   passage and every rejection with its reason. Read it once; re-read it
   whenever you edit the allowlist.

Three references from the allowlist are currently rejected by the filter, all
correctly: **14:7** and **57:20** mention عَذَاب, and **Al-Fatiha** contains
ٱلْمَغْضُوبِ عَلَيْهِمْ. Al-Fatiha is a judgement call — if you want it, add
`"الفاتحه"`-adjacent handling or remove `المغضوب` from the block list knowingly.

**Quranic text is never typed by hand in this repo.** `build_pool.py` fetches
it from the Quran.com API (Uthmani/Hafs), with alquran.cloud as a fallback.
Hand-transcription risks silent errors in scripture; a fetch does not.

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Rebuild the verse pool after editing the allowlist
python content/quran/build_pool.py

# Render six samples; posts nothing, writes to out/
python -m src.main --profile mahmoudelfakharany8 --preview 6

# Full pipeline, stopping short of Instagram
python -m src.main --profile mahmoudelfakharany8 --force

# Check credentials and how long the token has left
python -m src.main --profile mahmoudelfakharany8 --check-token

# Post for real
python -m src.main --profile mahmoudelfakharany8 --live --force

python -m tests.run
```

Posting is opt-in: without `--live` (or `LIVE=true`) nothing reaches Instagram.

## Layout

```
profiles/              one JSON per Instagram account — everything tunable
content/quran/         allowlist, build script, generated pool, review file
content/quotes/        a second pack, to show the pipeline isn't Quran-specific
src/
  main.py              orchestration and CLI
  schedule.py          the derived random daily posting time
  content.py           pool loading, non-repeating selection
  background.py        Unsplash / Pexels / local, with fallback
  render.py            image composition, Arabic layout, balanced wrapping
  caption.py           caption from the profile's template
  publish.py           Instagram Graph API
  safety.py            the Hell/punishment filter
  arabic.py            normalisation, numerals, waqf stripping
state/<profile>/       posting history (committed, so it survives runners)
docs/posts/<profile>/  every image posted
```

## Running another account

1. Copy a profile: `cp profiles/example-english.json profiles/my-account.json`.
2. Edit it — timezone, window, image size, fonts, colours, background queries,
   caption template, hashtags, and the **names** of the environment variables
   holding its secrets.
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
- **Selection** never repeats a passage until the whole pool has been through,
  then starts a fresh cycle. A failed post doesn't consume its verse.

Setup instructions: [SETUP.md](SETUP.md).
