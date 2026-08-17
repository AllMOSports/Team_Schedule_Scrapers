"""
mshsaa_schedule_scraper.py
 
Reusable fetch + parse layer for MSHSAA Schedule.aspx pages.
 
Page URL pattern:
    https://www.mshsaa.org/MySchool/Schedule.aspx?s={school_id}&alg={sport_code}&year={year}
 
Confirmed page structure (validated against Blue Springs South Football 2020):
- Static, server-rendered HTML -- no JS rendering required.
- <table class="schedule"> with one <tr data-level="N" class="home|away"> per game.
- Opponent's MSHSAA school id is embedded in the opponent <a href> as `s=`.
- Each game has a unique id embedded in the Matchup link as `comp=`.
 
NOTE: mshsaa.org's robots.txt disallows automated access to this path.
This script is intended for personal/analytical use with conservative
rate limiting (see REQUEST_DELAY_SECONDS below) -- not high-frequency
or commercial scraping. Confirm this is acceptable for your use case
before running at scale.
"""
 
import re
import time
import random
import socket
import logging
from dataclasses import dataclass, asdict
from typing import Optional
 
import requests
import urllib3.util.connection as urllib3_conn
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
 
# Force IPv4 for all requests made via this module. Some CI runners (including
# GitHub-hosted ones) intermittently have no working IPv6 route, which shows up
# as "Network is unreachable" on every single request -- before any connection
# to the remote server is even attempted, so it has nothing to do with the URL
# or the remote site. Forcing IPv4 sidesteps that class of failure.
_orig_allowed_gai_family = urllib3_conn.allowed_gai_family
 
 
def _allowed_gai_family_ipv4_only():
    return socket.AF_INET
 
 
urllib3_conn.allowed_gai_family = _allowed_gai_family_ipv4_only
 
from bs4 import BeautifulSoup
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
 
BASE_URL = "https://www.mshsaa.org/MySchool/Schedule.aspx"
 
# Sport -> `alg` query param code. football=19 confirmed from your sample URL.
# TODO: confirm the remaining codes by pulling one schedule page per sport
# in a browser and reading the `alg=` value out of the URL.
ALG_CODES = {
    "football": 19,
    "baseball": 3,
    "boys_basketball": 5,
    "girls_basketball": 6,
    "boys_soccer": 33,
    "girls_soccer": 34,
    "girls_volleyball": 57,
    "softball_fall": 38,
    "softball_spring": 68,
}
 
REQUEST_DELAY_SECONDS = (1.5, 3.0)  # randomized delay range between requests
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
 
 
@dataclass
class Game:
    year: int
    school_id: int
    level: Optional[str]
    date: Optional[str]
    home_away: Optional[str]
    opponent: Optional[str]
    opponent_school_id: Optional[int]
    opponent_record: Optional[str]
    outcome: Optional[str]
    score: Optional[str]
    game_id: Optional[int]
    is_playoff: bool = False
 
 
def build_url(school_id: int, alg: int, year: int) -> str:
    return f"{BASE_URL}?s={school_id}&alg={alg}&year={year}"
 
 
def fetch_html(url: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Fetch a page with retries + polite delay. Returns None on failure."""
    sess = session or requests
    headers = {"User-Agent": USER_AGENT}
 
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = sess.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            logger.warning("Non-200 (%s) for %s [attempt %d/%d]", resp.status_code, url, attempt, MAX_RETRIES)
        except requests.RequestException as exc:
            logger.warning("Request error for %s: %s [attempt %d/%d]", url, exc, attempt, MAX_RETRIES)
 
        time.sleep(2 * attempt)  # backoff
 
    logger.error("Failed to fetch after %d attempts: %s", MAX_RETRIES, url)
    return None
 
 
ICON_CHARS = "\u2937\u21b3\u00a0"  # reschedule/indent arrow (⤷) + misc nbsp seen in tournament rows
 
 
def clean_text(text: Optional[str]) -> Optional[str]:
    """Strip leading icon glyphs (e.g. the ⤷ reschedule/bracket-indent marker) and whitespace."""
    if text is None:
        return None
    cleaned = text.strip().strip(ICON_CHARS).strip()
    return cleaned or None
 
 
def parse_schedule(html: str, school_id: int, year: int) -> list[Game]:
    """Parse a Schedule.aspx page's HTML into a list of Game records."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="schedule")
    if table is None:
        logger.warning("No schedule table found (school_id=%s, year=%s) -- likely no season played", school_id, year)
        return []
 
    games: list[Game] = []
 
    for tr in table.select("tbody tr"):
        level = tr.get("data-level")
        row_class = tr.get("class", [])
        is_away = "away" in row_class
        is_home = "home" in row_class
 
        # MSHSAA inserts a bracket-label row (e.g. "Class 6 State Tournament") ahead of
        # playoff rounds. It carries class "tournament" (without "tournamentGame") and has
        # no opponent link / no score -- it's a section header, not a game. Skip it.
        if "tournament" in row_class and "tournamentGame" not in row_class:
            continue
 
        date_td = tr.find("td", class_="gamedate")
        date_text = clean_text(date_td.get_text()) if date_td else None
 
        opp_td = tr.find("td", id=re.compile(r"tdOpponent$"))
        opp_link = opp_td.find("a") if opp_td else None
        opponent_name = clean_text(opp_link.get_text()) if opp_link else None
 
        opponent_school_id = None
        if opp_link and opp_link.get("href"):
            m = re.search(r"[?&]s=(\d+)", opp_link["href"])
            if m:
                opponent_school_id = int(m.group(1))
 
        opponent_record = None
        if opp_td:
            record_match = re.search(r"\((\d+-\d+(?:-\d+)?)\)", opp_td.get_text())
            if record_match:
                opponent_record = record_match.group(1)
 
        outcome_td = tr.find("td", id=re.compile(r"tdOutcome$"))
        outcome = outcome_td.get_text(strip=True) or None if outcome_td else None
 
        score_td = tr.find("td", id=re.compile(r"tdScoreTime$"))
        score_text = score_td.get_text(strip=True) or None if score_td else None
 
        matchup_link = tr.find("a", id=re.compile(r"aMatchup$"))
        game_id = None
        if matchup_link and matchup_link.get("href"):
            m = re.search(r"comp=(\d+)", matchup_link["href"])
            if m:
                game_id = int(m.group(1))
 
        games.append(
            Game(
                year=year,
                school_id=school_id,
                level=level,
                date=date_text,
                home_away="away" if is_away else ("home" if is_home else None),
                opponent=opponent_name,
                opponent_school_id=opponent_school_id,
                opponent_record=opponent_record,
                outcome=outcome,
                score=score_text,
                game_id=game_id,
                is_playoff="tournamentGame" in row_class,
            )
        )
 
    return games
 
 
def fetch_and_parse(school_id: int, alg: int, year: int, session: Optional[requests.Session] = None) -> list[Game]:
    url = build_url(school_id, alg, year)
    html = fetch_html(url, session=session)
    if html is None:
        return []
    return parse_schedule(html, school_id, year)
 
 
def polite_delay():
    time.sleep(random.uniform(*REQUEST_DELAY_SECONDS))
 
 
def games_to_dicts(games: list[Game]) -> list[dict]:
    return [asdict(g) for g in games]
