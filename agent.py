"""Football AI Agent — function calling with multi-step reasoning.

Uses Groq's native tool/function calling. The AI decides which tools to call,
can call multiple in sequence, and reasons about results before responding.
"""

import json
import logging
from config import get_key

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a football data assistant with tools. Use them to answer questions.

STRATEGY:
- Use search() first to find team/player IDs
- For age/roster: search then get_squad (fast)
- For match details/preview/lineups/injuries: search then get_match_data (slow, browser)
- For standings: get_standings directly (47=PL, 87=LaLiga, 54=Bundesliga, 55=SerieA, 53=Ligue1, 42=UCL, 73=UEL, 57=Eredivisie)
- For TV: get_tv_channels (just team names, no ID needed)
- For odds: get_odds (just team names)
- For player career/stats: search then get_player (slow, browser)

RULES:
- Fix typos before searching
- Keep responses concise (1-5 lines simple, up to 10 for previews)
- TV preference: US, European, South American channels first
- Curate human-readable answers, don't dump raw data"""

TOOLS = [
    {"type": "function", "function": {"name": "search", "description": "Search FotMob for teams, players, leagues. Returns IDs.", "parameters": {"type": "object", "properties": {"term": {"type": "string", "description": "Search term"}}, "additionalProperties": False, "required": ["term"]}}},
    {"type": "function", "function": {"name": "get_standings", "description": "League standings (47=PL, 87=LaLiga, 54=Bundesliga, 55=SerieA, 53=Ligue1, 42=UCL)", "parameters": {"type": "object", "properties": {"league_id": {"type": "integer", "description": "League ID"}}, "additionalProperties": False, "required": ["league_id"]}}},
    {"type": "function", "function": {"name": "get_team", "description": "Team overview: form, next/last match. Fast.", "parameters": {"type": "object", "properties": {"team_id": {"type": "integer", "description": "Team ID"}}, "additionalProperties": False, "required": ["team_id"]}}},
    {"type": "function", "function": {"name": "get_squad", "description": "Team roster with names, ages, positions, shirts. Fast.", "parameters": {"type": "object", "properties": {"team_id": {"type": "integer", "description": "Team ID"}}, "additionalProperties": False, "required": ["team_id"]}}},
    {"type": "function", "function": {"name": "get_match_data", "description": "FULL match data via browser (SLOW): lineups, referee, weather, injuries, H2H, stats.", "parameters": {"type": "object", "properties": {"team_id": {"type": "integer", "description": "Team ID"}}, "additionalProperties": False, "required": ["team_id"]}}},
    {"type": "function", "function": {"name": "get_tv_channels", "description": "TV channels for a match from LiveSoccerTV. US/Europe/Americas.", "parameters": {"type": "object", "properties": {"team_name": {"type": "string", "description": "Team name"}, "opponent_name": {"type": "string", "description": "Opponent"}}, "additionalProperties": False, "required": ["team_name"]}}},
    {"type": "function", "function": {"name": "get_odds", "description": "Betting odds from bookmakers.", "parameters": {"type": "object", "properties": {"home_team": {"type": "string", "description": "Home team"}, "away_team": {"type": "string", "description": "Away team"}}, "additionalProperties": False, "required": ["home_team"]}}},
    {"type": "function", "function": {"name": "get_player", "description": "Detailed player profile via browser (SLOW): career, stats, matches.", "parameters": {"type": "object", "properties": {"player_id": {"type": "integer", "description": "Player ID"}}, "additionalProperties": False, "required": ["player_id"]}}},
]


