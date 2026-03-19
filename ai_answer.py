"""AI-powered answer generation.

Two-pass approach:
1. Parse query → determine what data to fetch
2. Fetch data from FotMob → send data + query to LLM → get curated answer
"""

import json
import logging

from groq import Groq
from config import GROQ_API_KEY as GROQ_KEY

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_KEY)
    return _client


# --- Pass 1: Parse the query ---

PARSE_PROMPT = """You are a football data assistant query parser. Parse the user's query into a JSON action.

Available actions:
- standings: {league: "premier league"} — League table
- fixtures: {league: "ucl", round: 5} — Match schedule (round optional)
- team: {team: "Arsenal"} — Team info, form, overview
- team_fixtures: {team: "Arsenal", limit: 5} — Team's recent matches
- squad: {team: "Barcelona"} — Team roster
- last_match: {team: "PSG"} — Team's most recent result
- next_match: {team: "Real Madrid"} — Team's upcoming match
- top_scorers: {league: "pl", stat: "goals"} — League stat leaders
- player: {player: "Haaland"} — Player profile, stats, career, transfers
- transfers: {team: "Arsenal"} — Transfer news (team optional)
- news: {} — Football headlines
- search: {query: "something"} — Search anything
- live: {team: "Arsenal"} or {league: "pl"} — Live match tracking
- leagues: {} — List leagues
- help: {} — Help

Fix typos. Understand context:
- "haaland man city when?" → player (wants transfer date info)
- "2 days ago champions result" → fixtures for champions league (wants recent results)
- "who is top of la liga" → standings for la liga (wants #1 team)
- "did chelsea lose" → last_match for Chelsea
- "give me ars last 5 matches" → team_fixtures for Arsenal, limit 5

RESPOND WITH ONLY JSON:
{"action": "player", "params": {"player": "Haaland"}}"""


ANSWER_PROMPT = """You are a football data assistant. The user asked a question and we fetched data from FotMob.

Your job: Answer the user's SPECIFIC question using ONLY the data provided. Be concise and direct.

RULES:
- Answer the EXACT question asked. Don't dump all data.
- "haaland man city when?" → Find and state the transfer date, not all his stats.
- "who is top of la liga" → Name the #1 team and their points, not the full table.
- "2 days ago champions result" → Show only matches from that date, summarize scores.
- "did PSG lose?" → Say "Yes, PSG lost 0-3 to Chelsea" or "No, PSG won", not show all match data.
- "last 5 matches arsenal" → List the 5 matches with scores, brief.
- Keep answers to 1-5 lines. Be conversational but factual.
- Use the data provided — don't make up information.
- If the data doesn't contain the answer, say so.
- Format: Use plain text. For scores, use "Team 2-1 Team" format."""


def parse_query(query):
    """Pass 1: Parse user query into structured action."""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": PARSE_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        logger.debug("parse_query failed: %s", e)
        return None


def generate_answer(query, data_summary):
    """Pass 2: Generate a curated answer from data + query."""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "user", "content": f"User question: {query}\n\nData from FotMob:\n{data_summary}"},
            ],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.debug("generate_answer failed: %s", e)
        return None


