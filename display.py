"""Display helpers - formats API data into rich terminal output."""

from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()


def format_utc_time(utc_str):
    """Convert UTC time string to local readable format."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%b %d, %H:%M")
    except (ValueError, AttributeError):
        return utc_str or "TBD"


def result_color(result_str):
    """Return color for W/D/L."""
    if result_str == "W":
        return "green"
    elif result_str == "L":
        return "red"
    elif result_str == "D":
        return "yellow"
    return "white"


# --- Search ---

def show_search_results(results):
    """Display search results."""
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for group in results:
        title = group.get("title", {})
        group_name = title.get("value", title.get("key", "Unknown")) if isinstance(title, dict) else str(title)
        items = group.get("suggestions", [])
        if not items:
            continue

        # Separate by type
        item_type = items[0].get("type", "") if items else ""

        if item_type == "match":
            table = Table(title=f"  {group_name}", show_header=True, title_style="bold cyan")
            table.add_column("Home", width=18, justify="right")
            table.add_column("Score", width=7, justify="center", style="bold")
            table.add_column("Away", width=18)
            table.add_column("League", width=20, style="dim")
            table.add_column("Date", width=14, style="dim")

            for item in items[:10]:
                home = item.get("homeTeamName", "")
                away = item.get("awayTeamName", "")
                status = item.get("status", {})
                score = status.get("scoreStr", "vs")
                league = item.get("leagueName", "")
                date = format_utc_time(status.get("utcTime", ""))
                table.add_row(home, score, away, league, date)
        else:
            table = Table(title=f"  {group_name}", show_header=True, title_style="bold cyan")
            table.add_column("ID", style="dim", width=8)
            table.add_column("Name", style="bold", width=25)
            table.add_column("Info", style="dim", width=25)

            for item in items[:10]:
                name = item.get("name", "")
                pid = str(item.get("id", ""))
                info = item.get("leagueName", item.get("teamName", ""))
                table.add_row(pid, name, info)

        console.print(table)
        console.print()


# --- League Standings ---

def show_standings(league_data):
    """Display league standings table."""
    details = league_data.get("details", {})
    league_name = details.get("name", "League")

    table_data = league_data.get("table", [])
    if not table_data:
        console.print("[yellow]No standings available.[/yellow]")
        return

    for group in table_data:
        data = group.get("data", {})
        standings = data.get("table", {}).get("all", [])
        if not standings:
            continue

        group_name = data.get("leagueName", league_name)
        table = Table(title=f"  {group_name}", show_header=True, title_style="bold cyan")
        table.add_column("#", justify="right", width=3)
        table.add_column("Team", width=22)
        table.add_column("MP", justify="center", width=4)
        table.add_column("W", justify="center", width=4, style="green")
        table.add_column("D", justify="center", width=4, style="yellow")
        table.add_column("L", justify="center", width=4, style="red")
        table.add_column("GF-GA", justify="center", width=7)
        table.add_column("GD", justify="center", width=5)
        table.add_column("Pts", justify="center", width=5, style="bold")

        for team in standings:
            qual_color = team.get("qualColor", "")
            name_style = "bold" if qual_color else ""
            idx = str(team.get("idx", ""))
            table.add_row(
                idx,
                Text(team.get("shortName", team.get("name", "")), style=name_style),
                str(team.get("played", "")),
                str(team.get("wins", "")),
                str(team.get("draws", "")),
                str(team.get("losses", "")),
                team.get("scoresStr", ""),
                str(team.get("goalConDiff", "")),
                str(team.get("pts", "")),
            )

        console.print(table)
        console.print()


# --- Match List ---

def show_matches(matches, title="Matches"):
    """Display a list of matches."""
    if not matches:
        console.print("[yellow]No matches found.[/yellow]")
        return

    table = Table(title=f"  {title}", show_header=True, title_style="bold cyan")
    table.add_column("Date", width=14)
    table.add_column("Home", width=20, justify="right")
    table.add_column("Score", width=7, justify="center", style="bold")
    table.add_column("Away", width=20)
    table.add_column("Status", width=8)

    for m in matches:
        home = m.get("home", {})
        away = m.get("away", {})
        status = m.get("status", {})

        home_name = home.get("shortName", home.get("name", ""))
        away_name = away.get("shortName", away.get("name", ""))

        score_str = status.get("scoreStr", "")
        if not score_str and m.get("notStarted"):
            score_str = "vs"

        reason = status.get("reason", {})
        status_text = reason.get("short", "")
        if not status_text:
            if status.get("finished"):
                status_text = "FT"
            elif status.get("started") and not status.get("finished"):
                status_text = "LIVE"
            elif m.get("notStarted"):
                status_text = ""

        date_str = format_utc_time(status.get("utcTime", ""))

        # Color based on live/finished
        score_style = "bold"
        if status.get("started") and not status.get("finished"):
            score_style = "bold green"
            status_text = "[green]LIVE[/green]"

        table.add_row(
            date_str,
            home_name,
            Text(score_str or "vs", style=score_style),
            away_name,
            status_text,
        )

    console.print(table)
    console.print()


# --- Team Info ---

def show_team_overview(team_data):
    """Display team overview."""
    details = team_data.get("details", {})
    overview = team_data.get("overview", {})

    team_name = details.get("name", "Team")
    country = details.get("country", "")

    # Basic info panel
    info_lines = [f"[bold]{team_name}[/bold]"]
    if country:
        info_lines.append(f"Country: {country}")

    venue = overview.get("venue", {})
    if venue:
        vname = venue.get("widget", {}).get("name", "")
        vcity = venue.get("widget", {}).get("city", "")
        if vname:
            info_lines.append(f"Stadium: {vname}" + (f", {vcity}" if vcity else ""))

    console.print(Panel("\n".join(info_lines), title="Team Info", border_style="cyan"))

    # Form
    form = overview.get("teamForm", [])
    if form:
        form_str = " ".join(
            f"[{result_color(f.get('resultString', ''))}]{f.get('resultString', '?')}[/{result_color(f.get('resultString', ''))}]"
            for f in form[:10]
        )
        console.print(f"  Form: {form_str}")
        console.print()

    # Next match
    nm = overview.get("nextMatch")
    if nm:
        home = nm.get("home", {})
        away = nm.get("away", {})
        date = format_utc_time(nm.get("status", {}).get("utcTime", ""))
        tourn = nm.get("tournament", {}).get("name", "")
        console.print(
            f"  Next: [bold]{home.get('name', '')}[/bold] vs [bold]{away.get('name', '')}[/bold]"
            f"  {date}  [dim]{tourn}[/dim]"
        )

    # Last match
    lm = overview.get("lastMatch")
    if lm:
        home = lm.get("home", {})
        away = lm.get("away", {})
        score = lm.get("status", {}).get("scoreStr", "")
        date = format_utc_time(lm.get("status", {}).get("utcTime", ""))
        tourn = lm.get("tournament", {}).get("name", "")
        console.print(
            f"  Last: [bold]{home.get('name', '')}[/bold] {score} [bold]{away.get('name', '')}[/bold]"
            f"  {date}  [dim]{tourn}[/dim]"
        )

    console.print()


def show_team_squad(team_data):
    """Display team squad."""
    squad = team_data.get("squad", {})

    if isinstance(squad, list):
        # Old format
        groups = squad
    elif isinstance(squad, dict):
        groups = squad.get("squad", squad.get("members", []))
        if not isinstance(groups, list):
            groups = [squad]
    else:
        console.print("[yellow]No squad data available.[/yellow]")
        return

    if not groups:
        console.print("[yellow]No squad data available.[/yellow]")
        return

    for group in groups:
        if isinstance(group, dict):
            title = group.get("title", "Players")
            members = group.get("members", [])
        else:
            continue

        if not members:
            continue

        table = Table(title=f"  {title}", show_header=True, title_style="bold cyan")
        table.add_column("#", width=4, justify="right")
        table.add_column("Name", width=25)
        table.add_column("ID", width=8, style="dim")

        for player in members:
            num = str(player.get("shirtNumber", ""))
            name = player.get("name", "")
            pid = str(player.get("id", ""))
            table.add_row(num, name, pid)

        console.print(table)
        console.print()


# --- Transfers ---

def show_transfers(transfer_data):
    """Display transfer feed."""
    transfers = transfer_data.get("transfers", [])
    if not transfers:
        console.print("[yellow]No transfers found.[/yellow]")
        return

    table = Table(title="  Recent Transfers", show_header=True, title_style="bold cyan")
    table.add_column("Player", width=22)
    table.add_column("From", width=18)
    table.add_column("To", width=18)
    table.add_column("Fee", width=14)

    for t in transfers[:20]:
        player = t.get("name", "")
        from_team = t.get("fromClub", "")
        to_team = t.get("toClub", "")
        fee = t.get("fee", {})
        fee_str = fee.get("feeText", "") if isinstance(fee, dict) else str(fee)
        table.add_row(player, from_team, to_team, fee_str)

    console.print(table)
    console.print()


# --- News ---

def show_news(news_data):
    """Display news feed."""
    articles = news_data if isinstance(news_data, list) else news_data.get("articles", [])
    if not articles:
        console.print("[yellow]No news found.[/yellow]")
        return

    for article in articles[:15]:
        title = article.get("title", "")
        source = article.get("sourceStr", article.get("source", ""))
        page_url = article.get("page", {}).get("url", "") if isinstance(article.get("page"), dict) else ""
        gmtime = article.get("gmtTime", "")
        date = format_utc_time(gmtime) if gmtime else ""

        console.print(f"  [bold]{title}[/bold]")
        console.print(f"  [dim]{source}  {date}[/dim]")
        if page_url:
            console.print(f"  [dim blue]https://www.fotmob.com{page_url}[/dim blue]")
        console.print()


# --- League Fixtures ---

def show_league_fixtures(league_data, round_num=None, show_all=False):
    """Display league fixtures, optionally filtered by round."""
    fixtures = league_data.get("fixtures", {})
    all_matches = fixtures.get("allMatches", [])

    if not all_matches:
        console.print("[yellow]No fixtures found.[/yellow]")
        return

    if round_num:
        all_matches = [m for m in all_matches if str(m.get("round", "")) == str(round_num)]
    elif not show_all:
        # Show matches around the current gameweek
        first_unplayed = fixtures.get("firstUnplayedMatch", {})
        first_idx = first_unplayed.get("firstUnplayedMatchIndex", 0)
        if first_idx > 0:
            # Find the round of the first unplayed match
            target_round = all_matches[first_idx].get("round") if first_idx < len(all_matches) else None
            if target_round is not None:
                all_matches = [m for m in all_matches if m.get("round") == target_round]
            else:
                all_matches = all_matches[max(0, first_idx - 5):first_idx + 10]
        else:
            all_matches = all_matches[:10]

    show_matches(all_matches, title="Fixtures")


# --- Match Details (browser-sourced) ---

def show_match_details(match_data):
    """Display detailed match info including events, stats, lineups."""
    if not match_data:
        console.print("[red]No match data available.[/red]")
        return

    general = match_data.get("general", {})
    header = match_data.get("header", {})
    content = match_data.get("content", {})

    # Match header
    teams = header.get("teams", [])
    home_team = teams[0] if len(teams) > 0 else {}
    away_team = teams[1] if len(teams) > 1 else {}
    home_name = home_team.get("name", "Home")
    away_name = away_team.get("name", "Away")
    home_score = home_team.get("score", "")
    away_score = away_team.get("score", "")

    league = general.get("leagueName", "")
    match_round = general.get("matchRound", "")
    status = header.get("status", {})
    reason = status.get("reason", {}).get("long", "")
    utc = status.get("utcTime", "")
    date_str = format_utc_time(utc) if utc else ""

    console.print(Panel(
        f"[bold]{home_name}[/bold]  [bold cyan]{home_score} - {away_score}[/bold cyan]  [bold]{away_name}[/bold]\n"
        f"[dim]{league} Round {match_round}  |  {date_str}  |  {reason}[/dim]",
        border_style="cyan",
    ))

    # Events (goals, cards, subs)
    match_facts = content.get("matchFacts", {})
    events_data = match_facts.get("events", {})
    events_list = events_data.get("events", [])

    if events_list:
        console.print("[bold]Match Events:[/bold]")
        for ev in events_list:
            ev_type = ev.get("type", "")
            time_str = str(ev.get("timeStr", ""))
            player = ev.get("player", {})
            pname = player.get("name", "")

            if ev_type == "Goal":
                is_home = ev.get("isHome", True)
                assist = ev.get("assistStr", "")
                side = home_name if is_home else away_name
                score_after = f"{ev.get('homeScore', '')}-{ev.get('awayScore', '')}"
                assist_info = f" (assist: {assist})" if assist else ""
                console.print(f"  [green]GOAL {time_str}'[/green]  {pname}{assist_info}  [dim]{side}[/dim]  [{score_after}]")

            elif ev_type == "Card":
                card = ev.get("card", "")
                color = "yellow" if "yellow" in card.lower() else "red"
                card_icon = "YC" if "yellow" in card.lower() else "RC"
                console.print(f"  [{color}]{card_icon} {time_str}'[/{color}]  {pname}  [dim]{card}[/dim]")

            elif ev_type == "Substitution":
                swap = ev.get("swap", [])
                p_on = swap[0].get("name", "") if len(swap) > 0 else ""
                p_off = swap[1].get("name", "") if len(swap) > 1 else ""
                if p_on or p_off:
                    console.print(f"  [blue]SUB {time_str}'[/blue]  [green]{p_on}[/green] on, [red]{p_off}[/red] off")

        console.print()

    # Stats
    stats = content.get("stats", {})
    periods = stats.get("Periods", {})
    all_stats = periods.get("All", {}).get("stats", [])

    if all_stats:
        # Show "Top stats" group
        for stat_group in all_stats:
            if stat_group.get("title", "").lower() in ("top stats", "shots", "expected goals (xg)"):
                table = Table(
                    title=f"  {stat_group.get('title', 'Stats')}",
                    show_header=True, title_style="bold cyan",
                )
                table.add_column(home_name, width=12, justify="center")
                table.add_column("Stat", width=22, justify="center", style="dim")
                table.add_column(away_name, width=12, justify="center")

                for s in stat_group.get("stats", []):
                    if s.get("type") == "title":
                        continue
                    stat_vals = s.get("stats", [])
                    home_val = str(stat_vals[0]) if len(stat_vals) > 0 else ""
                    away_val = str(stat_vals[1]) if len(stat_vals) > 1 else ""
                    stat_name = s.get("title", "")
                    table.add_row(home_val, stat_name, away_val)

                console.print(table)
                console.print()

    # Lineups
    lineup = content.get("lineup", {})
    if lineup:
        for side, key in [("Home", "homeTeam"), ("Away", "awayTeam")]:
            team_lineup = lineup.get(key, {})
            team_name = team_lineup.get("teamName", side)
            formation = team_lineup.get("formation", "")
            starters = team_lineup.get("starters", [])
            subs = team_lineup.get("subs", [])

            if not starters:
                continue

            table = Table(
                title=f"  {team_name} ({formation})",
                show_header=True, title_style="bold cyan",
            )
            table.add_column("#", width=4, justify="right")
            table.add_column("Player", width=22)
            table.add_column("Rating", width=7, justify="center")
            table.add_column("Events", width=20, style="dim")

            for row in starters:
                for p in row if isinstance(row, list) else [row]:
                    if not isinstance(p, dict):
                        continue
                    num = str(p.get("shirt", ""))
                    pname = p.get("name", {})
                    if isinstance(pname, dict):
                        pname = pname.get("fullName", pname.get("lastName", ""))
                    rating = p.get("rating", {})
                    if isinstance(rating, dict):
                        rating = rating.get("num", "")
                    rating_str = str(rating) if rating else ""

                    # Events for this player
                    ev_strs = []
                    p_events = p.get("events", {})
                    if p_events.get("g"):
                        ev_strs.append(f"G:{p_events['g']}")
                    if p_events.get("as"):
                        ev_strs.append(f"A:{p_events['as']}")
                    if p_events.get("yc"):
                        ev_strs.append("YC")
                    if p_events.get("rc"):
                        ev_strs.append("RC")
                    if p_events.get("sub"):
                        sub_info = p_events["sub"]
                        if isinstance(sub_info, dict):
                            ev_strs.append(f"sub:{sub_info.get('minute', '')}'")

                    table.add_row(num, str(pname), rating_str, " ".join(ev_strs))

            console.print(table)
            console.print()


# --- Player Stats (browser-sourced) ---

def show_player_stats(player_data):
    """Display detailed player stats."""
    if not player_data:
        console.print("[red]No player data available.[/red]")
        return

    name = player_data.get("name", "Unknown")
    birth = player_data.get("birthDate", {})
    birth_date = ""
    if isinstance(birth, dict):
        birth_date = format_utc_time(birth.get("utcTime", ""))
    position = player_data.get("positionDescription", {})
    if isinstance(position, dict):
        position = position.get("primaryPosition", {}).get("label", "")

    team = player_data.get("primaryTeam", {})
    team_name = team.get("teamName", "")

    # Info panel
    info_lines = [f"[bold]{name}[/bold]"]
    if position:
        info_lines.append(f"Position: {position}")
    if team_name:
        info_lines.append(f"Team: {team_name}")
    if birth_date:
        info_lines.append(f"Born: {birth_date}")

    injury = player_data.get("injuryInformation")
    if injury:
        inj_type = injury.get("injuryType", "")
        expected = injury.get("expectedReturn", {})
        exp_str = ""
        if isinstance(expected, dict):
            exp_str = expected.get("expectedReturnFull", "")
        if inj_type:
            info_lines.append(f"[red]Injury: {inj_type}[/red]" + (f" (return: {exp_str})" if exp_str else ""))

    console.print(Panel("\n".join(info_lines), title="Player Profile", border_style="cyan"))

    # Season stats
    main = player_data.get("mainLeague", {})
    league_name = main.get("leagueName", "")
    stats = main.get("stats", [])

    if stats:
        table = Table(title=f"  Season Stats - {league_name}", show_header=True, title_style="bold cyan")
        table.add_column("Stat", width=20)
        table.add_column("Value", width=10, justify="center", style="bold")

        for s in stats:
            title = s.get("title", "")
            value = s.get("value", "")
            table.add_row(title, str(value))

        console.print(table)
        console.print()

    # Recent matches
    recent = player_data.get("recentMatches", [])
    if recent:
        table = Table(title="  Recent Matches", show_header=True, title_style="bold cyan")
        table.add_column("Date", width=12)
        table.add_column("Opponent", width=18)
        table.add_column("Score", width=7, justify="center", style="bold")
        table.add_column("Min", width=5, justify="center")
        table.add_column("Rating", width=7, justify="center")
        table.add_column("G", width=3, justify="center", style="green")
        table.add_column("A", width=3, justify="center", style="cyan")

        for m in recent[:10]:
            date = format_utc_time(m.get("matchDate", {}).get("utcTime", ""))
            opp = m.get("opponentTeamName", "")
            h_score = m.get("homeScore", "")
            a_score = m.get("awayScore", "")
            score = f"{h_score}-{a_score}"
            mins = str(m.get("minutesPlayed", ""))
            rating = m.get("ratingProps", {})
            if isinstance(rating, dict):
                rating = str(rating.get("num", ""))
            else:
                rating = str(rating) if rating else ""
            goals = str(m.get("goals", "")) if m.get("goals") else ""
            assists = str(m.get("assists", "")) if m.get("assists") else ""

            table.add_row(date, opp, score, mins, rating, goals, assists)

        console.print(table)
        console.print()
