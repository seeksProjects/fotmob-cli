"""TV channel lookup via LiveSoccerTV.

Scrapes LiveSoccerTV for match broadcast information.
Prioritizes: UK, US, Europe, then Americas.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Team name → LiveSoccerTV URL slug mapping
TEAM_SLUGS = {
    # Premier League
    "arsenal": "england/arsenal",
    "aston villa": "england/aston-villa",
    "bournemouth": "england/afc-bournemouth",
    "afc bournemouth": "england/afc-bournemouth",
    "brentford": "england/brentford",
    "brighton": "england/brighton-hove-albion",
    "brighton and hove albion": "england/brighton-hove-albion",
    "burnley": "england/burnley",
    "chelsea": "england/chelsea",
    "crystal palace": "england/crystal-palace",
    "everton": "england/everton",
    "fulham": "england/fulham",
    "leeds": "england/leeds-united",
    "leeds united": "england/leeds-united",
    "liverpool": "england/liverpool",
    "man city": "england/manchester-city",
    "manchester city": "england/manchester-city",
    "man united": "england/manchester-united",
    "manchester united": "england/manchester-united",
    "newcastle": "england/newcastle-united",
    "newcastle united": "england/newcastle-united",
    "nottm forest": "england/nottingham-forest",
    "nottingham forest": "england/nottingham-forest",
    "sunderland": "england/sunderland",
    "tottenham": "england/tottenham-hotspur",
    "tottenham hotspur": "england/tottenham-hotspur",
    "west ham": "england/west-ham-united",
    "west ham united": "england/west-ham-united",
    "wolves": "england/wolverhampton-wanderers",
    "wolverhampton wanderers": "england/wolverhampton-wanderers",
    # La Liga
    "barcelona": "spain/barcelona",
    "real madrid": "spain/real-madrid",
    "atletico madrid": "spain/atletico-madrid",
    "sevilla": "spain/sevilla",
    "villarreal": "spain/villarreal",
    "real betis": "spain/real-betis",
    "real sociedad": "spain/real-sociedad",
    "athletic club": "spain/athletic-club",
    # Bundesliga
    "bayern munich": "germany/bayern-munich",
    "bayern munchen": "germany/bayern-munich",
    "borussia dortmund": "germany/borussia-dortmund",
    "rb leipzig": "germany/rb-leipzig",
    "bayer leverkusen": "germany/bayer-leverkusen",
    # Serie A
    "ac milan": "italy/ac-milan",
    "milan": "italy/ac-milan",
    "inter": "italy/internazionale",
    "internazionale": "italy/internazionale",
    "juventus": "italy/juventus",
    "napoli": "italy/napoli",
    "roma": "italy/roma",
    # Ligue 1
    "psg": "france/paris-saint-germain",
    "paris saint-germain": "france/paris-saint-germain",
    "marseille": "france/marseille",
    "lyon": "france/lyon",
}

# Priority countries for TV channels (UK, US, Europe, Americas)
PRIORITY_COUNTRIES = [
    {"code": "US", "name": "United States", "timezone": "America/New_York", "continent": "Americas"},
    {"code": "GB", "name": "United Kingdom", "timezone": "Europe/London", "continent": "Europe"},
    {"code": "ES", "name": "Spain", "timezone": "Europe/Madrid", "continent": "Europe"},
    {"code": "DE", "name": "Germany", "timezone": "Europe/Berlin", "continent": "Europe"},
    {"code": "BR", "name": "Brazil", "timezone": "America/Sao_Paulo", "continent": "Americas"},
    {"code": "MX", "name": "Mexico", "timezone": "America/Mexico_City", "continent": "Americas"},
]


def _get_team_slug(team_name):
    """Find the LiveSoccerTV URL slug for a team."""
    key = team_name.lower().strip()
    if key in TEAM_SLUGS:
        return TEAM_SLUGS[key]
    # Fuzzy match
    for name, slug in TEAM_SLUGS.items():
        if key in name or name in key:
            return slug
    return None


def get_tv_channels(team_name, opponent_name=None):
    """Get TV channels for a team's upcoming match.

    Uses LiveSoccerTV via browser (seleniumbase).
    Returns dict with match info and channels, or None.
    """
    slug = _get_team_slug(team_name)
    if not slug:
        # Try opponent
        if opponent_name:
            slug = _get_team_slug(opponent_name)
        if not slug:
            return None

    try:
        from seleniumbase import SB
        from browser import _get_browser

        sb = _get_browser()

        # Set US cookies for priority channels
        url = f'https://www.livesoccertv.com/teams/{slug}/'
        sb.open(url)
        sb.sleep(3)

        # Set country cookie to US and reload
        sb.execute_script("""
            document.cookie = "u_country=United States; path=/; domain=.livesoccertv.com";
            document.cookie = "u_country_code=US; path=/; domain=.livesoccertv.com";
            document.cookie = "u_timezone=America%2FNew_York; path=/; domain=.livesoccertv.com";
            document.cookie = "u_continent=Americas; path=/; domain=.livesoccertv.com";
        """)
        sb.open(url)
        sb.sleep(4)

        # Extract upcoming matches with channels
        js = """
        var results = [];
        var rows = document.querySelectorAll('tr.matchrow');
        for (var row of rows) {
            var gameEl = row.querySelector('a');
            var game = gameEl ? gameEl.textContent.trim() : '';

            var channels = [];
            var chEls = row.querySelectorAll('td:last-child a, .channelstd a');
            for (var ch of chEls) {
                var t = ch.textContent.trim();
                if (t && t.length > 1 && !t.includes('vs') && !t.includes('FC'))
                    channels.push(t);
            }

            var time = '';
            var timeEl = row.querySelector('.timecell span');
            if (timeEl) time = timeEl.textContent.trim();

            // Check if it's a played match (has .ft class)
            var ftEl = row.querySelector('.livecell.ft');
            var isPlayed = ftEl ? true : false;

            if (game && !isPlayed) {
                results.push({game: game, time: time, channels: channels});
            }
        }
        return JSON.stringify(results);
        """
        result = json.loads(sb.execute_script(js))

        # Find the match that includes the opponent
        if opponent_name:
            opp_lower = opponent_name.lower()
            for m in result:
                if opp_lower in m["game"].lower():
                    return {
                        "match": m["game"],
                        "time": m["time"],
                        "channels": m["channels"],
                        "source": "LiveSoccerTV",
                        "region": "US",
                    }

        # Return first upcoming match
        if result:
            return {
                "match": result[0]["game"],
                "time": result[0]["time"],
                "channels": result[0]["channels"],
                "source": "LiveSoccerTV",
                "region": "US",
            }

        return None

    except Exception as e:
        logger.debug("TV channel lookup failed: %s", e)
        return None


def format_tv_text(tv_data):
    """Format TV data into text for AI summary."""
    if not tv_data or not tv_data.get("channels"):
        return "TV broadcast information not available for this match."

    channels = ", ".join(tv_data["channels"][:5])
    region = tv_data.get("region", "US")
    return f"TV/Broadcast ({region}): {channels}"
