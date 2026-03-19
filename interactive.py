"""Interactive mode - REPL loop powered by NLP intent detection."""

import logging
import re
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)

from api import FotMobAPI
from nlp import (
    detect_intent,
    extract_league,
    extract_entity,
    extract_round_number,
    fuzzy_match_league,
    NOISE_WORDS, RESULT_NOISE, SQUAD_NOISE, FORM_NOISE, NEXT_NOISE,
    LEAGUE_DICT,
)
from display import (
    show_search_results,
    show_standings,
    show_matches,
    show_team_overview,
    show_team_squad,
    show_transfers,
    show_news,
    show_league_fixtures,
    show_match_details,
    show_player_stats,
    format_utc_time,
    console,
)

api = FotMobAPI()


# =============================================================================
# ENTITY RESOLUTION (search FotMob for teams/players)
# =============================================================================

def _resolve_league_from_params(params):
    """Resolve a league from LLM params to a league ID."""
    league = params.get("league", "")
    if not league:
        return None
    # Try exact match in our dict
    lid, _, _ = extract_league(league)
    if lid:
        return lid
    # Try fuzzy
    return fuzzy_match_league(league)


def _resolve_team(name):
    """Search for a team → (id, name) or (None, None)."""
    if not name:
        return None, None
    results = api.search(name)
    for group in results:
        for s in group.get("suggestions", []):
            if s.get("type") == "team":
                return s.get("id"), s.get("name", name)
    return None, None


def _resolve_player(name):
    """Search for a player → (id, name) or (None, None)."""
    if not name:
        return None, None
    results = api.search(name)
    for group in results:
        for s in group.get("suggestions", []):
            if s.get("type") == "player":
                return s.get("id"), s.get("name", name)
    return None, None


# =============================================================================
# ACTION HANDLERS
# =============================================================================

def _do_standings(query):
    league_id, _, remaining = extract_league(query)
    if not league_id:
        entity = extract_entity(query, NOISE_WORDS)
        league_id = fuzzy_match_league(entity)
    if league_id:
        data = api.league(league_id)
        show_standings(data)
    else:
        console.print("[yellow]Which league? Try: standings pl, la liga table, etc.[/yellow]")


def _do_fixtures(query):
    league_id, _, remaining = extract_league(query)
    if not league_id:
        entity = extract_entity(query, NOISE_WORDS)
        league_id = fuzzy_match_league(entity)
    if league_id:
        data = api.league(league_id)
        round_num = extract_round_number(query)
        show_league_fixtures(data, round_num=round_num)
    else:
        console.print("[yellow]Which league? Try: fixtures pl, ucl schedule, etc.[/yellow]")


