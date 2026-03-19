"""FotMob CLI - Query football data from your terminal."""

import logging
import click
from rich.console import Console

from api import FotMobAPI

logger = logging.getLogger(__name__)
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
)

console = Console()
api = FotMobAPI()

# Well-known league IDs for quick access
LEAGUE_IDS = {
    "premier league": 47, "pl": 47, "epl": 47,
    "la liga": 87, "laliga": 87,
    "bundesliga": 54,
    "serie a": 55, "seriea": 55,
    "ligue 1": 53, "ligue1": 53,
    "champions league": 42, "ucl": 42, "cl": 42,
    "europa league": 73, "uel": 73, "el": 73,
    "eredivisie": 57,
    "mls": 130,
    "world cup": 77,
}


def resolve_team(name):
    """Search for a team and return its ID and name."""
    results = api.search(name)
    for group in results:
        suggestions = group.get("suggestions", [])
        for s in suggestions:
            if s.get("type") == "team":
                return s.get("id"), s.get("name", name)
    return None, None


def resolve_league(name):
    """Resolve a league name to its ID."""
    key = name.lower().strip()
    if key in LEAGUE_IDS:
        return LEAGUE_IDS[key]

    # Try numeric ID
    try:
        return int(name)
    except ValueError:
        pass

    # Search
    results = api.search(name)
    for group in results:
        suggestions = group.get("suggestions", [])
        for s in suggestions:
            if s.get("type") == "league":
                return s.get("id")
    return None


@click.group()
def cli():
    """FotMob CLI - Football data in your terminal.

    Query live scores, standings, team info, transfers, and news
    from FotMob directly in your terminal.
    """
    pass


@cli.command()
@click.argument("query")
def search(query):
    """Search for teams, players, or leagues.

    Example: fotmob search "Arsenal"
    """
    try:
        results = api.search(query)
        show_search_results(results)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("league")
def standings(league):
    """Show league standings/table.

    LEAGUE can be a name (e.g., "Premier League", "pl") or numeric ID.

    Examples:
        fotmob standings pl
        fotmob standings "la liga"
        fotmob standings 47
    """
    try:
        league_id = resolve_league(league)
        if not league_id:
            console.print(f"[red]Could not find league: {league}[/red]")
            return
        data = api.league(league_id)
        show_standings(data)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("league")
@click.option("--round", "-r", "round_num", default=None, help="Specific round/gameweek number")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all fixtures")
def fixtures(league, round_num, show_all):
    """Show league fixtures and results.

    By default shows the current gameweek. Use --round for a specific gameweek.

    Examples:
        fotmob fixtures pl
        fotmob fixtures pl --round 30
        fotmob fixtures "champions league" --all
    """
    try:
        league_id = resolve_league(league)
        if not league_id:
            console.print(f"[red]Could not find league: {league}[/red]")
            return
        data = api.league(league_id)
        show_league_fixtures(data, round_num=round_num, show_all=show_all)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("name")
def team(name):
    """Show team overview, form, and upcoming matches.

    Examples:
        fotmob team Arsenal
        fotmob team "Manchester United"
    """
    try:
        team_id, team_name = resolve_team(name)
        if not team_id:
            console.print(f"[red]Could not find team: {name}[/red]")
            return
        data = api.team(team_id)
        show_team_overview(data)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("name")
def squad(name):
    """Show team squad/roster.

    Examples:
        fotmob squad Arsenal
        fotmob squad "Real Madrid"
    """
    try:
        team_id, team_name = resolve_team(name)
        if not team_id:
            console.print(f"[red]Could not find team: {name}[/red]")
            return
        data = api.team(team_id)
        console.print(f"\n[bold cyan]{team_name}[/bold cyan] Squad\n")
        show_team_squad(data)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command(name="team-fixtures")