def _exec_tool(name, args):
    from api import FotMobAPI
    api = FotMobAPI()
    try:
        if name == "search":
            results = api.search(args.get("term", ""))
            lines = []
            for group in results:
                for s in group.get("suggestions", []):
                    lines.append(f"[{s.get('type')}] {s.get('name','')} (ID:{s.get('id','')}) {s.get('leagueName','')}")
            return "\n".join(lines[:8]) or "No results."

        elif name == "get_standings":
            data = api.league(args["league_id"])
            lines = []
            for group in data.get("table", []):
                for t in group.get("data", {}).get("table", {}).get("all", []):
                    lines.append(f"#{t.get('idx')} {t.get('name')} {t.get('pts')}pts P{t.get('played')} W{t.get('wins')} D{t.get('draws')} L{t.get('losses')} GD{t.get('goalConDiff')}")
            return "\n".join(lines) or "No standings."

        elif name == "get_team":
            data = api.team(args["team_id"])
            ov = data.get("overview", {})
            det = data.get("details", {})
            lines = [f"{det.get('name','')} ({det.get('country','')})"]
            form = ov.get("teamForm", [])
            if form:
                lines.append("Form: " + " ".join(f.get("resultString", "?") for f in form[:5]))
            for key, label in [("nextMatch", "Next"), ("lastMatch", "Last")]:
                m = ov.get(key)
                if m:
                    s = m.get("status", {})
                    live = "LIVE: " if s.get("started") and not s.get("finished") else ""
                    lines.append(f"{live}{label}: {m.get('home',{}).get('name','')} {s.get('scoreStr','vs')} {m.get('away',{}).get('name','')} ({s.get('utcTime','')[:10]})")
            return "\n".join(lines)

        elif name == "get_squad":
            data = api.team(args["team_id"])
            squad = data.get("squad", {})
            lines = []
            groups = squad if isinstance(squad, list) else squad.get("squad", squad.get("members", []))
            if not isinstance(groups, list):
                groups = [squad]
            for g in groups:
                if not isinstance(g, dict):
                    continue
                for p in g.get("members", []):
                    lines.append(f"#{p.get('shirtNumber','')} {p.get('name','')} age:{p.get('age','')} {g.get('title','')}")
            return "\n".join(lines) or "No squad data."

        elif name == "get_match_data":
            api._cache = {}
            data = api.team(args["team_id"])
            m = data.get("overview", {}).get("nextMatch") or data.get("overview", {}).get("lastMatch")
            if m and m.get("id") and m.get("pageUrl"):
                from browser import get_match_details
                from match_data import extract_full_match_data, summarize_full_match
                md = get_match_details(m["id"], match_url=m["pageUrl"])
                if md and "content" in md:
                    return summarize_full_match(extract_full_match_data(md))
            from ai_answer import summarize_data
            return summarize_data("team", {}, data)

        elif name == "get_tv_channels":
            from tv_channels import get_tv_channels as _gtv, format_tv_text
            r = _gtv(args.get("team_name", ""), args.get("opponent_name"))
            return format_tv_text(r) if r and r.get("channels") else "No TV data for this team."

        elif name == "get_odds":
            from odds import get_match_odds, format_odds_text
            return format_odds_text(get_match_odds(args.get("home_team", ""), args.get("away_team")))

        elif name == "get_player":
            from browser import get_player_data
            from ai_answer import summarize_data
            d = get_player_data(args["player_id"])
            return summarize_data("player", {}, d) if d else "Could not load player."

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Error: {str(e)[:150]}"


_client = None

def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=get_key("GROQ_API_KEY"))
    return _client


def run_agent(query, max_steps=4):
    """Run the AI agent loop. Returns final text or None."""
    client = _get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    for step in range(max_steps):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0,
                max_tokens=1000,
            )
        except Exception as e:
            logger.warning("Agent step %d failed: %s", step, e)
            return None

        msg = resp.choices[0].message

        if msg.tool_calls:
            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })
            for tc in msg.tool_calls:
                fn_args = json.loads(tc.function.arguments)
                logger.info("Agent[%d]: %s(%s)", step, tc.function.name, fn_args)
                result = _exec_tool(tc.function.name, fn_args)
                if len(result) > 3000:
                    result = result[:3000] + "\n...(truncated)"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        elif msg.content:
            return msg.content.strip()
        else:
            return None

    # Force final answer
    try:
        messages.append({"role": "user", "content": "Give your final answer now."})
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=messages, temperature=0, max_tokens=500)
        return resp.choices[0].message.content.strip()
    except Exception:
        return None
