"""Web server — serves the FotMob CLI as a terminal-style web UI.

Run: python web.py
Opens a Flask server + ngrok tunnel so you can access it from your phone.
"""

import sys
import os
import io
import threading
import logging

from flask import Flask, request, jsonify, render_template_string

# Suppress noisy logs
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Add project dir to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

from api import FotMobAPI
from ai_answer import parse_query, generate_answer, summarize_data
from display import format_utc_time

api = FotMobAPI()

app = Flask(__name__)

# ============================================================================
# QUERY HANDLER (reuses our AI two-pass system)
# ============================================================================

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


def _resolve_league(name):
    from nlp import extract_league, fuzzy_match_league
    lid, _, _ = extract_league(name)
    if lid:
        return lid
    return fuzzy_match_league(name)


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


def _format_matches(matches, title="Matches"):
    """Format matches as plain text."""
    lines = [f"  {title}"]
    lines.append(f"  {'Date':<14} {'Home':>20} {'Score':^7} {'Away':<20} {'Status':<8}")
    lines.append("  " + "-" * 72)
    for m in matches:
        home = m.get("home", {})
        away = m.get("away", {})
        status = m.get("status", {})
        h = home.get("shortName", home.get("name", ""))
        a = away.get("shortName", away.get("name", ""))
        score = status.get("scoreStr", "vs")
        reason = status.get("reason", {}).get("short", "")
        if status.get("started") and not status.get("finished"):
            reason = "LIVE"
        date = format_utc_time(status.get("utcTime", ""))
        lines.append(f"  {date:<14} {h:>20} {score:^7} {a:<20} {reason:<8}")
    return "\n".join(lines)