@click.argument("name")
@click.option("--limit", "-n", default=10, help="Number of fixtures to show")
def team_fixtures(name, limit):
    """Show a team's fixtures and recent results.

    Examples:
        fotmob team-fixtures Arsenal
        fotmob team-fixtures "Barcelona" --limit 20
    """
    try:
        team_id, team_name = resolve_team(name)
        if not team_id:
            console.print(f"[red]Could not find team: {name}[/red]")
            return
        data = api.team(team_id)
        fixtures = data.get("fixtures", {}).get("allFixtures", {})
        all_matches = fixtures.get("fixtures", [])

        if not all_matches:
            console.print("[yellow]No fixtures found.[/yellow]")
            return

        # Show around current time - mix of recent and upcoming
        show_matches(all_matches[:limit], title=f"{team_name} Fixtures")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


# Cache: maps match_id -> league_id for faster future lookups
_match_league_cache = {}


def _find_match_url(match_id):
    """Find the full page URL for a match ID by searching league/team data."""
    match_id = str(match_id)

    # Check cached league first for faster repeat lookups
    all_league_ids = [47, 87, 54, 55, 53, 42, 73]
    if match_id in _match_league_cache:
        cached = _match_league_cache[match_id]
        # Put the cached league first in the search order
        all_league_ids = [cached] + [lid for lid in all_league_ids if lid != cached]

    for league_id in all_league_ids:
        try:
            data = api.league(league_id)
            for m in data.get("overview", {}).get("leagueOverviewMatches", []):
                if str(m.get("id")) == match_id:
                    _match_league_cache[match_id] = league_id
                    return m.get("pageUrl")
            for m in data.get("fixtures", {}).get("allMatches", []):
                if str(m.get("id")) == match_id:
                    _match_league_cache[match_id] = league_id
                    return m.get("pageUrl")
        except Exception as e:
            logger.debug("Error searching league %s for match %s: %s", league_id, match_id, e)
            continue

    return None


