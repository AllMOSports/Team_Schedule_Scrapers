"""
resolve_from_opponents.py
 
Your schedule scraper output (from run_scraper.py) lists every opponent a
matched school played, along with that opponent's real MSHSAA school id --
pulled straight from live mshsaa.org pages. This script mines that data to
resolve schools that didn't get an id any other way: if an unmatched school
ever shows up as someone else's opponent, we get its real id for free,
verified by an actual page fetch rather than a static CSV or a guess.
 
Usage:
    python resolve_from_opponents.py \
        --schedule-outputs football_schedules.json boys_soccer_schedules.json \
        --unmatched unmatched_schools.json \
        --output resolved_from_opponents.json \
        --still-unresolved-output still_unresolved_after_opponents.json
 
You can pass as many --schedule-outputs files as you have (one per sport/year
run) -- the more schedules scraped, the more opponent coverage, since a school
only surfaces here if someone already-matched played against it.
"""
 
import argparse
import json
import re
from collections import defaultdict
 
 
SUFFIXES = [
    " Senior High School",
    " Sr. High School",
    " High School",
]
 
 
def normalize(name: str) -> str:
    n = name
    for suf in SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    n = n.lower()
    n = re.sub(r"[.'’]", "", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n
 
 
def load_opponent_lookup(schedule_paths: list) -> tuple:
    """Scan every game in every schedule output for (opponent, opponent_school_id)
    pairs. Returns (clean_lookup, conflicts) where clean_lookup maps a
    normalized name to a single agreed-upon id, and conflicts lists any
    normalized name that showed up with more than one different id (a sign
    of noisy data -- e.g. two schools sharing a short display name).
    """
    name_to_ids = defaultdict(set)
    name_to_raw = defaultdict(set)
 
    for path in schedule_paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for school_id, school in data.get("schools", {}).items():
            for game in school.get("games", []):
                opp_name = game.get("opponent")
                opp_id = game.get("opponent_school_id")
                if not opp_name or not opp_id:
                    continue
                norm = normalize(opp_name)
                name_to_ids[norm].add(opp_id)
                name_to_raw[norm].add(opp_name)
 
    clean_lookup = {}
    conflicts = []
    for norm, ids in name_to_ids.items():
        if len(ids) == 1:
            clean_lookup[norm] = next(iter(ids))
        else:
            conflicts.append({
                "normalized_name": norm,
                "raw_names_seen": sorted(name_to_raw[norm]),
                "conflicting_ids": sorted(ids),
            })
 
    return clean_lookup, conflicts
 
 
def load_unmatched(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
 
 
def main():
    parser = argparse.ArgumentParser(description="Resolve unmatched school ids from opponent data in scraped schedules.")
    parser.add_argument("--schedule-outputs", nargs="+", required=True, help="One or more run_scraper.py output JSON files.")
    parser.add_argument("--unmatched", required=True, help="Path to unmatched_schools.json (from build_scraper_schools_json.py).")
    parser.add_argument("--output", required=True, help="Path to write resolved additions (id, name, slug), ready to merge.")
    parser.add_argument("--still-unresolved-output", required=True, help="Path to write the schools that still have no id.")
    parser.add_argument("--conflicts-output", default=None, help="Optional: path to write opponent-name collisions found in the schedule data, for awareness.")
    args = parser.parse_args()
 
    opponent_lookup, conflicts = load_opponent_lookup(args.schedule_outputs)
    unmatched = load_unmatched(args.unmatched)
 
    print(f"Built opponent lookup from {len(args.schedule_outputs)} schedule file(s): "
          f"{len(opponent_lookup)} distinct opponent names, {len(conflicts)} name collisions set aside.")
 
    resolved = []
    still_unresolved = []
 
    for item in unmatched:
        candidates = []
        if item.get("mshsaa_name"):
            candidates.append(item["mshsaa_name"])
            if " with " in item["mshsaa_name"]:
                candidates.append(item["mshsaa_name"].split(" with ")[0])
        if item.get("name"):
            candidates.append(item["name"])
 
        found_id = None
        for cand in candidates:
            norm = normalize(cand)
            if norm in opponent_lookup:
                found_id = opponent_lookup[norm]
                break
 
        if found_id is not None:
            resolved.append({
                "id": found_id,
                "name": item.get("name") or item.get("mshsaa_name"),
                "slug": item["slug"],
            })
        else:
            still_unresolved.append(item)
 
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2, ensure_ascii=False)
    with open(args.still_unresolved_output, "w", encoding="utf-8") as f:
        json.dump(still_unresolved, f, indent=2, ensure_ascii=False)
 
    print(f"Resolved {len(resolved)} / {len(unmatched)} schools from opponent data -> {args.output}")
    print(f"{len(still_unresolved)} still unresolved -> {args.still_unresolved_output}")
 
    if args.conflicts_output and conflicts:
        with open(args.conflicts_output, "w", encoding="utf-8") as f:
            json.dump(conflicts, f, indent=2, ensure_ascii=False)
        print(f"{len(conflicts)} opponent-name collisions written -> {args.conflicts_output} (not auto-used; a name mapped to more than one id in your scraped data)")
 
 
if __name__ == "__main__":
    main()
