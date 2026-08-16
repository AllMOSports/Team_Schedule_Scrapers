"""
run_scraper.py

Batch-runs the MSHSAA schedule scraper across a list of schools and one or
more seasons, writing a combined JSON file.

Usage:
    python run_scraper.py --sport football --years 2020 2021 2022 \
        --schools schools.json --output football_schedules.json

    # Single year, single school (smoke test):
    python run_scraper.py --sport football --years 2020 \
        --schools schools.json --output test.json --limit 1

Expected schools.json input shape (flexible -- adjust --id-field / --name-field
to match your existing AllMOSports schools.json):

    [
      {"id": 15, "slug": "blue-springs-south", "name": "Blue Springs South"},
      {"id": 115, "slug": "lees-summit-north", "name": "Lee's Summit North"},
      ...
    ]

Output JSON shape:

    {
      "sport": "football",
      "years": [2020, 2021],
      "generated_at": "...",
      "schools": {
        "15": {
          "school_id": 15,
          "slug": "blue-springs-south",
          "name": "Blue Springs South",
          "games": [ {...}, {...}, ... ]
        },
        ...
      }
    }
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from mshsaa_schedule_scraper import (
    ALG_CODES,
    fetch_and_parse,
    games_to_dicts,
    polite_delay,
    logger,
)


def load_schools(path: str, id_field: str, name_field: str, slug_field: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Support either a flat list or a dict keyed by id/slug
    if isinstance(data, dict):
        data = list(data.values())

    schools = []
    for entry in data:
        if id_field not in entry:
            logger.warning("Skipping school entry missing '%s': %s", id_field, entry)
            continue
        schools.append(
            {
                "id": entry[id_field],
                "name": entry.get(name_field),
                "slug": entry.get(slug_field),
            }
        )
    return schools


def main():
    parser = argparse.ArgumentParser(description="Batch scrape MSHSAA team schedules.")
    parser.add_argument("--sport", required=True, choices=ALG_CODES.keys())
    parser.add_argument("--alg", type=int, default=None, help="Override the alg code from ALG_CODES.")
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--schools", required=True, help="Path to schools JSON file.")
    parser.add_argument("--id-field", default="id", help="Key in schools.json holding the MSHSAA school id.")
    parser.add_argument("--name-field", default="name")
    parser.add_argument("--slug-field", default="slug")
    parser.add_argument("--output", required=True, help="Path to write combined output JSON.")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N schools (smoke test).")
    args = parser.parse_args()

    alg = args.alg if args.alg is not None else ALG_CODES.get(args.sport)
    if alg is None:
        logger.error(
            "No alg code known for sport '%s'. Pass --alg explicitly, or fill in "
            "ALG_CODES in mshsaa_schedule_scraper.py once you've confirmed it.",
            args.sport,
        )
        sys.exit(1)

    schools = load_schools(args.schools, args.id_field, args.name_field, args.slug_field)
    if args.limit:
        schools = schools[: args.limit]

    logger.info("Scraping %d schools x %d year(s) for sport=%s (alg=%d)", len(schools), len(args.years), args.sport, alg)

    result = {
        "sport": args.sport,
        "years": args.years,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schools": {},
    }

    session = requests.Session()
    total = len(schools) * len(args.years)
    done = 0

    for school in schools:
        school_id = school["id"]
        all_games = []

        for year in args.years:
            games = fetch_and_parse(school_id, alg, year, session=session)
            all_games.extend(games_to_dicts(games))
            done += 1
            logger.info(
                "[%d/%d] school_id=%s year=%s -> %d games",
                done, total, school_id, year, len(games),
            )
            polite_delay()

        result["schools"][str(school_id)] = {
            "school_id": school_id,
            "slug": school.get("slug"),
            "name": school.get("name"),
            "games": all_games,
        }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