def _do_team(query):
    entity = extract_entity(query, NOISE_WORDS)
    team_id, team_name = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        show_team_overview(data)
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_form(query):
    entity = extract_entity(query, NOISE_WORDS | FORM_NOISE)
    team_id, team_name = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        show_team_overview(data)
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_squad(query):
    entity = extract_entity(query, NOISE_WORDS | SQUAD_NOISE)
    team_id, team_name = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        console.print(f"\n[bold cyan]{team_name}[/bold cyan] Squad\n")
        show_team_squad(data)
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_team_fixtures(query):
    # Extract a number for limit (e.g. "last 5 matches")
    limit_match = re.search(r'(\d+)', query)
    limit = int(limit_match.group(1)) if limit_match else 10

    # Strip intent words, noise, and numbers to find team name
    team_noise = NOISE_WORDS | {
        "last", "recent", "past", "all", "matches", "games", "results",
        "match", "game", "history", "played", "give", "show",
    }
    # Remove numbers from query before extracting entity
    cleaned = re.sub(r'\b\d+\b', '', query)
    entity = extract_entity(cleaned, team_noise)
    team_id, team_name = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        fixtures = data.get("fixtures", {}).get("allFixtures", {})
        all_matches = fixtures.get("fixtures", [])

        if not all_matches:
            console.print("[yellow]No fixtures found.[/yellow]")
            return

        # Find recent finished matches + upcoming
        finished = [m for m in all_matches if m.get("status", {}).get("finished")]
        upcoming = [m for m in all_matches if m.get("notStarted")]

        # Show last N finished + next few upcoming
        recent = finished[-limit:] if finished else []
        display = recent + upcoming[:3]

        show_matches(display, title=f"{team_name} - Last {len(recent)} matches")
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_live(query):
    from live import track_team_live, track_league_live

    # Extract interval if specified (e.g. "live arsenal 30s")
    interval_match = re.search(r'(\d+)\s*s(?:ec)?', query.lower())
    interval = int(interval_match.group(1)) if interval_match else 60

    # Try to find a league first
    league_id, _, remaining = extract_league(query)
    if league_id:
        track_league_live(query, interval=interval)
        return

    # Try to find a team
    live_noise = NOISE_WORDS | {
        "live", "track", "follow", "watch", "score", "scores",
        "update", "updates", "happening", "what", "is", "current",
        "commentary", "match",
    }
    entity = extract_entity(query, live_noise)
    # Remove numbers (interval) from entity
    entity = re.sub(r'\b\d+\b', '', entity).strip()

    if entity:
        team_id, team_name = _resolve_team(entity)
        if team_id:
            track_team_live(entity, interval=interval)
            return

        # Maybe it's a league name not in our dict
        league_id = fuzzy_match_league(entity)
        if league_id:
            track_league_live(entity, interval=interval)
            return

    # No specific team/league — check popular leagues for any live matches
    q_lower = query.lower()
    generic_live = any(w in q_lower for w in ["any", "now", "happening", "ongoing", "current", "live match"])
    if generic_live or not entity:
        console.print("[dim]Checking leagues for live matches...[/dim]")
        from display import format_utc_time
        found_live = False
        # Scan 20+ leagues to catch most live matches globally
        for lid in [47, 87, 54, 55, 53, 42, 73, 71, 10562, 130, 61, 62, 57,
                     132, 133, 68, 10419, 9227, 8442, 325, 8044]:
            try:
                data = api.league(lid)
                details = data.get("details", {})
                league_name = details.get("name", "")
                matches = data.get("fixtures", {}).get("allMatches", [])
                live_now = [m for m in matches if m.get("status", {}).get("started") and not m.get("status", {}).get("finished")]
                if live_now:
                    found_live = True
                    for m in live_now:
                        h = m.get("home", {}).get("name", "")
                        a = m.get("away", {}).get("name", "")
                        score = m.get("status", {}).get("scoreStr", "")
                        console.print(f"  [green]LIVE[/green] [bold]{h}[/bold] {score} [bold]{a}[/bold]  [dim]{league_name}[/dim]")
            except Exception:
                continue
        if not found_live:
            console.print("[yellow]No live matches in major leagues right now.[/yellow]")
        console.print()
        return

    console.print("[yellow]Track what? Try: live arsenal, live pl, what is happening in arsenal vs city[/yellow]")


