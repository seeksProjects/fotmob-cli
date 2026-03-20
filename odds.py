"""Betting odds fetcher using The Odds API.

Free tier: 500 requests/month.
Docs: https://the-odds-api.com/liveapi/guides/v4/
"""

import json
import logging
import urllib.request
from config import get_key

logger = logging.getLogger(__name__)

ODDS_API_KEY = get_key("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# Map FotMob league names to odds API sport keys
LEAGUE_TO_SPORT = {
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "LaLiga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Ligue 1": "soccer_france_ligue_one",
    "Champions League": "soccer_uefa_champs_league",
    "Champions League Final Stage": "soccer_uefa_champs_league",
    "Europa League": "soccer_uefa_europa_league",
    "FA Cup": "soccer_fa_cup",
    "EFL Cup": "soccer_efl_cup",
    "MLS": "soccer_usa_mls",
    "Eredivisie": "soccer_netherlands_eredivisie",
}


def _fuzzy_match_team(name, candidates):
    """Find the best matching team name from candidates."""
    name_lower = name.lower().strip()
    for c in candidates:
        c_lower = c.lower()
        # Exact match
        if name_lower == c_lower:
            return c
        # Partial match
        if name_lower in c_lower or c_lower in name_lower:
            return c
        # Key word match (e.g. "Man United" matches "Manchester United")
        name_words = set(name_lower.split())
        c_words = set(c_lower.split())
        if len(name_words & c_words) >= 1 and len(name_words) > 0:
            overlap = len(name_words & c_words) / len(name_words)
            if overlap >= 0.5:
                return c
    return None


def get_match_odds(home_team, away_team=None, league_name=None):
    """Fetch betting odds for a specific match.

    Parameters
    ----------
    home_team : str
        Home team name (or any team name to search for).
    away_team : str, optional
        Away team name for more precise matching.
    league_name : str, optional
        League name to narrow down the sport.

    Returns
    -------
    dict or None
        Odds data with bookmaker prices, or None if not found.
    """
    if not ODDS_API_KEY:
        return None

    # Determine which sport keys to search
    sport_keys = []
    if league_name and league_name in LEAGUE_TO_SPORT:
        sport_keys = [LEAGUE_TO_SPORT[league_name]]
    else:
        # Search common leagues
        sport_keys = [
            "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
            "soccer_italy_serie_a", "soccer_france_ligue_one",
            "soccer_uefa_champs_league", "soccer_uefa_europa_league",
        ]

    for sport_key in sport_keys:
        try:
            url = (
                f"{BASE_URL}/sports/{sport_key}/odds/"
                f"?regions=eu,uk&markets=h2h&apiKey={ODDS_API_KEY}"
            )
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())

            for match in data:
                h = match.get("home_team", "")
                a = match.get("away_team", "")

                # Check if this is the right match
                h_match = _fuzzy_match_team(home_team, [h, a])
                a_match = _fuzzy_match_team(away_team, [h, a]) if away_team else True

                if h_match and a_match:
                    # Extract odds from first 3 bookmakers
                    odds_list = []
                    for bm in match.get("bookmakers", [])[:3]:
                        for market in bm.get("markets", []):
                            if market.get("key") == "h2h":
                                outcomes = market.get("outcomes", [])
                                odds_dict = {o["name"]: o["price"] for o in outcomes}
                                odds_list.append({
                                    "bookmaker": bm.get("title", ""),
                                    "home": odds_dict.get(h, ""),
                                    "draw": odds_dict.get("Draw", ""),
                                    "away": odds_dict.get(a, ""),
                                })

                    return {
                        "home_team": h,
                        "away_team": a,
                        "sport": sport_key,
                        "odds": odds_list,
                    }
        except Exception as e:
            logger.debug("Odds API error for %s: %s", sport_key, e)
            continue

    return None


def format_odds_text(odds_data):
    """Format odds data into readable text for AI summary."""
    if not odds_data:
        return "Betting odds not available for this match."

    lines = [f"Betting odds for {odds_data['home_team']} vs {odds_data['away_team']}:"]
    for o in odds_data.get("odds", []):
        lines.append(
            f"  {o['bookmaker']}: {odds_data['home_team']} {o['home']}, "
            f"Draw {o['draw']}, {odds_data['away_team']} {o['away']}"
        )
    return "\n".join(lines)
