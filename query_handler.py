"""Unified query handler — single source of truth for ALL query processing.

Both web.py and interactive.py call handle_query() from here.
No more duplicated logic.
"""

import re
import logging

from api import FotMobAPI
from ai_answer import parse_query, generate_answer, summarize_data
from nlp import extract_league, fuzzy_match_league, NOISE_WORDS

logger = logging.getLogger(__name__)

api = FotMobAPI()

# Shared league IDs for scanning
MAJOR_LEAGUE_IDS = [47, 87, 54, 55, 53, 42, 73, 71, 10562, 130, 61, 62, 57]


def _resolve_team(name):
    if not name:
        return None, None
    results = api.search(name)
    for group in results:
        for s in group.get("suggestions", []):
            if s.get("type") == "team":
                return s.get("id"), s.get("name", name)
    return None, None


def _resolve_player(name):
    if not name:
        return None, None
    results = api.search(name)
    for group in results:
        for s in group.get("suggestions", []):
            if s.get("type") == "player":
                return s.get("id"), s.get("name", name)
    return None, None


def _resolve_league(param):
    if not param:
        return None
    lid, _, _ = extract_league(param)
    if lid:
        return lid
    return fuzzy_match_league(param)


def _get_match_from_team(team_id):
    """Get the next/last match for a team. Returns (match_dict, team_data)."""
    api._cache = {}  # Fresh data
    raw = api.team(team_id)
    overview = raw.get("overview", {})
    for key in ("nextMatch", "lastMatch"):
        m = overview.get(key)
        if m:
            return m, raw
    return None, raw


def _browser_match_data(match_id, page_url):
    """Fetch full match data via browser. Returns summary text or None."""
    try:
        from browser import get_match_details
        from match_data import extract_full_match_data, summarize_full_match
        md = get_match_details(match_id, match_url=page_url)
        if md and "content" in md:
            full = extract_full_match_data(md)
            return summarize_full_match(full)
    except Exception as e:
        logger.warning("Browser match data failed: %s", e)
    return None


def _browser_player_data(player_id):
    """Fetch player data via browser. Returns summary text or None."""
    try:
        from browser import get_player_data
        raw = get_player_data(player_id)
        if raw:
            return summarize_data("player", {}, raw)
    except Exception as e:
        logger.warning("Browser player data failed: %s", e)
    return None


def _browser_commentary(match_id, page_url):
    """Fetch live commentary. Returns text or None."""
    try:
        from browser import get_match_commentary
        entries = get_match_commentary(match_id, match_url=page_url, limit=15)
        if entries:
            return "\n".join([f"{e['minute']}': {e['text']}" for e in entries])
    except Exception as e:
        logger.warning("Browser commentary failed: %s", e)
    return None


# =========================================================================
# MAIN HANDLER
# =========================================================================

def handle_query(query):
    """Process any query and return a plain text response.

    This is the SINGLE function both web.py and interactive.py should call.
    """
    query = query.strip()
    if not query:
        return "Type a query. Example: arsenal, standings pl, haaland stats"

    # === "X vs Y" queries — top priority ===
    vs_match = re.search(r'(.+?)\s+vs\.?\s+(.+)', query, re.IGNORECASE)
    if vs_match:
        return _handle_vs_query(query, vs_match)

    # === AI parse ===
    parsed = parse_query(query)
    if parsed and isinstance(parsed, dict) and "action" in parsed:
        result = _handle_action(query, parsed)
        if result:
            return result

    # === Fallback: bare league name → standings ===
    lid, _, remaining = extract_league(query)
    if lid and not remaining.strip():
        raw = api.league(lid)
        summary = summarize_data("standings", {}, raw)
        answer = generate_answer(query, summary)
        return answer or summary

    # === Fallback: team name ===
    tid, tname = _resolve_team(query)
    if tid:
        raw = api.team(tid)
        summary = summarize_data("team", {}, raw)
        answer = generate_answer(query, summary)
        return answer or summary

    # === Fallback: player name ===
    pid, pname = _resolve_player(query)
    if pid:
        summary = _browser_player_data(pid)
        if summary:
            answer = generate_answer(query, summary)
            return answer or summary
        return f"Could not load data for {pname}. Browser may be unavailable."

    return f"Couldn't understand: '{query}'. Try a team name, league, or player."