def _do_last_match(query):
    entity = extract_entity(query, NOISE_WORDS | RESULT_NOISE)
    team_id, resolved = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        lm = data.get("overview", {}).get("lastMatch")
        if lm:
            home = lm.get("home", {})
            away = lm.get("away", {})
            score = lm.get("status", {}).get("scoreStr", "")
            date = format_utc_time(lm.get("status", {}).get("utcTime", ""))
            tourn = lm.get("tournament", {}).get("name", "")

            result_code = lm.get("result")
            result_map = {1: "[green]WON[/green]", 2: "[red]LOST[/red]", 3: "[yellow]DREW[/yellow]"}
            result_text = result_map.get(result_code, "")

            console.print(f"\n  [bold]{resolved}[/bold] {result_text}")
            console.print(f"  [bold]{home.get('name', '')}[/bold] {score} [bold]{away.get('name', '')}[/bold]")
            console.print(f"  [dim]{date}  {tourn}[/dim]\n")
        else:
            console.print("[yellow]No recent match data.[/yellow]")
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_next_match(query):
    entity = extract_entity(query, NOISE_WORDS | NEXT_NOISE)
    team_id, resolved = _resolve_team(entity)
    if team_id:
        data = api.team(team_id)
        nm = data.get("overview", {}).get("nextMatch")
        if nm:
            home = nm.get("home", {})
            away = nm.get("away", {})
            date = format_utc_time(nm.get("status", {}).get("utcTime", ""))
            tourn = nm.get("tournament", {}).get("name", "")
            console.print(
                f"\n  [bold]{home.get('name', '')}[/bold] vs [bold]{away.get('name', '')}[/bold]"
                f"\n  [dim]{date}  {tourn}[/dim]\n"
            )
        else:
            console.print("[yellow]No upcoming match found.[/yellow]")
    else:
        console.print(f"[yellow]Could not find team: {entity}[/yellow]")


def _do_top_scorers(query):
    league_id, _, remaining = extract_league(query)
    if not league_id:
        league_id = 47  # Default PL

    data = api.league(league_id)
    stats = data.get("stats", {})
    players = stats.get("players", [])
    if not players:
        console.print("[yellow]No stats available.[/yellow]")
        return

    # Detect stat type from query
    q = query.lower()
    stat_type = "goals"
    if "assist" in q:
        stat_type = "assists"
    elif "rating" in q:
        stat_type = "rating"
    elif "clean sheet" in q:
        stat_type = "clean"
    elif "yellow" in q or "red" in q or "card" in q:
        stat_type = "card"

    target = None
    for p in players:
        header = p.get("header", "").lower()
        if header == stat_type or header.startswith(stat_type):
            target = p
            break
    if not target:
        for p in players:
            if stat_type in p.get("header", "").lower():
                target = p
                break
    if not target:
        target = players[0]

    fetch_url = target.get("fetchAllUrl", "")
    if fetch_url:
        full_data = api.league_stats(fetch_url)
        top_lists = full_data.get("TopLists", [])
        stat_list = top_lists[0].get("StatList", []) if top_lists else []
    else:
        stat_list = target.get("topThree", [])

    if not stat_list:
        console.print("[yellow]No data available.[/yellow]")
        return

    table = Table(title=f"  {target.get('header', 'Top Players')}", show_header=True, title_style="bold cyan")
    table.add_column("#", width=4, justify="right")
    table.add_column("Player", width=24)
    table.add_column("Team", width=18, style="dim")
    table.add_column("Value", width=6, justify="center", style="bold")

    for player in stat_list[:20]:
        name = player.get("ParticipantName", player.get("name", ""))
        team = player.get("TeamName", player.get("teamName", ""))
        val = player.get("StatValue", player.get("value", ""))
        val_str = str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
        rank = str(player.get("Rank", ""))
        table.add_row(rank, name, team, val_str)

    console.print(table)
    console.print()


def _do_player(query):
    entity = extract_entity(query, NOISE_WORDS | {"stats", "statistics", "stat", "profile", "player", "info"})
    pid, pname = _resolve_player(entity)
    if pid:
        console.print(f"[dim]Loading {pname} stats (browser)...[/dim]")
        from browser import get_player_data
        data = get_player_data(pid)
        if data:
            show_player_stats(data)
        else:
            console.print("[red]Could not load player data.[/red]")
    else:
        console.print(f"[yellow]Could not find player: {entity}[/yellow]")


