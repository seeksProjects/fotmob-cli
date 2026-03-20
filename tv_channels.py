"""TV channel lookup via LiveSoccerTV — HTTP scraping (no browser needed).

Scrapes LiveSoccerTV team pages for match broadcast information.
Uses plain HTTP requests with BeautifulSoup — works on cloud without Chrome.
"""

import logging

try:
    from curl_cffi import requests as _http
    _HAS_CURL = True
except ImportError:
    import requests as _http
    _HAS_CURL = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

logger = logging.getLogger(__name__)

TEAM_SLUGS = {
    # Premier League
    "arsenal": "england/arsenal", "aston villa": "england/aston-villa",
    "bournemouth": "england/afc-bournemouth", "afc bournemouth": "england/afc-bournemouth",
    "brentford": "england/brentford", "brighton": "england/brighton-hove-albion",
    "brighton and hove albion": "england/brighton-hove-albion",
    "burnley": "england/burnley", "chelsea": "england/chelsea",
    "crystal palace": "england/crystal-palace", "everton": "england/everton",
    "fulham": "england/fulham", "leeds": "england/leeds-united",
    "leeds united": "england/leeds-united", "liverpool": "england/liverpool",
    "man city": "england/manchester-city", "manchester city": "england/manchester-city",
    "man united": "england/manchester-united", "manchester united": "england/manchester-united",
    "newcastle": "england/newcastle-united", "newcastle united": "england/newcastle-united",
    "nottm forest": "england/nottingham-forest", "nottingham forest": "england/nottingham-forest",
    "sunderland": "england/sunderland", "tottenham": "england/tottenham-hotspur",
    "tottenham hotspur": "england/tottenham-hotspur",
    "west ham": "england/west-ham-united", "west ham united": "england/west-ham-united",
    "wolves": "england/wolverhampton-wanderers",
    # La Liga
    "barcelona": "spain/barcelona", "real madrid": "spain/real-madrid",
    "atletico madrid": "spain/atletico-madrid", "sevilla": "spain/sevilla",
    "villarreal": "spain/villarreal", "real betis": "spain/real-betis",
    "real sociedad": "spain/real-sociedad", "athletic club": "spain/athletic-club",
    "valencia": "spain/valencia", "celta vigo": "spain/celta-vigo",
    "getafe": "spain/getafe", "osasuna": "spain/osasuna",
    "mallorca": "spain/mallorca", "espanyol": "spain/espanyol",
    # Bundesliga
    "bayern munich": "germany/bayern-munich", "bayern munchen": "germany/bayern-munich",
    "borussia dortmund": "germany/borussia-dortmund", "rb leipzig": "germany/rb-leipzig",
    "bayer leverkusen": "germany/bayer-leverkusen",
    # Serie A
    "ac milan": "italy/ac-milan", "milan": "italy/ac-milan",
    "inter": "italy/internazionale", "internazionale": "italy/internazionale",
    "juventus": "italy/juventus", "napoli": "italy/napoli", "roma": "italy/roma",
    # Ligue 1
    "psg": "france/paris-saint-germain", "paris saint-germain": "france/paris-saint-germain",
    "marseille": "france/marseille", "lyon": "france/lyon",
    # Eredivisie
    "ajax": "netherlands/ajax", "psv": "netherlands/psv-eindhoven",
    "feyenoord": "netherlands/feyenoord", "az alkmaar": "netherlands/az-alkmaar",
    "heracles": "netherlands/heracles-almelo", "excelsior": "netherlands/excelsior",
    "nec": "netherlands/nec-nijmegen", "twente": "netherlands/fc-twente",
    # Other
    "benfica": "portugal/benfica", "porto": "portugal/fc-porto",
    "sporting": "portugal/sporting-cp", "galatasaray": "turkey/galatasaray",
    "fenerbahce": "turkey/fenerbahce", "besiktas": "turkey/besiktas",
    "celtic": "scotland/celtic", "rangers": "scotland/rangers",
}

