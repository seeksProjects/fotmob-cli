"""FotMob API client — uses Next.js data routes after FotMob removed direct API endpoints.

FotMob moved from /api/* to /_next/data/{buildId}/*.json as of March 2026.
This client fetches the buildId dynamically and uses the new routes.
Falls back to direct page scraping if data routes fail.
"""

import json
import re
import time
import logging

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as _stdlib_requests
    _HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)

TIMEOUT = 15

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html",
    "Referer": "https://www.fotmob.com/",
}


class FotMobAPI:
    """Client for FotMob using Next.js data routes."""

    def __init__(self):
        if _HAS_CURL_CFFI:
            self.session = cffi_requests.Session(impersonate="chrome")
            self.session.headers.update({"Accept": "*/*", "Referer": "https://www.fotmob.com/"})
        else:
            self.session = _stdlib_requests.Session()
            self.session.headers.update(_HEADERS)
        self._cache = {}
        self._cache_ttl = 60
        self._build_id = None
        self._build_id_time = 0

    def _get_build_id(self):
        """Fetch the current Next.js buildId from FotMob homepage."""
        now = time.time()
        if self._build_id and now - self._build_id_time < 3600:  # Cache for 1 hour
            return self._build_id
        try:
            resp = self.session.get("https://www.fotmob.com/", timeout=TIMEOUT)
            match = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
            if match:
                self._build_id = match.group(1)
                self._build_id_time = now
                logger.info("FotMob buildId: %s", self._build_id)
                return self._build_id
        except Exception as e:
            logger.warning("Failed to get buildId: %s", e)
        return self._build_id  # Return cached even if expired

    def _next_data(self, path):
        """Fetch data via Next.js /_next/data/{buildId}/... route."""
        build_id = self._get_build_id()
        if not build_id:
            raise ConnectionError("Could not get FotMob buildId")

        url = f"https://www.fotmob.com/_next/data/{build_id}/{path}"
        cache_key = f"next:{path}"
        now = time.time()

        if cache_key in self._cache:
            data, ts = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return data

        resp = self.session.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        page_props = result.get("pageProps", {})

        self._cache[cache_key] = (page_props, now)
        return page_props

    def _page_scrape(self, url):
        """Fallback: scrape __NEXT_DATA__ from a rendered page."""
        cache_key = f"page:{url}"
        now = time.time()

        if cache_key in self._cache:
            data, ts = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return data

        resp = self.session.get(url, timeout=TIMEOUT)
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            page_props = data.get("props", {}).get("pageProps", {})
            self._cache[cache_key] = (page_props, now)
            return page_props
        return {}

    # --- Search ---

    def search(self, term):
        """Search for teams, players, and leagues via apigw.fotmob.com."""
        try:
            url = f"https://apigw.fotmob.com/searchapi/suggest?term={term}&lang=en"
            resp = self.session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            # Convert to the old format our code expects:
            # [{"title": {"value": "Teams"}, "suggestions": [{"type": "team", "id": X, "name": Y}]}]
            results = []

            # Teams
            team_options = []
            for group in data.get("teamSuggest", []):
                for opt in group.get("options", []):
                    payload = opt.get("payload", {})
                    name = opt.get("text", "").split("|")[0].strip()
                    team_options.append({
                        "type": "team",
                        "id": payload.get("id", ""),
                        "name": name,
                        "leagueId": payload.get("leagueId"),
                        "leagueName": payload.get("leagueName", ""),
                    })
            if team_options:
                results.append({"title": {"key": "teams", "value": "Teams"}, "suggestions": team_options})

            # Matches
            match_options = []
            for group in data.get("matchSuggest", []):
                for opt in group.get("options", []):
                    payload = opt.get("payload", {})
                    match_options.append({
                        "type": "match",
                        "id": payload.get("id", ""),
                        "name": opt.get("text", ""),
                        "homeTeamName": payload.get("homeName", ""),
                        "awayTeamName": payload.get("awayName", ""),
                        "leagueName": payload.get("leagueName", ""),
                        "status": {
                            "utcTime": payload.get("matchDate", ""),
                            "started": payload.get("statusId", 0) in (2, 3),
                            "finished": payload.get("statusId", 0) == 6,
                            "scoreStr": f"{payload.get('homeScore', '')} - {payload.get('awayScore', '')}" if payload.get("homeScore") is not None else None,
                        },
                    })
            if match_options:
                results.append({"title": {"key": "matches", "value": "Matches"}, "suggestions": match_options})

            # Players
            player_options = []
            for group in data.get("squadMemberSuggest", []):
                for opt in group.get("options", []):
                    payload = opt.get("payload", {})
                    name = opt.get("text", "").split("|")[0].strip()
                    player_options.append({
                        "type": "player",
                        "id": payload.get("id", ""),
                        "name": name,
                        "teamName": payload.get("teamName", ""),
                    })
            if player_options:
                results.append({"title": {"key": "players", "value": "Players"}, "suggestions": player_options})

            return results

        except Exception as e:
            logger.warning("Search failed: %s", e)
            return []

    # --- Leagues ---

    def all_leagues(self):
        """Get all available leagues."""
        try:
            return self._next_data("leagues.json")
        except Exception:
            return self._page_scrape("https://www.fotmob.com/leagues")

    def league(self, league_id, season=None):
        """Get league details including standings, fixtures, stats."""
        # Need the league slug — try common ones first
        slugs = {
            47: "premier-league", 87: "laliga", 54: "bundesliga",
            55: "serie-a", 53: "ligue-1", 42: "champions-league",
            73: "europa-league", 57: "eredivisie", 130: "mls",
            77: "world-cup", 132: "fa-cup", 133: "efl-cup",
            50: "euro", 71: "super-lig", 10562: "saudi-pro-league",
            62: "scottish-premiership", 61: "liga-portugal",
        }
        slug = slugs.get(league_id, str(league_id))
        try:
            pp = self._next_data(f"leagues/{league_id}/overview/{slug}.json")
            if pp and ("table" in pp or "details" in pp):
                return pp
        except Exception:
            pass
        # Fallback: page scrape
        return self._page_scrape(f"https://www.fotmob.com/leagues/{league_id}/overview/{slug}")

    # --- Teams ---

    def team(self, team_id):
        """Get team details including squad, fixtures, form."""
        try:
            pp = self._next_data(f"teams/{team_id}/overview.json")
            # New format: data is in fallback["team-{id}"]
            fallback = pp.get("fallback", {})
            team_data = fallback.get(f"team-{team_id}")
            if team_data:
                return team_data
            # If direct data exists
            if "details" in pp or "overview" in pp:
                return pp
        except Exception:
            pass
        # Fallback: page scrape
        pp = self._page_scrape(f"https://www.fotmob.com/teams/{team_id}/overview")
        fallback = pp.get("fallback", {})
        return fallback.get(f"team-{team_id}", pp)

    # --- Transfers ---

    def transfers(self, page=1):
        """Get recent transfers."""
        try:
            pp = self._next_data(f"transfers.json")
            return pp if pp else {"transfers": []}
        except Exception:
            return self._page_scrape("https://www.fotmob.com/transfers")

    # --- News ---

    def world_news(self, page=1):
        """Get world football news."""
        try:
            pp = self._next_data("news.json")
            return pp if pp else []
        except Exception:
            return self._page_scrape("https://www.fotmob.com/news")

    # --- Stats ---

    def league_stats(self, stats_url):
        """Fetch full stats from data.fotmob.com URL."""
        cache_key = f"stats:{stats_url}"
        now = time.time()

        if cache_key in self._cache:
            data, ts = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return data

        resp = self.session.get(stats_url, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self._cache[cache_key] = (data, now)
        return data