def _handle_vs_query(query, vs_match):
    """Handle X vs Y queries with full match data."""
    team_a = vs_match.group(1).strip()
    team_b_raw = vs_match.group(2).strip()

    # Clean team_a prefix
    for prefix in ["what is happening in", "whats happening in", "commentary for",
                    "updates for", "show me", "give me", "tell me about"]:
        if team_a.lower().startswith(prefix):
            team_a = team_a[len(prefix):].strip()
            break

    # Clean team_b suffix
    team_b = team_b_raw
    for suffix in ["who scored", "who score", "where to watch", "scores", "score",
                    "result", "what is happening", "live", "match", "game",
                    "update", "lineup", "lineups", "stats", "xg", "goals",
                    "scored", "cards", "events", "details", "summary",
                    "watch", "tv", "channel", "odds", "prediction",
                    "injuries", "injured", "referee", "preview",
                    "commentary", "updates", "weather", "coach",
                    "head to head", "h2h", "insights"]:
        if team_b.lower().endswith(suffix):
            team_b = team_b[:-(len(suffix))].strip()
            break

    # Check if user wants live commentary
    wants_commentary = any(w in query.lower() for w in
        ["commentary", "updates", "happening", "going on", "whats happening"])

    tid, tname = _resolve_team(team_a)
    if not tid:
        return f"Could not find team: {team_a}"

    match, raw = _get_match_from_team(tid)
    if not match:
        return f"No match found for {tname}."

    mid = match.get("id")
    purl = match.get("pageUrl")
    home = match.get("home", {}).get("name", "")
    away = match.get("away", {}).get("name", "")
    score = match.get("status", {}).get("scoreStr", "")
    is_live = match.get("status", {}).get("started") and not match.get("status", {}).get("finished")

    # Commentary request
    if wants_commentary and is_live and mid and purl:
        commentary = _browser_commentary(mid, purl)
        if commentary:
            header = f"LIVE: {home} {score} {away}\n\nCommentary:\n{commentary}"
            answer = generate_answer(query, header)
            return answer or header
        return f"Live: {home} {score} {away} — commentary not available."

    # Full match data via browser
    if mid and purl:
        summary = _browser_match_data(mid, purl)
        if summary:
            answer = generate_answer(query, summary)
            if answer:
                return answer
            # AI failed but we have data — return summary
            return summary

    # Fallback: team API data only (no browser)
    summary = summarize_data("team", {}, raw)
    summary += f"\nUser is asking about: {home} vs {away}"
    if score:
        summary += f"\nScore: {score}"
    answer = generate_answer(query, summary)
    return answer or f"{home} {score or 'vs'} {away}"