_COOKIES = {
    "u_country": "United States",
    "u_country_code": "US",
    "u_timezone": "America/New_York",
    "u_continent": "Americas",
}


def _get_team_slug(name):
    """Find LiveSoccerTV slug for a team name. Uses local dict first, then dynamic search."""
    key = name.lower().strip()
    if key in TEAM_SLUGS:
        return TEAM_SLUGS[key]
    for k, v in TEAM_SLUGS.items():
        if key in k or k in key:
            return v

    # Dynamic search via LiveSoccerTV autocomplete
    try:
        import re
        url = f"https://www.livesoccertv.com/es/include/autocomplete.php?search={name}&lang=en&s_type=instant"
        if _HAS_CURL:
            resp = _http.get(url, impersonate="chrome", timeout=10)
        else:
            resp = _http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            # Extract team URL from HTML: href="/slog.php?q=...&url=%2Fteams%2Fitaly%2Fgenoa%2F"
            match = re.search(r'url=%2Fteams%2F([^"&]+)%2F', resp.text)
            if match:
                slug = match.group(1).replace("%2F", "/")
                logger.info("Dynamic slug for %s: %s", name, slug)
                TEAM_SLUGS[key] = slug  # Cache for future lookups
                return slug
    except Exception as e:
        logger.debug("Dynamic slug search failed for %s: %s", name, e)

    return None


def get_tv_channels(home_team, away_team=None):
    """Get TV channels for a team's upcoming match via HTTP scraping.

    No browser needed — uses plain HTTP + BeautifulSoup.
    Returns dict with match info and channels, or None.
    """
    if not _HAS_BS4:
        logger.warning("BeautifulSoup not installed, TV lookup unavailable")
        return None

    slug = _get_team_slug(home_team)
    if not slug and away_team:
        slug = _get_team_slug(away_team)
    if not slug:
        return None

    url = f"https://www.livesoccertv.com/teams/{slug}/"

    try:
        if _HAS_CURL:
            resp = _http.get(url, cookies=_COOKIES, impersonate="chrome", timeout=15)
        else:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            }
            resp = _http.get(url, headers=headers, cookies=_COOKIES, timeout=15)

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("tr.matchrow")

        for row in rows:
            game_el = row.select_one("a")
            game = game_el.text.strip() if game_el else ""

            # Check if this is played (finished) — skip finished matches
            ft_el = row.select_one(".livecell.ft")
            if ft_el:
                continue

            # Get channels from last td
            channels = []
            for a in row.select("td:last-child a"):
                ch = a.text.strip()
                if ch and len(ch) > 1:
                    channels.append(ch)

            if not channels:
                continue

            # Check if opponent matches
            if away_team:
                opp_lower = away_team.lower()
                if opp_lower not in game.lower() and game.lower() not in opp_lower:
                    # Try matching partial name
                    opp_words = set(opp_lower.split())
                    game_words = set(game.lower().split())
                    if not opp_words & game_words:
                        continue

            return {
                "match": game,
                "channels": channels[:6],
                "source": "LiveSoccerTV",
                "region": "US",
            }

        # No upcoming match with channels found — return first with channels
        for row in rows:
            channels = [a.text.strip() for a in row.select("td:last-child a") if a.text.strip()]
            if channels:
                game = row.select_one("a")
                return {
                    "match": game.text.strip() if game else "",
                    "channels": channels[:6],
                    "source": "LiveSoccerTV",
                    "region": "US",
                }

        return None

    except Exception as e:
        logger.warning("TV channel lookup failed: %s", e)
        return None


def format_tv_text(tv_data):
    """Format TV data into text for AI summary."""
    if not tv_data or not tv_data.get("channels"):
        return "TV broadcast information not available for this match."

    channels = ", ".join(tv_data["channels"])
    return f"TV/Broadcast (US): {channels}"