def summarize_data(action, params, raw_data):
    """Convert raw FotMob data into a compact text summary for the LLM.

    We don't send the entire JSON — just the relevant parts, trimmed.
    """
    summary_parts = []

    if action == "standings":
        table_data = raw_data.get("table", [])
        for group in table_data:
            standings = group.get("data", {}).get("table", {}).get("all", [])
            league_name = group.get("data", {}).get("leagueName", "")
            summary_parts.append(f"League: {league_name}")
            for t in standings:  # Send full table so AI can answer bottom/mid/any position
                summary_parts.append(
                    f"  #{t.get('idx')} {t.get('name')} - {t.get('pts')} pts, "
                    f"P{t.get('played')} W{t.get('wins')} D{t.get('draws')} L{t.get('losses')} "
                    f"GD{t.get('goalConDiff')}"
                )

    elif action == "team":
        details = raw_data.get("details", {})
        overview = raw_data.get("overview", {})
        summary_parts.append(f"Team: {details.get('name', '')}, Country: {details.get('country', '')}")

        form = overview.get("teamForm", [])
        if form:
            form_str = " ".join(f.get("resultString", "?") for f in form[:10])
            summary_parts.append(f"Form: {form_str}")

        # Check for ongoing match
        has_ongoing = raw_data.get("fixtures", {}).get("hasOngoingMatch", False)

        nm = overview.get("nextMatch")
        if nm:
            h = nm.get("home", {}).get("name", "")
            a = nm.get("away", {}).get("name", "")
            status = nm.get("status", {})
            date = status.get("utcTime", "")
            tourn = nm.get("tournament", {}).get("name", "")
            score = status.get("scoreStr", "")
            started = status.get("started", False)
            finished = status.get("finished", False)

            if started and not finished:
                summary_parts.append(f"LIVE MATCH NOW: {h} {score} {a}, {tourn} (match is currently being played)")
            elif finished:
                summary_parts.append(f"Latest result: {h} {score} {a}, {date}, {tourn}")
            else:
                summary_parts.append(f"Next match: {h} vs {a}, {date}, {tourn}")

        lm = overview.get("lastMatch")
        if lm:
            h = lm.get("home", {}).get("name", "")
            a = lm.get("away", {}).get("name", "")
            score = lm.get("status", {}).get("scoreStr", "")
            date = lm.get("status", {}).get("utcTime", "")
            summary_parts.append(f"Last match: {h} {score} {a}, {date}")

        # Upcoming fixtures (more than just next match)
        all_fix = raw_data.get("fixtures", {}).get("allFixtures", {}).get("fixtures", [])
        upcoming = [m for m in all_fix if m.get("notStarted")]
        if upcoming:
            summary_parts.append("Upcoming fixtures:")
            for m in upcoming[:8]:
                h = m.get("home", {}).get("name", "")
                a = m.get("away", {}).get("name", "")
                date = m.get("status", {}).get("utcTime", "")
                tourn = m.get("tournament", {}).get("name", "") if "tournament" in m else ""
                summary_parts.append(f"  {h} vs {a}, {date}" + (f", {tourn}" if tourn else ""))

    elif action == "player":
        summary_parts.append(f"Name: {raw_data.get('name', '')}")
        summary_parts.append(f"Position: {raw_data.get('positionDescription', {}).get('primaryPosition', {}).get('label', '')}")
        team = raw_data.get("primaryTeam", {})
        summary_parts.append(f"Current team: {team.get('teamName', '')}")

        birth = raw_data.get("birthDate", {})
        if isinstance(birth, dict):
            summary_parts.append(f"Born: {birth.get('utcTime', '')}")

        # Career/transfer history
        career = raw_data.get("careerHistory", {})
        if isinstance(career, dict):
            entries = career.get("careerItems", {}).get("senior", {}).get("teamEntries", [])
            if entries:
                summary_parts.append("Career history:")
                for entry in entries:
                    team_name = entry.get("teamName", "")
                    start = entry.get("startDate", "")
                    end = entry.get("endDate", "ongoing")
                    summary_parts.append(f"  {team_name}: {start} to {end}")

        # Stats
        main = raw_data.get("mainLeague", {})
        stats = main.get("stats", [])
        if stats:
            summary_parts.append(f"Season stats ({main.get('leagueName', '')}):")
            for s in stats:
                summary_parts.append(f"  {s.get('title', '')}: {s.get('value', '')}")

        # Recent matches
        recent = raw_data.get("recentMatches", [])
        if recent:
            summary_parts.append("Recent matches:")
            for m in recent[:5]:
                opp = m.get("opponentTeamName", "")
                h = m.get("homeScore", "")
                a = m.get("awayScore", "")
                g = m.get("goals", 0)
                ass = m.get("assists", 0)
                date = m.get("matchDate", {}).get("utcTime", "")
                summary_parts.append(f"  vs {opp}: {h}-{a}, goals:{g} assists:{ass}, {date}")

    elif action == "team_fixtures":
        fixtures = raw_data.get("fixtures", {}).get("allFixtures", {}).get("fixtures", [])
        finished = [m for m in fixtures if m.get("status", {}).get("finished")]
        upcoming = [m for m in fixtures if m.get("notStarted")]

        limit = params.get("limit", 10)
        recent = finished[-limit:] if finished else []
        summary_parts.append(f"Last {len(recent)} matches:")
        for m in recent:
            h = m.get("home", {}).get("name", "")
            a = m.get("away", {}).get("name", "")
            score = m.get("status", {}).get("scoreStr", "")
            date = m.get("status", {}).get("utcTime", "")
            summary_parts.append(f"  {h} {score} {a}, {date}")

        if upcoming[:3]:
            summary_parts.append("Upcoming:")
            for m in upcoming[:3]:
                h = m.get("home", {}).get("name", "")
                a = m.get("away", {}).get("name", "")
                date = m.get("status", {}).get("utcTime", "")
                summary_parts.append(f"  {h} vs {a}, {date}")

    elif action == "last_match":
        overview = raw_data.get("overview", {})
        lm = overview.get("lastMatch", {})
        h = lm.get("home", {}).get("name", "")
        a = lm.get("away", {}).get("name", "")
        score = lm.get("status", {}).get("scoreStr", "")
        date = lm.get("status", {}).get("utcTime", "")
        tourn = lm.get("tournament", {}).get("name", "")
        result = lm.get("result")
        result_map = {1: "won", 2: "lost", 3: "drew"}
        summary_parts.append(f"Last match: {h} {score} {a}")
        summary_parts.append(f"Date: {date}, Competition: {tourn}")
        summary_parts.append(f"Result for queried team: {result_map.get(result, 'unknown')}")

    elif action == "next_match":
        overview = raw_data.get("overview", {})
        nm = overview.get("nextMatch", {})
        h = nm.get("home", {}).get("name", "")
        a = nm.get("away", {}).get("name", "")
        date = nm.get("status", {}).get("utcTime", "")
        tourn = nm.get("tournament", {}).get("name", "")
        summary_parts.append(f"Next match: {h} vs {a}, {date}, {tourn}")

    elif action == "fixtures":
        fixtures = raw_data.get("fixtures", {})
        all_matches = fixtures.get("allMatches", [])
        # Get recent finished + upcoming
        finished = [m for m in all_matches if m.get("status", {}).get("finished")]
        upcoming = [m for m in all_matches if not m.get("status", {}).get("finished") and not m.get("status", {}).get("started")]

        if finished:
            summary_parts.append("Recent results:")
            for m in finished[-10:]:
                h = m.get("home", {}).get("name", "")
                a = m.get("away", {}).get("name", "")
                score = m.get("status", {}).get("scoreStr", "")
                date = m.get("status", {}).get("utcTime", "")
                summary_parts.append(f"  {h} {score} {a}, {date}")

        if upcoming:
            summary_parts.append("Upcoming:")
            for m in upcoming[:5]:
                h = m.get("home", {}).get("name", "")
                a = m.get("away", {}).get("name", "")
                date = m.get("status", {}).get("utcTime", "")
                summary_parts.append(f"  {h} vs {a}, {date}")

    elif action == "top_scorers":
        # Data is already the stat list
        if isinstance(raw_data, list):
            for p in raw_data[:5]:
                name = p.get("ParticipantName", p.get("name", ""))
                team = p.get("TeamName", p.get("teamName", ""))
                val = p.get("StatValue", p.get("value", ""))
                summary_parts.append(f"  #{p.get('Rank', '')} {name} ({team}): {val}")

    elif action == "squad":
        squad = raw_data.get("squad", {})
        if isinstance(squad, list):
            groups = squad
        elif isinstance(squad, dict):
            groups = squad.get("squad", squad.get("members", []))
            if not isinstance(groups, list):
                groups = [squad]
        else:
            groups = []

        for group in groups:
            if isinstance(group, dict):
                title = group.get("title", "")
                members = group.get("members", [])
                if members:
                    names = [f"{m.get('name', '')} (#{m.get('shirtNumber', '')})" for m in members]
                    summary_parts.append(f"{title}: {', '.join(names)}")

    elif action in ("transfers", "news"):
        # These are already display-ready, just pass through
        summary_parts.append(json.dumps(raw_data, indent=2)[:2000])

    return "\n".join(summary_parts) if summary_parts else json.dumps(raw_data, indent=2)[:2000]