def _do_transfers(query):
    # Check if a team is mentioned
    entity = extract_entity(query, NOISE_WORDS | {"transfer", "transfers", "signing", "signings", "deals", "latest", "recent", "new", "market", "window"})
    if entity:
        team_id, team_name = _resolve_team(entity)
        if team_id:
            data = api.team(team_id)
            transfers = data.get("transfers", {})
            console.print(f"\n[bold cyan]{team_name}[/bold cyan] Transfers\n")
            for section_key in ["transfersIn", "transfersOut"]:
                section = transfers.get(section_key, [])
                if section:
                    label = "Transfers In" if "In" in section_key else "Transfers Out"
                    table = Table(title=f"  {label}", show_header=True, title_style="bold cyan")
                    table.add_column("Player", width=22)
                    table.add_column("From/To", width=20)
                    table.add_column("Fee", width=14)
                    for t in section[:10]:
                        pname = t.get("name", "")
                        other = t.get("fromClub", t.get("toClub", ""))
                        fee = t.get("fee", {})
                        fee_str = fee.get("feeText", "") if isinstance(fee, dict) else str(fee)
                        table.add_row(pname, other, fee_str)
                    console.print(table)
                    console.print()
            return

    # Global transfers
    data = api.transfers()
    show_transfers(data)


def _do_news(query):
    data = api.world_news()
    show_news(data)


def _do_search(query):
    entity = extract_entity(query, NOISE_WORDS | {"search", "find", "look", "up", "lookup"})
    if entity:
        results = api.search(entity)
        show_search_results(results)
    else:
        console.print("[yellow]Search for what? Try: search Arsenal[/yellow]")


def _do_leagues(query):
    data = api.all_leagues()
    popular = data.get("popular", [])
    if popular:
        table = Table(title="  Popular Leagues", show_header=True, title_style="bold cyan")
        table.add_column("ID", width=8, style="dim")
        table.add_column("League", width=30)
        for league in popular:
            table.add_row(str(league.get("id", "")), league.get("name", ""))
        console.print(table)
        console.print()


def _do_help(query):
    console.print(Panel(
        "[bold]Type natural queries like:[/bold]\n\n"
        "  [cyan]arsenal[/cyan]                       Team overview & form\n"
        "  [cyan]premier league[/cyan]                League standings\n"
        "  [cyan]standings la liga[/cyan]              League table\n"
        "  [cyan]fixtures pl[/cyan]                    Current gameweek\n"
        "  [cyan]fixtures ucl round 3[/cyan]           Specific round\n"
        "  [cyan]arsenal form[/cyan]                   Recent form\n"
        "  [cyan]players of barcelona[/cyan]           Squad roster\n"
        "  [cyan]did psg lose their last match[/cyan]  Last result\n"
        "  [cyan]next match real madrid[/cyan]         Upcoming fixture\n"
        "  [cyan]top scorers pl[/cyan]                 Goal rankings\n"
        "  [cyan]top assists bundesliga[/cyan]         Assist rankings\n"
        "  [cyan]haaland stats[/cyan]                  Player profile (browser)\n"
        "  [cyan]live arsenal[/cyan]                   Track live score (polls every 60s)\n"
        "  [cyan]live pl[/cyan]                        Track league live scores\n"
        "  [cyan]what is happening in arsenal[/cyan]   Same as live\n"
        "  [cyan]transfers[/cyan]                      Latest transfers\n"
        "  [cyan]arsenal transfers[/cyan]              Team transfers\n"
        "  [cyan]news[/cyan]                           Football headlines\n"
        "  [cyan]search messi[/cyan]                   Search anything\n"
        "  [cyan]leagues[/cyan]                        List all leagues\n\n"
        "[dim]Handles typos too: 'arsnal', 'premire league', etc.\n"
        "Type 'quit' or 'exit' to leave.[/dim]",
        title="FotMob CLI - Help",
        border_style="cyan",
    ))


# =============================================================================
# INTENT → ACTION DISPATCH
# =============================================================================

ACTION_MAP = {
    "standings": _do_standings,
    "fixtures": _do_fixtures,
    "team_fixtures": _do_team_fixtures,
    "live": _do_live,
    "team": _do_team,
    "form": _do_form,
    "squad": _do_squad,
    "last_match": _do_last_match,
    "next_match": _do_next_match,
    "top_scorers": _do_top_scorers,
    "player": _do_player,
    "transfers": _do_transfers,
    "news": _do_news,
    "search": _do_search,
    "leagues": _do_leagues,
    "help": _do_help,
}