def handle_query(query):
    """Process a query and return plain text response."""
    query = query.strip()
    if not query:
        return "Type a query. Example: arsenal, standings pl, haaland stats"

    import re

    # --- "vs" queries ---
    vs_match = re.search(r'(.+?)\s+vs\.?\s+(.+)', query, re.IGNORECASE)
    if vs_match:
        team_a = vs_match.group(1).strip()
        team_b_raw = vs_match.group(2).strip()

        # Strip trailing intent words from team_b
        team_b = team_b_raw
        for suffix in ["who scored", "who score", "where to watch", "scores", "score",
                        "result", "what is happening", "live", "match", "game",
                        "update", "lineup", "lineups", "stats", "xg", "goals",
                        "scored", "cards", "events", "details", "summary",
                        "watch", "tv", "channel", "odds", "prediction",
                        "injuries", "injured", "referee", "preview",
                        "commentary", "updates"]:
            if team_b.lower().endswith(suffix):
                team_b = team_b[:-(len(suffix))].strip()
                break

        # Any "vs" query should use full match data (browser) for accurate answers
        wants_detail = True

        print(f"[WEB] VS query: team_a={team_a}, team_b={team_b}, wants_detail={wants_detail}", flush=True)
        tid, tname = _resolve_team(team_a)
        print(f"[WEB] Resolved: tid={tid}, tname={tname}", flush=True)
        if tid:
            api._cache = {}
            raw = api.team(tid)

            if wants_detail:
                # Use comprehensive match data extractor
                overview = raw.get("overview", {})
                for mk in ("nextMatch", "lastMatch"):
                    m = overview.get(mk, {})
                    if not m:
                        continue
                    mid = m.get("id")
                    purl = m.get("pageUrl")
                    if mid and purl:
                        try:
                            from browser import get_match_details
                            from match_data import extract_full_match_data, summarize_full_match
                            md = get_match_details(mid, match_url=purl)
                            if md and "content" in md:
                                full_data = extract_full_match_data(md)
                                summary = summarize_full_match(full_data)
                                answer = generate_answer(query, summary)
                                return answer or summary
                        except Exception as e:
                            print(f"[WEB] Browser FAILED: {e}", flush=True)
                        break

            # Standard: just use team data summary
            summary = summarize_data("team", {}, raw)
            summary += f"\nUser is asking about a match against: {team_b}"
            answer = generate_answer(query, summary)
            return answer or f"Could not generate answer for: {query}"

        return f"Could not find team: {team_a}"

    # --- AI two-pass ---
    parsed = parse_query(query)
    if parsed and isinstance(parsed, dict) and "action" in parsed:
        action = parsed["action"]
        params = parsed.get("params", {})

        # Help
        if action == "help":
            return (
                "You can ask things like:\n"
                "  arsenal - Team overview\n"
                "  standings pl - League table\n"
                "  fixtures ucl - Match schedule\n"
                "  did psg lose - Last match result\n"
                "  haaland stats - Player profile\n"
                "  top scorers la liga - Stat leaders\n"
                "  transfers - Latest transfers\n"
                "  news - Headlines\n"
                "  live arsenal - Live match tracking\n"
                "  X vs Y score - Match score"
            )

        # Upcoming — general upcoming matches across leagues
        if action == "upcoming":
            limit = params.get("limit", 5)
            league_ids = [47, 87, 42, 54, 55, 53, 73]
            all_upcoming = []
            for lid in league_ids:
                try:
                    data = api.league(lid)
                    league_name = data.get("details", {}).get("name", "")
                    matches = data.get("fixtures", {}).get("allMatches", [])
                    upcoming = [m for m in matches if not m.get("status", {}).get("finished") and not m.get("status", {}).get("started")]
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

        # Match preview — full match data via browser
        if action == "match_preview":
            team_str = params.get("team", params.get("home", ""))
            if team_str:
                tid, tname = _resolve_team(team_str)
                if tid:
                    api._cache = {}
                    raw = api.team(tid)
                    overview = raw.get("overview", {})
                    for match_key in ("nextMatch", "lastMatch"):
                        m = overview.get(match_key, {})
                        if m:
                            mid = m.get("id")
                            purl = m.get("pageUrl")
                            if mid and purl:
                                from browser import get_match_details
                                from match_data import extract_full_match_data, summarize_full_match
                                page_props = get_match_details(mid, match_url=purl)
                                if page_props and "content" in page_props:
                                    full_data = extract_full_match_data(page_props)
                                    summary = summarize_full_match(full_data)
                                    answer = generate_answer(query, summary)
                                    return answer or summary
                            break
                    # Fallback to team data
                    summary = summarize_data("team", {}, raw)
                    answer = generate_answer(query, summary)
                    return answer or summary
            return "Could not find team for match preview."

        # Commentary — live match commentary
        if action == "commentary":
            team_str = params.get("team", params.get("home", ""))
            if team_str:
                tid, tname = _resolve_team(team_str)
                if tid:
                    api._cache = {}
                    raw = api.team(tid)
                    overview = raw.get("overview", {})
                    for match_key in ("nextMatch", "lastMatch"):
                        m = overview.get(match_key, {})
                        if m and m.get("status", {}).get("started") and not m.get("status", {}).get("finished"):
                            mid = m.get("id")
                            purl = m.get("pageUrl")
                            if mid and purl:
                                from browser import get_match_commentary
                                entries = get_match_commentary(mid, match_url=purl, limit=15)
                                if entries:
                                    h = m.get("home", {}).get("name", "")
                                    a = m.get("away", {}).get("name", "")
                                    score = m.get("status", {}).get("scoreStr", "")
                                    commentary_text = "\n".join([f"{e['minute']}': {e['text']}" for e in entries])
                                    header = f"LIVE: {h} {score} {a}\n\nCommentary:\n{commentary_text}"
                                    answer = generate_answer(query, header)
                                    return answer or header
                            break
                    return f"No live match found for {tname}. Commentary is only available during live matches."
            return "Which team? Try: commentary arsenal"

        # Standings — show full table if user wants it
        if action == "standings":
            q_lower = query.lower()
            wants_full = any(w in q_lower for w in ["full", "table", "standings", "all teams", "complete", "show"])
            lid = _resolve_league(params.get("league", "premier league"))
            if lid:
                raw = api.league(lid)
                if wants_full:
                    return _format_standings(raw)

        # Player — needs browser
        if action == "player":
            player_name = params.get("player", "")
            pid, pname = _resolve_player(player_name)
            if pid:
                from browser import get_player_data
                raw = get_player_data(pid)
                if raw:
                    summary = summarize_data("player", params, raw)
                    answer = generate_answer(query, summary)
                    return answer or summary
            return f"Could not find player: {player_name}"

        # Live — scan leagues
        if action == "live":
            team_str = params.get("team", params.get("league", ""))
            if team_str:
                tid, tname = _resolve_team(team_str)
                if tid:
                    api._cache = {}
                    raw = api.team(tid)
                    summary = summarize_data("team", {}, raw)
                    answer = generate_answer(f"What is happening in {tname}'s current match?", summary)
                    return answer or summary
            # Generic — scan leagues
            lines = []
            for lid in [47, 87, 54, 55, 53, 42, 73, 71, 10562, 130, 61, 62, 57]:
                try:
                    data = api.league(lid)
                    league_name = data.get("details", {}).get("name", "")
                    matches = data.get("fixtures", {}).get("allMatches", [])
                    live = [m for m in matches if m.get("status", {}).get("started") and not m.get("status", {}).get("finished")]
                    for m in live:
                        h = m.get("home", {}).get("name", "")
                        a = m.get("away", {}).get("name", "")
                        s = m.get("status", {}).get("scoreStr", "")
                        lines.append(f"LIVE  {h} {s} {a}  ({league_name})")
                except Exception:
                    continue
            return "\n".join(lines) if lines else "No live matches in major leagues right now."

        # All other actions — fetch data, AI curate
        raw = None
        try:
            if action == "standings":
                lid = _resolve_league(params.get("league", "premier league"))
                if lid:
                    raw = api.league(lid)
            elif action == "fixtures":
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
        except Exception:
            raw = None

        if raw is not None:
            summary = summarize_data(action, params, raw)
            answer = generate_answer(query, summary)
            if answer:
                return answer
            return summary

    # Fallback: try as team name
    tid, tname = _resolve_team(query)
    if tid:
        raw = api.team(tid)
        summary = summarize_data("team", {}, raw)
        answer = generate_answer(query, summary)
        return answer or summary

    # Fallback: try as player
    pid, pname = _resolve_player(query)
    if pid:
        from browser import get_player_data
        raw = get_player_data(pid)
        if raw:
            summary = summarize_data("player", {}, raw)
            answer = generate_answer(query, summary)
            return answer or summary

    return f"Couldn't understand: '{query}'. Try a team name, league, or player."


