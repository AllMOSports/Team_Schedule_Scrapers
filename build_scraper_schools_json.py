"""
build_scraper_schools_json.py
 
Merges your existing AllMOSports schools.json (keyed by slug, has mshsaa_name)
with mshsaa_schools.csv (school_name -> MSHSAA `s=` id) to produce the
schools.json shape run_scraper.py expects:
 
    [
      {"id": 15, "name": "Blue Springs South", "slug": "blue-springs-south"},
      ...
    ]
 
Usage:
    python build_scraper_schools_json.py \
        --allmosports-schools schools.json \
        --mshsaa-csv mshsaa_schools.csv \
        --output scraper_schools.json
"""
 
import argparse
import csv
import json
import re
import sys
from difflib import SequenceMatcher
 
 
SUFFIXES = [
    " Senior High School",
    " Sr. High School",
    " High School",
]
 
 
def normalize(name: str) -> str:
    """Lowercase, strip MSHSAA suffixes, drop punctuation, collapse whitespace."""
    n = name
    for suf in SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    n = n.lower()
    n = re.sub(r"[.'’]", "", n)          # drop periods/apostrophes
    n = re.sub(r"[^a-z0-9]+", " ", n)    # everything else -> space
    n = re.sub(r"\s+", " ", n).strip()
    return n
 
 
def fuzzy_match(name: str, lookup: dict, threshold: float = 0.82) -> tuple:
    """Best-effort match for near-miss names (e.g. 'Academie Lafayette' vs CSV's
    'academie lafayette charter'). Restricts comparison to CSV names sharing the
    first word, for speed and to reduce false positives, then falls back to a
    full scan if that bucket is empty. Returns (id, matched_csv_name, score) or
    None if nothing clears the threshold.
    """
    norm = normalize(name)
    first_word = norm.split()[0] if norm.split() else ""
    bucket = [n for n in lookup if n.split() and n.split()[0] == first_word]
    candidates = bucket or list(lookup.keys())
 
    best_score = 0.0
    best_name = None
    for cand in candidates:
        score = SequenceMatcher(None, norm, cand).ratio()
        if score > best_score:
            best_score = score
            best_name = cand
 
    if best_name is not None and best_score >= threshold:
        return lookup[best_name], best_name, best_score
    return None
 
 
def load_mshsaa_csv(path: str) -> dict:
    """Return {normalized_name: id}. Warns on duplicate normalized names."""
    lookup = {}
    dupes = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            norm = normalize(row["school_name"])
            school_id = int(row["school_id"])
            if norm in lookup and lookup[norm] != school_id:
                dupes.append((norm, lookup[norm], school_id, row["school_name"]))
            lookup[norm] = school_id
    if dupes:
        print(f"WARNING: {len(dupes)} normalized-name collisions in MSHSAA CSV:", file=sys.stderr)
        for norm, old_id, new_id, raw in dupes[:10]:
            print(f"  '{norm}' -> ids {old_id} vs {new_id} (raw: '{raw}')", file=sys.stderr)
    return lookup
 
 