@cli.command()
@click.argument("match_id")
def match(match_id):
    """Show detailed match info: events, stats, lineups.

    Uses browser to bypass Turnstile (first call takes ~10s to launch).
    MATCH_ID is the numeric FotMob match ID (find it via fixtures or search).

    Examples:
        fotmob match 4813666
    """
    try:
        console.print("[dim]Finding match URL...[/dim]")
        page_url = _find_match_url(match_id)

        if not page_url:
            console.print("[yellow]Could not find match URL in major leagues. Trying direct...[/yellow]")

        console.print("[dim]Loading match details (browser)...[/dim]")
        from browser import get_match_details
        data = get_match_details(match_id, match_url=page_url)
        if data and "general" in data:
            show_match_details(data)
        else:
            console.print("[red]Could not load match data. The match may be from a league not in our search scope.[/red]")
            console.print("[dim]Tip: Use 'fotmob fixtures <league>' to find match IDs with working URLs.[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("query")
def player(query):
    """Show detailed player stats and recent matches.

    Uses browser to bypass Turnstile (first call takes ~10s to launch).
    QUERY is a player name — will search and pick the best match.

    Examples:
        fotmob player "Bukayo Saka"
        fotmob player Haaland
    """
    try:
        # First search for the player to get their ID
        results = api.search(query)
        player_id = None
        player_name = query
        for group in results:
            for s in group.get("suggestions", []):
                if s.get("type") == "player":
                    player_id = s.get("id")
                    player_name = s.get("name", query)
                    break
            if player_id:
                break

        if not player_id:
            console.print(f"[red]Could not find player: {query}[/red]")
            return

        console.print(f"[dim]Loading {player_name} stats (browser)...[/dim]")
        from browser import get_player_data
        data = get_player_data(player_id)
        if data:
            show_player_stats(data)
        else:
            console.print("[red]Could not load player data.[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--page", "-p", default=1, help="Page number")
def transfers(page):
    """Show recent transfers.

    Examples:
        fotmob transfers
        fotmob transfers --page 2
    """
    try:
        data = api.transfers(page=page)
        show_transfers(data)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--page", "-p", default=1, help="Page number")
def news(page):
    """Show latest football news.

    Examples:
        fotmob news
        fotmob news --page 2
    """
    try:
        data = api.world_news(page=page)
        show_news(data)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
def leagues():
    """List all available leagues with their IDs.

    Shows popular leagues. Use the ID with other commands.
    """
    try:
        data = api.all_leagues()
        popular = data.get("popular", [])
        if popular:
            from rich.table import Table
            table = Table(title="  Popular Leagues", show_header=True, title_style="bold cyan")
            table.add_column("ID", width=8, style="dim")
            table.add_column("League", width=30)

            for league in popular:
                table.add_row(str(league.get("id", "")), league.get("name", ""))
            console.print(table)
            console.print()

        # Also show shortcut names
        console.print("[bold]Quick shortcuts:[/bold]")
        shortcuts = {}
        for name, lid in LEAGUE_IDS.items():
            if lid not in shortcuts:
                shortcuts[lid] = []
            shortcuts[lid].append(name)
        for lid, names in sorted(shortcuts.items()):
            console.print(f"  [dim]{lid:>5}[/dim]  {', '.join(names)}")
        console.print()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("league")
@click.option("--stat", "-s", default="goals", help="Stat type: goals, assists, rating, etc.")
@click.option("--limit", "-n", default=20, help="Number of players to show")
def top_scorers(league, stat, limit):
    """Show top scorers/stats for a league.

    Examples:
        fotmob top-scorers pl
        fotmob top-scorers "la liga" --stat assists
    """
    try:
        league_id = resolve_league(league)
        if not league_id:
            console.print(f"[red]Could not find league: {league}[/red]")
            return
        data = api.league(league_id)
        stats = data.get("stats", {})
        players = stats.get("players", [])

        if not players:
            console.print("[yellow]No stats available.[/yellow]")
            return

        # Find the matching stat category (prefer exact header match)
        target = None
        stat_lower = stat.lower()
        for p in players:
            header = p.get("header", "").lower()
            if header == stat_lower:
                target = p
                break
        if not target:
            for p in players:
                header = p.get("header", "").lower()
                name = p.get("name", "").lower()
                if header.startswith(stat_lower) or name.startswith(stat_lower):
                    target = p
                    break
        if not target:
            for p in players:
                header = p.get("header", "").lower()
                if stat_lower in header:
                    target = p
                    break
        if not target:
            target = players[0]

        header = target.get("header", "Top Players")
        fetch_url = target.get("fetchAllUrl", "")

        if fetch_url:
            # Fetch full list from data.fotmob.com
            full_data = api.league_stats(fetch_url)
            top_lists = full_data.get("TopLists", [])
            if top_lists:
                stat_list = top_lists[0].get("StatList", [])
            else:
                stat_list = []
        else:
            stat_list = target.get("topThree", [])

        if not stat_list:
            console.print("[yellow]No data available.[/yellow]")
            return

        from rich.table import Table
        table = Table(title=f"  {header}", show_header=True, title_style="bold cyan")
        table.add_column("#", width=4, justify="right")
        table.add_column("Player", width=24)
        table.add_column("Team", width=18, style="dim")
        table.add_column("Value", width=6, justify="center", style="bold")
        table.add_column("MP", width=4, justify="center", style="dim")

        for player in stat_list[:limit]:
            name = player.get("ParticipantName", player.get("name", ""))
            team = player.get("TeamName", player.get("teamName", ""))
            val = player.get("StatValue", player.get("value", ""))
            val_str = str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
            mp = str(player.get("MatchesPlayed", ""))
            rank = str(player.get("Rank", ""))
            table.add_row(rank, name, team, val_str, mp)

        console.print(table)
        console.print()

        # Show available stat types
        available = [p.get("header", "") for p in players]
        console.print(f"[dim]Available stats: {', '.join(available)}[/dim]")
        console.print("[dim]Use --stat <name> to view different stats[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    import sys
    # If no command given, launch interactive mode
    if len(sys.argv) == 1:
        from interactive import run_interactive
        run_interactive()
    else:
        cli()