# =============================================================================
# MAIN QUERY HANDLER
# =============================================================================

def _execute_llm_result(result):
    """Execute a parsed LLM result (dict with action + params)."""
    action = result.get("action", "")
    params = result.get("params", {})

    if action not in ACTION_MAP:
        return False

    # Build a synthetic query from the LLM's parsed params so our handlers work
    # Each handler expects a query string, so we reconstruct one from params
    if action == "standings":
        query = f"standings {params.get('league', 'pl')}"
    elif action == "fixtures":
        r = f" round {params['round']}" if params.get("round") else ""
        query = f"fixtures {params.get('league', 'pl')}{r}"
    elif action == "team_fixtures":
        limit = params.get("limit", 10)
        query = f"last {limit} matches {params.get('team', '')}"
    elif action == "live":
        query = f"live {params.get('team', params.get('league', ''))}"
    elif action == "team":
        query = params.get("team", "")
    elif action == "form":
        query = f"{params.get('team', '')} form"
    elif action == "squad":
        query = f"players of {params.get('team', '')}"
    elif action == "last_match":
        query = f"did {params.get('team', '')} lose last match"
    elif action == "next_match":
        query = f"next match {params.get('team', '')}"
    elif action == "top_scorers":
        stat = params.get("stat", "goals")
        query = f"top {stat} {params.get('league', 'pl')}"
    elif action == "player":
        query = f"{params.get('player', '')} stats"
    elif action == "transfers":
        team = params.get("team", "")
        query = f"{team} transfers" if team else "transfers"
    elif action == "news":
        query = "news"
    elif action == "search":
        query = f"search {params.get('query', '')}"
    elif action == "leagues":
        query = "leagues"
    elif action == "help":
        query = "help"
    else:
        return False

    ACTION_MAP[action](query)
    return True


def _keyword_fallback(query):
    """Keyword-based NLP fallback when LLM is unavailable."""
    # Step 1: Check if it's a bare league name → standings
    league_id, league_name, remaining = extract_league(query)
    if league_id and not remaining.strip():
        data = api.league(league_id)
        show_standings(data)
        return True

    # Step 2: Detect intent via keyword NLP
    intent, confidence, matched = detect_intent(query)

    # Context fix: "fixtures" + team but no league → team_fixtures
    if intent == "fixtures" and not league_id:
        fixture_noise = NOISE_WORDS | {"fixtures", "fixture", "schedule", "matches", "games", "results", "scores"}
        entity = extract_entity(query, fixture_noise)
        if entity:
            tid, _ = _resolve_team(entity)
            if tid:
                intent = "team_fixtures"

    if intent and intent in ACTION_MAP:
        ACTION_MAP[intent](query)
        return True

    # Step 3: League with extra words → standings
    if league_id:
        data = api.league(league_id)
        show_standings(data)
        return True

    # Step 4: Try as team name
    team_id, team_name = _resolve_team(query)
    if team_id:
        data = api.team(team_id)
        show_team_overview(data)
        return True

    # Step 5: Try as player name
    player_id, player_name = _resolve_player(query)
    if player_id:
        console.print(f"[dim]Loading {player_name} stats (browser)...[/dim]")
        from browser import get_player_data
        data = get_player_data(player_id)
        if data:
            show_player_stats(data)
            return True

    return False