# ============================================================================
# HTML TEMPLATE — Terminal-style UI
# ============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>FotMob CLI</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { height: 100vh; display: flex; flex-direction: column; font-size: 14px; transition: all 0.3s; }

        /* ========== HEADER ========== */
        #header {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 16px; z-index: 10;
        }
        #header h1 { font-size: 16px; margin: 0; }
        #mode-toggle {
            background: none; border: 1px solid; border-radius: 20px;
            padding: 4px 14px; font-size: 12px; cursor: pointer; transition: all 0.3s;
        }

        /* ========== OUTPUT AREA ========== */
        #output { flex: 1; overflow-y: auto; padding: 12px 16px; }

        /* ========== INPUT BAR ========== */
        #input-bar { display: flex; padding: 8px 12px; align-items: center; gap: 8px; }
        #query-input {
            flex: 1; border: none; outline: none; font-size: 16px; padding: 10px 14px;
            border-radius: 24px; transition: all 0.3s;
        }
        #send-btn {
            width: 42px; height: 42px; border-radius: 50%; border: none;
            font-size: 18px; cursor: pointer; transition: all 0.3s;
            display: flex; align-items: center; justify-content: center;
        }
        #send-btn:disabled { opacity: 0.4; }

        /* ========== TERMINAL MODE ========== */
        body.terminal {
            background: #0d1117; color: #c9d1d9;
            font-family: 'Courier New', 'Consolas', monospace;
        }
        .terminal #header { background: #0d1117; border-bottom: 1px solid #30363d; }
        .terminal #header h1 { color: #58a6ff; }
        .terminal #mode-toggle { color: #8b949e; border-color: #30363d; }
        .terminal #mode-toggle:hover { color: #c9d1d9; border-color: #58a6ff; }
        .terminal #output { white-space: pre-wrap; word-wrap: break-word; line-height: 1.5; padding: 12px 16px; }
        .terminal #input-bar { background: #161b22; border-top: 1px solid #30363d; }
        .terminal #query-input {
            background: transparent; color: #c9d1d9; border-radius: 0;
            font-family: 'Courier New', 'Consolas', monospace; padding: 8px 0;
        }
        .terminal #query-input::placeholder { color: #484f58; }
        .terminal #send-btn {
            background: #238636; color: white; border-radius: 6px;
            width: auto; height: auto; padding: 8px 16px; font-size: 14px;
            font-family: 'Courier New', 'Consolas', monospace;
        }
        .terminal .msg-row { display: block !important; }
        .terminal .msg-row .msg-bubble { all: unset; }
        .terminal .msg-row .msg-time { display: none; }
        .terminal .msg-row .bot-avatar { display: none; }
        .terminal .msg-row.user .msg-bubble { color: #3fb950; }
        .terminal .msg-row.user .msg-bubble::before { content: "> "; }
        .terminal .msg-row.bot .msg-bubble {
            color: #c9d1d9; display: block; white-space: pre-wrap;
            margin-bottom: 6px; max-width: 100%; background: none;
            box-shadow: none; padding: 0; border-radius: 0;
        }
        .terminal .msg-row.bot.msg-loading .msg-bubble { color: #8b949e; font-style: italic; background: none; }
        .terminal .msg-row.bot.msg-error .msg-bubble { color: #f85149; background: none; }
        .terminal .msg-user { color: #3fb950; margin-top: 10px; }
        .terminal .msg-user::before { content: "> "; }
        .terminal .msg-bot { color: #c9d1d9; margin-bottom: 6px; white-space: pre-wrap; }
        .terminal .msg-loading { color: #8b949e; font-style: italic; }
        .terminal .msg-error { color: #f85149; }

        /* ========== CHAT MODE ========== */
        body.chat {
            background: #e5ddd5;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            color: #111;
        }
        .chat #header { background: #075e54; color: white; }
        .chat #header h1 { color: white; font-size: 17px; }
        .chat #mode-toggle { color: rgba(255,255,255,0.8); border-color: rgba(255,255,255,0.4); }
        .chat #mode-toggle:hover { color: white; border-color: white; }
        .chat #output {
            background: #e5ddd5 url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L35 15 L30 12 L25 15Z' fill='%23d4ccb5' opacity='0.3'/%3E%3C/svg%3E");
            padding: 16px;
        }
        .chat #input-bar { background: #f0f0f0; border-top: 1px solid #d1d1d1; padding: 8px; }
        .chat #query-input { background: white; color: #111; }
        .chat #query-input::placeholder { color: #999; }
        .chat #send-btn { background: #075e54; color: white; }

        .chat .msg-row { display: flex; margin-bottom: 8px; }
        .chat .msg-row.user { justify-content: flex-end; }
        .chat .msg-row.bot { justify-content: flex-start; }

        .chat .msg-bubble {
            max-width: 85%; padding: 8px 12px; border-radius: 12px;
            font-size: 14px; line-height: 1.45; white-space: pre-wrap;
            word-wrap: break-word; position: relative;
        }
        .chat .msg-row.user .msg-bubble {
            background: #dcf8c6; color: #111; border-bottom-right-radius: 4px;
        }
        .chat .msg-row.bot .msg-bubble {
            background: white; color: #111; border-bottom-left-radius: 4px;
            box-shadow: 0 1px 1px rgba(0,0,0,0.1);
        }
        .chat .msg-time {
            font-size: 11px; color: #999; margin-top: 3px;
            text-align: right;
        }
        .chat .msg-row.bot .msg-time { text-align: left; }
        .chat .msg-loading .msg-bubble { background: #f5f5f5; color: #888; font-style: italic; }
        .chat .msg-error .msg-bubble { background: #ffe0e0; color: #c00; }

        .chat .bot-avatar {
            width: 30px; height: 30px; border-radius: 50%; background: #075e54;
            color: white; display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: bold; margin-right: 8px; flex-shrink: 0;
            align-self: flex-end;
        }

        /* ========== RESPONSIVE ========== */
        @media (max-width: 600px) {
            body { font-size: 13px; }
            .chat .msg-bubble { max-width: 90%; font-size: 14px; }
        }
        @media (min-width: 768px) {
            #output { max-width: 800px; margin: 0 auto; width: 100%; }
        }
    </style>
</head>
<body class="chat">
    <div id="header">
        <h1>FotMob</h1>
        <button id="mode-toggle" onclick="toggleMode()">Terminal</button>
    </div>
    <div id="output" role="log"></div>
    <div id="input-bar">
        <input type="text" id="query-input" placeholder="Ask about football..." autocomplete="off" autofocus>
        <button id="send-btn" onclick="sendQuery()">&#10148;</button>
    </div>

    <script>
        const output = document.getElementById('output');
        const input = document.getElementById('query-input');
        const btn = document.getElementById('send-btn');
        const toggle = document.getElementById('mode-toggle');
        let mode = localStorage.getItem('ui_mode') || 'chat';

        function setMode(m) {
            mode = m;
            document.body.className = m;
            toggle.textContent = m === 'chat' ? 'Terminal' : 'Chat';
            btn.innerHTML = m === 'chat' ? '&#10148;' : 'Go';
            localStorage.setItem('ui_mode', m);
        }
        function toggleMode() {
            setMode(mode === 'chat' ? 'terminal' : 'chat');
        }
        setMode(mode);

        // Welcome message
        addBot('Football data at your fingertips. Ask anything!\\nExamples: arsenal, standings pl, haaland stats, did psg lose');

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && input.value.trim()) sendQuery();
        });

        function getTime() {
            return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        }

        function addUser(text) {
            if (mode === 'chat') {
                const row = document.createElement('div');
                row.className = 'msg-row user';
                row.innerHTML = '<div><div class="msg-bubble">' + esc(text) +
                    '</div><div class="msg-time">' + getTime() + '</div></div>';
                output.appendChild(row);
            } else {
                const d = document.createElement('div');
                d.className = 'msg-user';
                d.textContent = text;
                output.appendChild(d);
            }
            scrollDown();
        }

        function addBot(text, isError) {
            if (mode === 'chat') {
                const row = document.createElement('div');
                row.className = 'msg-row bot' + (isError ? ' msg-error' : '');
                row.innerHTML = '<div class="bot-avatar">F</div><div><div class="msg-bubble">' +
                    esc(text) + '</div><div class="msg-time">' + getTime() + '</div></div>';
                output.appendChild(row);
            } else {
                const d = document.createElement('div');
                d.className = isError ? 'msg-error' : 'msg-bot';
                d.textContent = text;
                output.appendChild(d);
            }
            scrollDown();
        }

        function addLoading() {
            const id = 'load-' + Date.now();
            if (mode === 'chat') {
                const row = document.createElement('div');
                row.className = 'msg-row bot msg-loading';
                row.id = id;
                row.innerHTML = '<div class="bot-avatar">F</div><div><div class="msg-bubble">Thinking...</div></div>';
                output.appendChild(row);
            } else {
                const d = document.createElement('div');
                d.className = 'msg-loading';
                d.id = id;
                d.textContent = 'Processing...';
                output.appendChild(d);
            }
            scrollDown();
            return id;
        }

        function removeLoading(id) {
            const el = document.getElementById(id);
            if (el) el.remove();
        }

        function esc(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>'); }
        function scrollDown() { output.scrollTop = output.scrollHeight; }

        async function sendQuery() {
            const query = input.value.trim();
            if (!query) return;

            addUser(query);
            const loadId = addLoading();
            input.value = '';
            btn.disabled = true;

            try {
                const res = await fetch('/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: query})
                });
                const data = await res.json();
                removeLoading(loadId);
                addBot(data.response || data.error, !!data.error);
            } catch (err) {
                removeLoading(loadId);
                addBot('Network error: ' + err.message, true);
            }
            btn.disabled = false;
            input.focus();
        }
    </script>
</body>
</html>"""


# ============================================================================
# ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/query", methods=["POST"])
def query_endpoint():
    data = request.get_json()
    q = data.get("query", "").strip()
    if not q:
        return jsonify({"error": "Empty query"})
    try:
        response = handle_query(q)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)})


# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    is_cloud = os.environ.get("RENDER") or os.environ.get("PORT")

    if is_cloud:
        # Running on Render/cloud — just start Flask
        print(f"Starting FotMob Web CLI on port {port} (cloud mode)")
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        # Running locally — start ngrok tunnel too
        import subprocess, time

        print(f"\n  Starting FotMob Web CLI on port {port}...")
        print(f"  Local: http://localhost:{port}")
        print(f"\n  Starting ngrok tunnel...")

        try:
            subprocess.run(["taskkill", "/f", "/im", "ngrok.exe"],
                           capture_output=True, timeout=5)
        except Exception:
            pass

        ngrok_proc = subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(3)

        try:
            import urllib.request, json as _json
            resp = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=5)
            tunnels = _json.loads(resp.read())
            public_url = tunnels["tunnels"][0]["public_url"]
            print(f"\n  ====================================")
            print(f"  PUBLIC URL: {public_url}")
            print(f"  ====================================")
            print(f"\n  Open this URL on your phone's Chrome!")
            print(f"  Press Ctrl+C to stop.\n")
        except Exception as e:
            print(f"  ngrok URL not ready. Check http://localhost:4040\n")

        try:
            app.run(host="0.0.0.0", port=port, debug=False)
        except KeyboardInterrupt:
            pass
        finally:
            ngrok_proc.terminate()
            print("\n  Server stopped.")
