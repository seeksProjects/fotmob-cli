"""Live match tracker - polls FotMob for real-time match updates.

Uses the team/league API endpoints (no Turnstile) to poll for score changes,
and optionally the browser for detailed events on a specific match.
"""

import time
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from api import FotMobAPI

console = Console()
api = FotMobAPI()


def _build_match_table(matches, title="Live Matches"):
    """Build a rich table from match data."""
    table = Table(title=f"  {title}", show_header=True, title_style="bold cyan")
    table.add_column("Min", width=6, justify="center")
    table.add_column("Home", width=20, justify="right")
    table.add_column("Score", width=7, justify="center", style="bold")
    table.add_column("Away", width=20)
    table.add_column("League", width=18, style="dim")

    for m in matches:
        home = m.get("home", {})
        away = m.get("away", {})
        status = m.get("status", {})

        home_name = home.get("shortName", home.get("name", ""))
        away_name = away.get("shortName", away.get("name", ""))

        score_str = status.get("scoreStr", "")
        reason = status.get("reason", {})
        status_short = reason.get("short", "")

        # Determine minute or status
        if status.get("started") and not status.get("finished"):
            # Live match
            minute = status.get("liveTime", {})
            if isinstance(minute, dict):
                min_str = f"[green]{minute.get('short', 'LIVE')}[/green]"
            else:
                min_str = "[green]LIVE[/green]"
            score_style = "bold green"
        elif status.get("finished"):
            min_str = status_short or "FT"
            score_style = "bold"
        else:
            # Not started
            from display import format_utc_time
            min_str = format_utc_time(status.get("utcTime", ""))
            score_str = "vs"
            score_style = "dim"

        league = m.get("tournament", {}).get("name", "") if "tournament" in m else ""

        table.add_row(
            min_str,
            home_name,
            Text(score_str or "vs", style=score_style),
            away_name,
            league,
        )

    return table


def track_team_live(team_name, interval=60):
    """Track a team's current/next match live.

    Polls the team endpoint every `interval` seconds and displays
    score updates using Rich Live display.
    """
    from interactive import _resolve_team

    team_id, resolved_name = _resolve_team(team_name)
    if not team_id:
        console.print(f"[red]Could not find team: {team_name}[/red]")
        return

    console.print(f"[dim]Tracking {resolved_name} live (updates every {interval}s, Ctrl+C to stop)...[/dim]\n")

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                try:
                    # Reduce cache TTL for live tracking
                    api._cache_ttl = 10
                    data = api.team(team_id)
                    api._cache = {}  # Clear cache to force fresh data

                    overview = data.get("overview", {})
                    has_ongoing = data.get("fixtures", {}).get("hasOngoingMatch", False)

                    if has_ongoing:
                        # There's a live match — show it prominently
                        # Get match info from overview fixtures
                        ov_fixtures = overview.get("overviewFixtures", [])
                        live_matches = []
                        for m in ov_fixtures:
                            s = m.get("status", {})
                            if s.get("started") and not s.get("finished"):
                                live_matches.append(m)

                        if live_matches:
                            table = _build_match_table(live_matches, f"{resolved_name} - LIVE")
                        else:
                            # Fallback: show from nextMatch/lastMatch
                            nm = overview.get("nextMatch") or overview.get("lastMatch")
                            if nm:
                                live_matches = [nm]
                                table = _build_match_table(live_matches, f"{resolved_name} - LIVE")
                            else:
                                table = Table(title=f"  {resolved_name}")
                                table.add_row("No live match data available")
                    else:
                        # No live match — show next + last
                        display_matches = []
                        lm = overview.get("lastMatch")
                        nm = overview.get("nextMatch")
                        if lm:
                            display_matches.append(lm)
                        if nm:
                            display_matches.append(nm)

                        if display_matches:
                            table = _build_match_table(display_matches, f"{resolved_name} - No Live Match")
                        else:
                            table = Table(title=f"  {resolved_name}")
                            table.add_row("No match data available")

                    # Add timestamp
                    now = datetime.now().strftime("%H:%M:%S")
                    output = table
                    live.update(
                        Panel(output, subtitle=f"[dim]Updated {now} | Ctrl+C to stop[/dim]", border_style="cyan")
                    )

                except Exception as e:
                    live.update(Panel(f"[red]Error: {e}[/red]\n[dim]Retrying...[/dim]"))

                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped tracking.[/dim]")
    finally:
        api._cache_ttl = 60  # Restore normal cache


def track_league_live(league_name, interval=60):
    """Track all live/ongoing matches in a league.

    Polls the league endpoint every `interval` seconds.
    """
    from nlp import extract_league, fuzzy_match_league

    league_id, _, _ = extract_league(league_name)
    if not league_id:
        league_id = fuzzy_match_league(league_name)
    if not league_id:
        console.print(f"[red]Could not find league: {league_name}[/red]")
        return

    console.print(f"[dim]Tracking league live (updates every {interval}s, Ctrl+C to stop)...[/dim]\n")

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                try:
                    api._cache = {}  # Clear cache for fresh data
                    data = api.league(league_id)

                    details = data.get("details", {})
                    league_display = details.get("name", "League")

                    # Get current round matches
                    fixtures = data.get("fixtures", {})
                    all_matches = fixtures.get("allMatches", [])
                    first_unplayed = fixtures.get("firstUnplayedMatch", {})
                    first_idx = first_unplayed.get("firstUnplayedMatchIndex", 0)

                    # Find current round
                    if first_idx > 0 and first_idx < len(all_matches):
                        target_round = all_matches[first_idx].get("round")
                        # Include the previous round too (for just-finished matches)
                        prev_round = all_matches[max(0, first_idx - 1)].get("round")
                        current = [m for m in all_matches
                                   if m.get("round") in (target_round, prev_round)]
                    else:
                        current = all_matches[:10]

                    # Separate live, finished today, upcoming
                    live_matches = []
                    other = []
                    for m in current:
                        s = m.get("status", {})
                        if s.get("started") and not s.get("finished"):
                            live_matches.append(m)
                        else:
                            other.append(m)

                    # Build display
                    all_display = live_matches + other
                    if all_display:
                        title = f"{league_display} - {len(live_matches)} LIVE" if live_matches else league_display
                        table = _build_match_table(all_display, title)
                    else:
                        table = Table(title=f"  {league_display}")
                        table.add_row("No matches in current round")

                    now = datetime.now().strftime("%H:%M:%S")
                    live.update(
                        Panel(table, subtitle=f"[dim]Updated {now} | Ctrl+C to stop[/dim]", border_style="cyan")
                    )

                except Exception as e:
                    live.update(Panel(f"[red]Error: {e}[/red]\n[dim]Retrying...[/dim]"))

                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped tracking.[/dim]")
    finally:
        api._cache_ttl = 60