def parse_and_execute(query):
    """Parse a natural language query and execute the appropriate action.

    Strategy:
    1. Try LLM (Gemini) for understanding complex/ambiguous queries
    2. Fall back to keyword NLP if LLM is unavailable (quota exhausted, etc.)
    """
    query = query.strip()
    if not query:
        return

    # === PRIORITY: "X vs Y" queries → always resolve as match lookup ===
    vs_match = re.search(r'(.+?)\s+vs\.?\s+(.+)', query, re.IGNORECASE)
    if vs_match:
        team_a = vs_match.group(1).strip()
        team_b_raw = vs_match.group(2).strip()
        # Clean team_a — remove leading noise phrases
        for prefix in ["what is happening in", "whats happening in", "what's happening in",
                        "commentary for", "updates for", "latest on", "show me",
                        "give me", "tell me about", "how is", "what about"]:
            if team_a.lower().startswith(prefix):
                team_a = team_a[len(prefix):].strip()
                break
        # Strip trailing intent words from team_b
        team_b = team_b_raw
        for suffix in ["who scored", "who score", "scores", "score", "result",
                        "what is happening", "live", "match", "game", "update",
                        "lineup", "lineups", "stats", "xg", "goals", "scored",
                        "cards", "events", "details", "summary", "preview",
                        "injuries", "injured", "referee", "weather", "coach",
                        "head to head", "h2h", "insights", "prediction",
                        "commentary", "updates", "latest", "what's happening",
                        "whats happening", "going on"]:
            if team_b.lower().endswith(suffix):
                team_b = team_b[:-(len(suffix))].strip()
                break

        # Check if user wants live commentary
        commentary_words = {"commentary", "updates", "latest", "happening", "going on",
                            "whats happening", "what's happening", "live updates",
                            "what is happening", "summarize", "summary of the match"}
        wants_commentary = any(w in query.lower() for w in commentary_words)

        tid, tname = _resolve_team(team_a)
        if tid:
            from ai_answer import generate_answer
            from match_data import extract_full_match_data, summarize_full_match

            # Get team data to find match URL
            api._cache = {}
            raw = api.team(tid)
            overview = raw.get("overview", {})

            # If user wants commentary, fetch it directly
            if wants_commentary:
                for match_key in ("nextMatch", "lastMatch"):
                    m = overview.get(match_key, {})
                    if m and m.get("status", {}).get("started"):
                        mid = m.get("id")
                        purl = m.get("pageUrl")
                        if mid and purl:
                            console.print("[dim]Loading live commentary...[/dim]")
                            from browser import get_match_commentary
                            entries = get_match_commentary(mid, match_url=purl, limit=15)
                            if entries:
                                commentary_text = "\n".join(
                                    [f"{e['minute']}': {e['text']}" for e in entries]
                                )
                                h = m.get("home", {}).get("name", "")
                                a = m.get("away", {}).get("name", "")
                                score = m.get("status", {}).get("scoreStr", "")
                                header = f"LIVE: {h} {score} {a}\n\nCommentary (latest):\n{commentary_text}"
                                answer = generate_answer(query, header)
                                if answer:
                                    console.print(f"\n{answer}\n")
                                    return
                                # Fallback: print raw
                                console.print(f"\n[bold]{h} {score} {a}[/bold] (LIVE)\n")
                                for e in entries:
                                    console.print(f"  [dim]{e['minute']}'[/dim] {e['text']}")
                                console.print()
                                return
                            break
                console.print("[yellow]No live commentary available for this match.[/yellow]")
                return

            # Find the match page URL
            match_loaded = False
            for match_key in ("nextMatch", "lastMatch"):
                m = overview.get(match_key, {})
                if m:
                    match_id = m.get("id")
                    page_url = m.get("pageUrl")
                    if match_id and page_url:
                        console.print(f"[dim]Loading full match data...[/dim]")
                        from browser import get_match_details
                        page_props = get_match_details(match_id, match_url=page_url)
                        if page_props and "content" in page_props:
                            full_data = extract_full_match_data(page_props)
                            summary = summarize_full_match(full_data)
                            answer = generate_answer(query, summary)
                            if answer:
                                console.print(f"\n{answer}\n")
                                return
                            console.print(summary)
                            return
                        break

            # Fallback: use team API data
            from ai_answer import summarize_data
            summary = summarize_data("team", {}, raw)
            summary += f"\nUser is asking about a match against: {team_b}"
            answer = generate_answer(query, summary)
            if answer:
                console.print(f"\n{answer}\n")
                return
            show_team_overview(raw)
            return
        else:
            console.print(f"[yellow]Could not find team: {team_a}[/yellow]")
            return

    # === AI TWO-PASS: Parse → Fetch → Curate answer ===
    from ai_answer import parse_query, generate_answer, summarize_data

    parsed = parse_query(query)
    if parsed and isinstance(parsed, dict) and "action" in parsed:
        action = parsed["action"]
        params = parsed.get("params", {})

        # Actions that need raw display (help, leagues) — skip AI curation
        if action in ("help", "leagues"):
            if action in ACTION_MAP:
                ACTION_MAP[action](query)
                return

        # Commentary — fetch live commentary for a team's ongoing match
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
                                console.print("[dim]Loading live commentary...[/dim]")
                                from browser import get_match_commentary
                                entries = get_match_commentary(mid, match_url=purl, limit=15)
                                if entries:
                                    commentary_text = "\n".join([f"{e['minute']}': {e['text']}" for e in entries])
                                    h = m.get("home", {}).get("name", "")
                                    a = m.get("away", {}).get("name", "")
                                    score = m.get("status", {}).get("scoreStr", "")
                                    header = f"LIVE: {h} {score} {a}\n\nCommentary:\n{commentary_text}"
                                    answer = generate_answer(query, header)
                                    if answer:
                                        console.print(f"\n{answer}\n")
                                    else:
                                        console.print(f"\n[bold]{h} {score} {a}[/bold]\n")
                                        for e in entries:
                                            console.print(f"  [dim]{e['minute']}'[/dim] {e['text']}")
                                        console.print()
                                    return
                            break
                    console.print(f"[yellow]No live match found for {tname}. Commentary is only available during live matches.[/yellow]")
                    return
            console.print("[yellow]Which team? Try: commentary arsenal, or vitoria vs gremio commentary[/yellow]")
            return

        # Live tracking — handle "X vs Y" match format
        if action == "live":
            match_str = params.get("match", "")
            team_str = params.get("team", params.get("league", ""))

            # If "X vs Y" format, extract first team
            if match_str and "vs" in match_str.lower():
                team_str = match_str.split("vs")[0].strip()
            elif match_str:
                team_str = match_str

            if team_str:
                # If it's a "vs" or "what is happening" query, do one-time check
                q_lower = query.lower()
                is_vs_query = "vs" in q_lower or "happening" in q_lower or "current score" in q_lower

                tid, tname = _resolve_team(team_str)
                if tid:
                    if is_vs_query:
                        # One-time: fetch team data and let AI answer
                        raw = api.team(tid)
                        summary = summarize_data("team", params, raw)
                        answer = generate_answer(query, summary)
                        if answer:
                            console.print(f"\n{answer}\n")
                            return
                        # Fallback
                        show_team_overview(raw)
                        return
                    else:
                        # Continuous tracking: "live arsenal"
                        from live import track_team_live
                        track_team_live(team_str, interval=60)
                        return

                # Try as league
                lid = _resolve_league_from_params({"league": team_str})
                if lid:
                    from live import track_league_live
                    track_league_live(team_str, interval=60)
                    return
                # Team/league not found — search and give AI answer instead
                results = api.search(match_str or team_str)
                for group in results:
                    for s in group.get("suggestions", []):
                        if s.get("type") == "match":
                            # Found a match — show its info
                            status = s.get("status", {})
                            home = s.get("homeTeamName", "")
                            away = s.get("awayTeamName", "")
                            score = status.get("scoreStr", "vs")
                            league = s.get("leagueName", "")
                            if status.get("started") and not status.get("finished"):
                                console.print(f"\n  [green]LIVE[/green] [bold]{home}[/bold] {score} [bold]{away}[/bold]  [dim]{league}[/dim]\n")
                            elif status.get("finished"):
                                console.print(f"\n  [bold]{home}[/bold] {score} [bold]{away}[/bold]  [dim]FT - {league}[/dim]\n")
                            else:
                                from display import format_utc_time
                                date = format_utc_time(status.get("utcTime", ""))
                                console.print(f"\n  [bold]{home}[/bold] vs [bold]{away}[/bold]  [dim]{date} - {league}[/dim]\n")
                            return
                console.print(f"[yellow]Could not find match or team: {match_str or team_str}[/yellow]")
                return

            ACTION_MAP["live"](query)
            return

        # Actions that need browser (player, match) — fetch via browser, then curate
        if action == "player":
            player_name = params.get("player", "")
            pid, pname = _resolve_player(player_name)
            if pid:
                console.print(f"[dim]Loading {pname} data...[/dim]")
                from browser import get_player_data
                raw = get_player_data(pid)
                if raw:
                    summary = summarize_data("player", params, raw)
                    answer = generate_answer(query, summary)
                    if answer:
                        console.print(f"\n{answer}\n")
                        return
                    # Fallback: show raw display
                    show_player_stats(raw)
                    return

        # Standings: if user wants "full table" or bare league name, show raw table
        if action == "standings":
            q_lower = query.lower()
            wants_full = any(w in q_lower for w in ["full", "table", "standings", "all teams", "complete"])
            league_id = _resolve_league_from_params(params)
            if league_id:
                raw = api.league(league_id)
                if raw and wants_full:
                    show_standings(raw)
                    return
                # Otherwise fall through to AI summary

        # Actions that use API — fetch, summarize, curate
        raw = None
        try:
            if action == "standings":
                league_id = _resolve_league_from_params(params)
                if league_id:
                    raw = api.league(league_id)
            elif action == "fixtures":
                league_id = _resolve_league_from_params(params)
                if league_id:
                    raw = api.league(league_id)
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
                league_id = _resolve_league_from_params(params)
                if league_id:
                    league_data = api.league(league_id)
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
                team_name = params.get("team", "")
                if team_name:
                    tid, _ = _resolve_team(team_name)
                    if tid:
                        raw = api.team(tid)
                        action = "team"  # reuse team summary
                else:
                    raw = api.transfers()
            elif action == "news":
                raw = api.world_news()
            elif action == "search":
                results = api.search(params.get("query", query))
                show_search_results(results)
                return
        except Exception as e:
            logger.debug("Data fetch failed for action '%s': %s", action, e)
            raw = None

        if raw is not None:
            summary = summarize_data(action, params, raw)
            answer = generate_answer(query, summary)
            if answer:
                console.print(f"\n{answer}\n")
                return
            # Fallback: execute raw display
            try:
                _execute_llm_result(parsed)
                return
            except Exception as e:
                logger.debug("Fallback display failed: %s", e)

    # === KEYWORD NLP FALLBACK ===
    if _keyword_fallback(query):
        return

    # === NOTHING MATCHED ===
    console.print(f"[yellow]Couldn't understand: '{query}'[/yellow]")
    console.print("[dim]Try a team name, league, or type 'help' for examples.[/dim]")


# =============================================================================
# REPL LOOP
# =============================================================================

def run_interactive():
    """Run the interactive REPL loop."""
    # Test LLM availability on startup
    from llm_parser import get_status_text
    llm_status = get_status_text()

    console.print(Panel(
        f"[bold]FotMob CLI[/bold] - Football data in your terminal\n"
        f"Type a query or [cyan]help[/cyan] for examples. [dim]quit[/dim] to exit.\n"
        f"{llm_status}",
        border_style="cyan",
    ))

    while True:
        try:
            query = console.input("[bold green]> [/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        q = query.strip().lower()
        if q in ("quit", "exit", "q", "bye"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not q:
            continue

        try:
            parse_and_execute(query)
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
