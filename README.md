# Team_Schedule_Scrapers

Scrapers for MSHSAA (`mshsaa.org`) `Schedule.aspx` team schedule pages, across
sports and seasons, feeding into AllMOSports data pipelines.

## Files

- `mshsaa_schedule_scraper.py` — core module: builds URLs, fetches HTML,
  parses a schedule page into structured `Game` records.
- `run_scraper.py` — batch runner: loops a list of schools x years, writes
  one combined JSON file.

## Page structure notes

`Schedule.aspx?s={school_id}&alg={sport_code}&year={year}` is a static,
server-rendered ASP.NET WebForms page (confirmed via view-source, not just
DevTools) — no headless browser needed.

Key parsing details already handled:

- Home/away comes from the `home`/`away` class on each `<tr>`, not a
  dedicated column.
- `data-level` on each row distinguishes varsity/JV/etc. Currently the
  scraper keeps all levels — filter on `level` downstream if you only want
  varsity.
- The opponent's own MSHSAA school id is embedded in the opponent link's
  `s=` query param — free join key back to your `schools.json`, no fuzzy
  name matching needed for opponents this source covers.
- Each game has a unique id in the Matchup link's `comp=` param — used as
  `game_id`, a natural dedup key.
- MSHSAA inserts a **bracket-label row** ahead of playoff rounds (e.g.
  "Class 6 State Tournament") with no opponent/score — this is filtered out,
  it's not a real game.
- Actual playoff games carry a `tournamentGame` class and are flagged
  `is_playoff: true` in the output.
- A `⤷` (U+2937) icon MSHSAA prepends to some tournament-row text is
  stripped during cleaning.

## Known gaps / TODO before running at scale

1. **`alg` codes per sport** — only `football = 19` is confirmed (from the
   sample URL). Pull one schedule page per sport in a browser and read the
   `alg=` value out of the URL, then fill in `ALG_CODES` in
   `mshsaa_schedule_scraper.py`.
2. **robots.txt** — `mshsaa.org` disallows automated access to this path.
   The scraper uses conservative rate limiting (`REQUEST_DELAY_SECONDS` in
   `mshsaa_schedule_scraper.py`, currently a 1.5–3s randomized delay) but
   this is still worth a deliberate decision on frequency/volume before
   wiring into a GitHub Action that runs unattended.
3. **Row shapes not yet seen in the sample**: postponed/cancelled games,
   overtime notation, and levels other than varsity (`data-level="1"` was
   the only value in the sample). Spot-check a few more schools/sports
   before trusting this at full scale.
4. **Score parsing is currently a raw string** (`"12 - 17"`). If you want
   separate `points_for`/`points_against` ints for your ratings pipelines
   (matching your other `*_history.json` conventions), split on `" - "`
   downstream once you've confirmed OT/forfeit notation doesn't break the
   pattern.

## Usage

```bash
pip install requests beautifulsoup4

# Smoke test against a single school/year
python run_scraper.py --sport football --years 2020 \
    --schools schools.json --output test_output.json --limit 1

# Full batch
python run_scraper.py --sport football --years 2020 2021 2022 2023 2024 2025 \
    --schools schools.json --output football_schedules_2020-2025.json
```

`schools.json` should be a list (or dict of records) with at minimum an id
field matching MSHSAA's `s=` school id. Adjust `--id-field` / `--name-field`
/ `--slug-field` if your existing `schools.json` uses different keys.

## Suggested next step: GitHub Action

Once `ALG_CODES` is filled in and you've spot-checked a few sports, this
slots into the same GitHub Actions pattern as your other pipelines — a
scheduled or manually-triggered workflow that runs `run_scraper.py` per
sport and commits the output JSON, similar to your backfill scrapers for
MSHSAA season records.
