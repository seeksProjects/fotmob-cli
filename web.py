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
        for suffix in ["who scored", "who score", "scores", "score", "result",
                        "what is happening", "live", "match", "game", "update",
                        "lineup", "lineups", "stats", "xg", "goals", "scored",
                        "cards", "events", "details", "summary"]:
            if team_b.lower().endswith(suffix):
                team_b = team_b[:-(len(suffix))].strip()
                break

        # Check if user wants detailed events
        detail_words = {"scored", "scorer", "score", "goal", "goals", "who scored",
                        "who score", "lineup", "lineups", "cards", "events", "xg",
                        "stats", "details"}
        wants_detail = any(w in query.lower() for w in detail_words)

        print(f"[WEB] VS query: team_a={team_a}, team_b={team_b}, wants_detail={wants_detail}", flush=True)
        tid, tname = _resolve_team(team_a)
        print(f"[WEB] Resolved: tid={tid}, tname={tname}", flush=True)
        if tid:
            api._cache = {}
            raw = api.team(tid)

            if wants_detail:
                # Try to find the match and fetch details via browser
                overview = raw.get("overview", {})
                for mk in ("nextMatch", "lastMatch"):
                    m = overview.get(mk, {})
                    if not m:
                        continue
                    mid = m.get("id")
                    purl = m.get("pageUrl")
                    print(f"[WEB] Detail fetch: mk={mk}, mid={mid}, purl={purl}", flush=True)
                    if mid and purl:
                        try:
                            from browser import get_match_details
                            md = get_match_details(mid, match_url=purl)
                            print(f"[WEB] Browser returned: {type(md)}, has content: {'content' in md if md else False}", flush=True)
                        except Exception as e:
                            print(f"[WEB] Browser FAILED: {e}", flush=True)
                            md = None
                        if md and "content" in md:
                            events = md.get("content", {}).get("matchFacts", {}).get("events", {}).get("events", [])
                            header = md.get("header", {})
                            teams_h = header.get("teams", [])
                            hn = teams_h[0].get("name", "") if teams_h else ""
                            an = teams_h[1].get("name", "") if len(teams_h) > 1 else ""
                            hs = teams_h[0].get("score", "") if teams_h else ""
                            as_ = teams_h[1].get("score", "") if len(teams_h) > 1 else ""
                            status = header.get("status", {})
                            is_live = status.get("started") and not status.get("finished")

                            ev_lines = [f"Match: {hn} {hs} - {as_} {an}"]
                            if is_live:
                                ev_lines.append("Status: LIVE (match is currently being played)")
                            for ev in events:
                                if ev.get("type") == "Goal":
                                    pname = ev.get("player", {}).get("name", "Unknown")
                                    assist = ev.get("assistStr", "")
                                    side = hn if ev.get("isHome") else an
                                    ev_lines.append(f"GOAL {ev.get('timeStr')}': {pname} ({side})" +
                                                    (f" - {assist}" if assist else ""))
                                elif ev.get("type") == "Card":
                                    ev_lines.append(f"CARD {ev.get('timeStr')}': {ev.get('player', {}).get('name', '')} ({ev.get('card', '')})")
                                elif ev.get("type") == "Substitution":
                                    swap = ev.get("swap", [])
                                    p_on = swap[0].get("name", "") if len(swap) > 0 else ""
                                    p_off = swap[1].get("name", "") if len(swap) > 1 else ""
                                    if p_on or p_off:
                                        ev_lines.append(f"SUB {ev.get('timeStr')}': {p_on} on, {p_off} off")

                            if not any("GOAL" in l for l in ev_lines):
                                ev_lines.append("No goals scored yet.")

                            summary = "\n".join(ev_lines)
                            answer = generate_answer(query, summary)
                            return answer or summary
                        break  # Only try one match

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

        body {
            background: #0d1117;
            color: #c9d1d9;
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 14px;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        #header {
            padding: 12px 16px;
            border-bottom: 1px solid #30363d;
            color: #58a6ff;
            font-weight: bold;
            font-size: 15px;
        }

        #output {
            flex: 1;
            overflow-y: auto;
            padding: 12px 16px;
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.5;
        }

        .query-line {
            color: #3fb950;
            margin-top: 12px;
        }

        .response-line {
            color: #c9d1d9;
            margin-bottom: 8px;
        }

        .loading {
            color: #8b949e;
            font-style: italic;
        }

        .error {
            color: #f85149;
        }

        #input-bar {
            display: flex;
            border-top: 1px solid #30363d;
            background: #161b22;
            padding: 8px 12px;
            align-items: center;
            gap: 8px;
        }

        #input-bar span {
            color: #3fb950;
            font-weight: bold;
            font-size: 16px;
        }

        #query-input {
            flex: 1;
            background: transparent;
            border: none;
            color: #c9d1d9;
            font-family: inherit;
            font-size: 16px;
            outline: none;
            padding: 8px 0;
        }

        #query-input::placeholder {
            color: #484f58;
        }

        #send-btn {
            background: #238636;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-family: inherit;
            font-size: 14px;
            cursor: pointer;
        }

        #send-btn:active { background: #2ea043; }
        #send-btn:disabled { background: #21262d; color: #484f58; }

        @media (max-width: 600px) {
            body { font-size: 13px; }
            #query-input { font-size: 16px; }
        }
    </style>
</head>
<body>
    <div id="header">FotMob CLI</div>
    <div id="output">
        <div class="response-line">Football data in your terminal. Type a query below.</div>
        <div class="response-line" style="color: #8b949e;">Examples: arsenal, standings pl, haaland stats, did psg lose</div>
    </div>
    <div id="input-bar">
        <span>&gt;</span>
        <input type="text" id="query-input" placeholder="Type a query..." autocomplete="off" autofocus>
        <button id="send-btn" onclick="sendQuery()">Go</button>
    </div>

    <script>
        const output = document.getElementById('output');
        const input = document.getElementById('query-input');
        const btn = document.getElementById('send-btn');

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && input.value.trim()) sendQuery();
        });

        async function sendQuery() {
            const query = input.value.trim();
            if (!query) return;

            // Show query
            const qDiv = document.createElement('div');
            qDiv.className = 'query-line';
            qDiv.textContent = '> ' + query;
            output.appendChild(qDiv);

            // Show loading
            const loadDiv = document.createElement('div');
            loadDiv.className = 'loading';
            loadDiv.textContent = 'Processing...';
            output.appendChild(loadDiv);

            input.value = '';
            btn.disabled = true;
            output.scrollTop = output.scrollHeight;

            try {
                const res = await fetch('/query', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: query})
                });
                const data = await res.json();

                loadDiv.remove();
                const rDiv = document.createElement('div');
                rDiv.className = data.error ? 'error' : 'response-line';
                rDiv.textContent = data.response || data.error;
                output.appendChild(rDiv);
            } catch (err) {
                loadDiv.remove();
                const eDiv = document.createElement('div');
                eDiv.className = 'error';
                eDiv.textContent = 'Network error: ' + err.message;
                output.appendChild(eDiv);
            }

            btn.disabled = false;
            input.focus();
            output.scrollTop = output.scrollHeight;
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