def _handle_action(query, parsed):
    """Handle a parsed AI action."""
    action = parsed["action"]
    params = parsed.get("params", {})

    if action == "help":
        return (
            "You can ask things like:\n"
            "  arsenal — Team overview\n"
            "  standings pl — League table\n"
            "  fixtures ucl — Match schedule\n"
            "  did psg lose — Last match result\n"
            "  haaland stats — Player profile\n"
            "  top scorers la liga — Stat leaders\n"
            "  arsenal vs man city watch — TV channels\n"
            "  arsenal vs man city odds — Betting odds\n"
            "  transfers — Latest transfers\n"
            "  news — Headlines\n"
            "  live arsenal — Live tracking\n"
            "  give me 5 scheduled matches — Upcoming"
        )

    if action == "leagues":
        data = api.all_leagues()
        popular = data.get("popular", [])
        lines = ["Popular leagues:"]
        for lg in popular:
            lines.append(f"  {lg.get('id')}: {lg.get('name')}")
        return "\n".join(lines)

    # Match preview — full data via browser
    if action == "match_preview":
        team_str = params.get("team", params.get("home", ""))
        if team_str:
            tid, tname = _resolve_team(team_str)
            if tid:
                match, raw = _get_match_from_team(tid)
                if match:
                    mid = match.get("id")
                    purl = match.get("pageUrl")
                    if mid and purl:
                        summary = _browser_match_data(mid, purl)
                        if summary:
                            answer = generate_answer(query, summary)
                            return answer or summary
                # Fallback to team data
                summary = summarize_data("team", {}, raw)
                answer = generate_answer(query, summary)
                return answer or summary
        return "Could not find team for match preview."

    # Commentary
    if action == "commentary":
        team_str = params.get("team", params.get("home", ""))
        if team_str:
            tid, tname = _resolve_team(team_str)
            if tid:
                match, raw = _get_match_from_team(tid)
                if match and match.get("status", {}).get("started") and not match.get("status", {}).get("finished"):
                    mid = match.get("id")
                    purl = match.get("pageUrl")
                    if mid and purl:
                        commentary = _browser_commentary(mid, purl)
                        if commentary:
                            home = match.get("home", {}).get("name", "")
                            away = match.get("away", {}).get("name", "")
                            score = match.get("status", {}).get("scoreStr", "")
                            header = f"LIVE: {home} {score} {away}\n\nCommentary:\n{commentary}"
                            answer = generate_answer(query, header)
                            return answer or header
                return f"No live match found for {tname}."
        return "Which team? Try: commentary arsenal"

    # Upcoming — general fixtures across leagues
    if action == "upcoming":
        limit = params.get("limit", 5)
        all_upcoming = []
        for lid in MAJOR_LEAGUE_IDS[:7]:
            try:
                data = api.league(lid)
                league_name = data.get("details", {}).get("name", "")
                matches = data.get("fixtures", {}).get("allMatches", [])
                upcoming = [m for m in matches if not m.get("status", {}).get("finished")
                            and not m.get("status", {}).get("started")]
                for m in upcoming[:2]:
                    h = m.get("home", {}).get("name", "")
                    a = m.get("away", {}).get("name", "")
                    date = m.get("status", {}).get("utcTime", "")
                    all_upcoming.append(f"{h} vs {a} | {date[:10]} | {league_name}")
            except Exception:
                continue
        if all_upcoming:
            summary = "Upcoming matches:\n" + "\n".join(all_upcoming[:int(limit)])
            answer = generate_answer(query, summary)
            return answer or summary
        return "No upcoming matches found."

    # Player — needs browser
    if action == "player":
        player_name = params.get("player", "")
        pid, pname = _resolve_player(player_name)
        if pid:
            summary = _browser_player_data(pid)
            if summary:
                answer = generate_answer(query, summary)
                return answer or summary
            return f"Could not load data for {pname}. Try again."
        return f"Could not find player: {player_name}"

    # Live — scan for live matches
    if action == "live":
        team_str = params.get("team", params.get("league", params.get("match", "")))
        if team_str:
            # Extract first team from "X vs Y" format
            if "vs" in team_str.lower():
                team_str = team_str.split("vs")[0].strip()
            tid, tname = _resolve_team(team_str)
            if tid:
                api._cache = {}
                raw = api.team(tid)
                summary = summarize_data("team", {}, raw)
                answer = generate_answer(f"What is the current status of {tname}?", summary)
                return answer or summary
        # Generic — scan leagues
        lines = []
        for lid in MAJOR_LEAGUE_IDS:
            try:
                data = api.league(lid)
                league_name = data.get("details", {}).get("name", "")
                matches = data.get("fixtures", {}).get("allMatches", [])
                live = [m for m in matches if m.get("status", {}).get("started")
                        and not m.get("status", {}).get("finished")]
                for m in live:
                    h = m.get("home", {}).get("name", "")
                    a = m.get("away", {}).get("name", "")
                    s = m.get("status", {}).get("scoreStr", "")
                    lines.append(f"LIVE: {h} {s} {a} ({league_name})")
            except Exception:
                continue
        return "\n".join(lines) if lines else "No live matches in major leagues right now."

    # Standings
    if action == "standings":
        q_lower = query.lower()
        wants_full = any(w in q_lower for w in ["full", "table", "standings", "all", "complete", "show"])
        lid = _resolve_league(params.get("league", "premier league"))
        if lid:
            raw = api.league(lid)
            summary = summarize_data("standings", {}, raw)
            if wants_full:
                return _format_standings(raw)
            answer = generate_answer(query, summary)
            return answer or summary
        return "Could not find that league."

    # All other API-based actions
    raw = None
    try:
        if action == "fixtures":
            lid = _resolve_league(params.get("league", ""))
            if lid:
                raw = api.league(lid)
        elif action in ("team", "form"):
            tid, _ = _resolve_team(params.get("team", ""))
            if tid:
                raw = api.team(tid)
        elif action == "team_fixtures":
            tid, _ = _resolve_team(params.get("team", ""))
            if tid:
                raw = api.team(tid)
        elif action in ("last_match", "next_match"):
            tid, _ = _resolve_team(params.get("team", ""))
            if tid:
                raw = api.team(tid)
        elif action == "squad":
            tid, _ = _resolve_team(params.get("team", ""))
            if tid:
                raw = api.team(tid)
        elif action == "top_scorers":
            lid = _resolve_league(params.get("league", "premier league"))
            if lid:
                league_data = api.league(lid)
                players = league_data.get("stats", {}).get("players", [])
                stat = params.get("stat", "goals")
                target = None
                for p in players:
                    if stat in p.get("header", "").lower():
                        target = p
                        break
                if not target and players:
                    target = players[0]
                if target and target.get("fetchAllUrl"):
                    full = api.league_stats(target["fetchAllUrl"])
                    tl = full.get("TopLists", [])
                    raw = tl[0].get("StatList", [])[:10] if tl else []
                else:
                    raw = []
        elif action == "transfers":
            team = params.get("team", "")
            if team:
                tid, _ = _resolve_team(team)
                if tid:
                    raw = api.team(tid)
            else:
                raw = api.transfers()
        elif action == "news":
            raw = api.world_news()
        elif action == "search":
            results = api.search(params.get("query", query))
            lines = []
            for group in results:
                for s in group.get("suggestions", []):
                    stype = s.get("type", "")
                    name = s.get("name", s.get("homeTeamName", ""))
                    lines.append(f"[{stype}] {name} (ID: {s.get('id', '')})")
            return "\n".join(lines) if lines else "No results found."
    except Exception as e:
        logger.warning("Action %s failed: %s", action, e)
        raw = None

    if raw is not None:
        summary = summarize_data(action, params, raw)
        answer = generate_answer(query, summary)
        return answer or summary

    return None


def _format_standings(league_data):
    """Format standings as plain text table."""
    lines = []
    for group in league_data.get("table", []):
        data = group.get("data", {})
        league_name = data.get("leagueName", "")
        standings = data.get("table", {}).get("all", [])
        if not standings:
            continue
        lines.append(f"  {league_name}")
        lines.append(f"  {'#':>3}  {'Team':<22} {'MP':>3} {'W':>3} {'D':>3} {'L':>3} {'GF-GA':>7} {'GD':>4} {'Pts':>4}")
        lines.append("  " + "-" * 60)
        for t in standings:
            lines.append(
                f"  {t.get('idx',''):>3}  {t.get('shortName', t.get('name','')):.<22} "
                f"{t.get('played',''):>3} {t.get('wins',''):>3} {t.get('draws',''):>3} "
                f"{t.get('losses',''):>3} {t.get('scoresStr',''):>7} {t.get('goalConDiff',''):>4} "
                f"{t.get('pts',''):>4}"
            )
    return "\n".join(lines)
