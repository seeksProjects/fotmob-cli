"""FotMob API client - handles all HTTP requests to FotMob's internal API."""

import json
import time
from curl_cffi import requests as cffi_requests

BASE_URL = "https://www.fotmob.com/api"
IMPERSONATE = "chrome"
TIMEOUT = 15


class FotMobAPI:
    """Client for FotMob's internal API."""

    def __init__(self):
        self.session = cffi_requests.Session(impersonate=IMPERSONATE)
        self.session.headers.update({
            "Accept": "application/json",
            "Referer": "https://www.fotmob.com/",
        })
        self._cache = {}
        self._cache_ttl = 60  # seconds

    def _get(self, endpoint, params=None):
        """Make a GET request with caching."""
        cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        now = time.time()

        if cache_key in self._cache:
            data, ts = self._cache[cache_key]
            if now - ts < self._cache_ttl:
                return data

        url = f"{BASE_URL}/{endpoint}"
        resp = self.session.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        self._cache[cache_key] = (data, now)
        return data

    # --- Search ---

    def search(self, term):
        """Search for teams, players, and leagues."""
        return self._get("search/suggest", params={"term": term})

    # --- Leagues ---

    def all_leagues(self):
        """Get all available leagues."""
        return self._get("allLeagues")

    def league(self, league_id, season=None):
        """Get league details including standings, fixtures, stats."""
        params = {"id": league_id}
        if season:
            params["season"] = season
        return self._get("leagues", params=params)

    # --- Teams ---

    def team(self, team_id):
        """Get team details including squad, fixtures, form."""
        return self._get("teams", params={"id": team_id})

    # --- Transfers ---

    def transfers(self, page=1):
        """Get recent transfers."""
        return self._get("transfers", params={"page": page, "lang": "en"})

    # --- News ---

    def world_news(self, page=1):
        """Get world football news."""
        return self._get("worldnews", params={"page": page, "lang": "en"})

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