def load_allmosports_schools(path: str) -> dict:
    """Return {slug: {mshsaa_name, name, sports}}.
 
    Handles two shapes:
      1. The dict of schools directly: {slug: {...}, slug: {...}}
      2. Wrapped under a "schools" key alongside other metadata:
         {"generated": ..., "ranges": {...}, "schools": {slug: {...}, ...}}
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "schools" in data and isinstance(data["schools"], dict):
        return data["schools"]
    return data
 
 
def main():
    parser = argparse.ArgumentParser(description="Build scraper-ready schools.json with MSHSAA ids.")
    parser.add_argument("--allmosports-schools", required=True, help="Path to your existing schools.json")
    parser.add_argument("--mshsaa-csv", required=True, help="Path to mshsaa_schools.csv")
    parser.add_argument("--output", required=True, help="Path to write scraper-ready schools JSON")
    parser.add_argument("--unmatched-output", default=None, help="Optional path to write list of unmatched schools, with suggested (unverified) candidates")
    args = parser.parse_args()
 
    mshsaa_lookup = load_mshsaa_csv(args.mshsaa_csv)
    allmosports = load_allmosports_schools(args.allmosports_schools)
 
    matched = []
    unmatched = []
 
    skipped_metadata = []
 
    for slug, info in allmosports.items():
        # schools.json carries a few top-level metadata keys alongside the actual
        # school entries (e.g. "generated_at": "2026-08-11T...", a "ranges" block
        # of classification min/max values). Those values aren't school dicts --
        # skip them rather than crashing on .get().
        if not isinstance(info, dict) or "sports" not in info:
            skipped_metadata.append(slug)
            continue
 
        # mshsaa_name is the more "official" name (e.g. "Bayless with Hancock");
        # name is the display name (e.g. "Bayless"). Try mshsaa_name first, then name,
        # then the part before " with " in mshsaa_name (co-op schools).
        candidates = []
        if info.get("mshsaa_name"):
            candidates.append(info["mshsaa_name"])
            if " with " in info["mshsaa_name"]:
                candidates.append(info["mshsaa_name"].split(" with ")[0])
        if info.get("name"):
            candidates.append(info["name"])
 
        school_id = None
        for cand in candidates:
            norm = normalize(cand)
            if norm in mshsaa_lookup:
                school_id = mshsaa_lookup[norm]
                break
 
        if school_id is not None:
            matched.append({
                "id": school_id,
                "name": info.get("name") or info.get("mshsaa_name"),
                "slug": slug,
            })
        else:
            # No exact match. Suggest the closest CSV name(s) for manual review --
            # NEVER auto-accept a fuzzy match. Missouri has many schools with
            # generic, similar-sounding names (e.g. "Summit Christian Academy" vs
            # "Faith Christian Academy", "Sheldon" vs "Eldon") where a plausible-
            # looking text-similarity score is still the wrong school. Attaching
            # the wrong MSHSAA id would silently scrape and label the wrong
            # team's schedule, so this always requires a human decision.
            best_cand = candidates[0] if candidates else (info.get("name") or slug)
            suggestion = fuzzy_match(best_cand, mshsaa_lookup, threshold=0.0)
            entry = {
                "slug": slug,
                "mshsaa_name": info.get("mshsaa_name"),
                "name": info.get("name"),
            }
            if suggestion:
                sug_id, sug_name, sug_score = suggestion
                entry["suggested_id"] = sug_id
                entry["suggested_csv_name"] = sug_name
                entry["suggested_score"] = round(sug_score, 3)
            unmatched.append(entry)
 
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(matched, f, indent=2, ensure_ascii=False)
 
    print(f"Matched {len(matched)} / {len(allmosports)} schools -> {args.output}")
    if skipped_metadata:
        print(f"Skipped {len(skipped_metadata)} non-school top-level keys: {skipped_metadata}")
 
    # Always write the unmatched file, even if empty, so downstream steps
    # (e.g. a CI `git add`) can rely on it existing. Each entry may include a
    # suggested_id / suggested_csv_name / suggested_score for manual review --
    # these are NEVER auto-applied. Verify each one before adding it to your
    # schools list; some suggestions will be wrong (e.g. "Sheldon" vs "Eldon").
    if args.unmatched_output:
        with open(args.unmatched_output, "w", encoding="utf-8") as f:
            json.dump(unmatched, f, indent=2, ensure_ascii=False)
 
    if unmatched:
        print(f"{len(unmatched)} schools unmatched -- see {args.unmatched_output} for review, "
              f"each with a suggested_id where a plausible candidate was found.", file=sys.stderr)
        print("Suggestions are NOT verified -- confirm each one before using it "
              "(similar-sounding schools can produce a confident-looking wrong match).", file=sys.stderr)
    else:
        print("All schools matched.")
 
 
if __name__ == "__main__":
    main()
