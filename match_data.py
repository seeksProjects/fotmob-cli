"""Comprehensive match data extractor.

Extracts ALL available data from a FotMob match page and returns
a structured dict that can be summarized for AI or displayed directly.
"""


def extract_tv_and_odds_from_browser(sb):
    """Extract TV channel and odds from the rendered browser page.

    Must be called while the match page is loaded in the browser.
    Returns dict with 'tv_channel' and 'odds'.
    """
    try:
        js = r"""
        let results = {};

        // TV Channel - from info bar
        let lis = document.querySelectorAll("li");
        for (let li of lis) {
            let t = li.textContent.trim();
            if (t.includes("Sport") || t.includes("DStv") || t.includes("ESPN") ||
                t.includes("Sky") || t.includes("NBC") || t.includes("BT Sport") ||
                t.includes("beIN") || t.includes("DAZN") || t.includes("Canal") ||
                t.includes("StarTimes") || t.includes("TV") || t.includes("streaming")) {
                if (!t.includes("Stadium") && !t.includes("Round") && !t.includes("Referee") && t.length < 150 && !t.includes("TV schedules")) {
                    results.tv = t;
                    break;
                }
            }
        }

        // Odds - from the sidebar widget
        let oddsContainer = document.querySelector("[class*='OddsWidget'], [class*='oddswidget'], [class*='odds']");
        if (oddsContainer) {
            results.oddsText = oddsContainer.textContent.trim().slice(0, 300);
        }

        // Also try to get odds from specific bet elements
        let allEls = document.querySelectorAll("span, div, a");
        let oddsProvider = "";
        let oddsVals = [];
        for (let el of allEls) {
            let t = el.textContent.trim();
            if (t === "1XBET" || t === "1xBet" || t === "bet365" || t === "Betway") {
                oddsProvider = t;
            }
        }
        results.oddsProvider = oddsProvider;

        return JSON.stringify(results);
        """
        result = sb.execute_script(js)
        return __import__("json").loads(result)
    except Exception:
        return {}


def extract_full_match_data(page_props):
    """Extract every piece of data from a match page's pageProps.

    Returns a structured dict with all available match information.
    """
    if not page_props:
        return None

    general = page_props.get("general", {})
    header = page_props.get("header", {})
    content = page_props.get("content", {})
    match_facts = content.get("matchFacts", {})
    lineup_data = content.get("lineup", {})

    teams = header.get("teams", [])
    home_team = teams[0] if len(teams) > 0 else {}
    away_team = teams[1] if len(teams) > 1 else {}
    status = header.get("status", {})

    info_box = match_facts.get("infoBox", {})
    stadium_info = info_box.get("Stadium", {})
    referee_info = info_box.get("Referee", {})

    result = {
        # --- GENERAL ---
        "match_id": general.get("matchId"),
        "league": general.get("leagueName", ""),
        "round": general.get("matchRound", ""),
        "date": status.get("utcTime", ""),
        "started": status.get("started", False),
        "finished": status.get("finished", False),
        "is_live": status.get("started", False) and not status.get("finished", False),

        # --- TEAMS & SCORE ---
        "home": {
            "name": home_team.get("name", ""),
            "id": home_team.get("id"),
            "score": home_team.get("score"),
        },
        "away": {
            "name": away_team.get("name", ""),
            "id": away_team.get("id"),
            "score": away_team.get("score"),
        },

        # --- VENUE ---
        "stadium": stadium_info.get("name", ""),
        "city": stadium_info.get("city", ""),
        "country": stadium_info.get("country", ""),
        "capacity": stadium_info.get("capacity"),
        "surface": stadium_info.get("surface", ""),

        # --- REFEREE ---
        "referee": referee_info.get("text", ""),
        "referee_country": referee_info.get("country", ""),

        # --- WEATHER ---
        "weather": _extract_weather(content.get("weather", {})),

        # --- COACHES ---
        "home_coach": _extract_coach(lineup_data.get("homeTeam", {})),
        "away_coach": _extract_coach(lineup_data.get("awayTeam", {})),

        # --- PREDICTED/ACTUAL LINEUPS ---
        "home_lineup": _extract_lineup(lineup_data.get("homeTeam", {})),
        "away_lineup": _extract_lineup(lineup_data.get("awayTeam", {})),

        # --- INJURED & SUSPENDED ---
        "home_injuries": _extract_injuries(lineup_data.get("homeTeam", {})),
        "away_injuries": _extract_injuries(lineup_data.get("awayTeam", {})),

        # --- TEAM FORM ---
        "team_form": _extract_team_form(match_facts.get("teamForm", [])),

        # --- INSIGHTS ---
        "insights": _extract_insights(match_facts.get("insights", [])),

        # --- TOP SCORERS COMPARISON ---
        "top_scorers": _extract_top_scorers(match_facts.get("topScorers", {})),

        # --- POLL (Who will win?) ---
        "poll": _extract_poll(match_facts.get("poll", {})),

        # --- H2H ---
        "h2h": _extract_h2h(content.get("h2h", {})),

        # --- EVENTS (goals, cards, subs — for live/finished matches) ---
        "events": _extract_events(match_facts.get("events", {})),

        # --- STATS (possession, shots, etc. — for live/finished matches) ---
        "stats": _extract_stats(content.get("stats", {})),

        # --- PREVIEW ARTICLES ---
        "previews": _extract_previews(match_facts),

        # --- MARKET VALUES ---
        "home_squad_value": lineup_data.get("homeTeam", {}).get("totalStarterMarketValue"),
        "away_squad_value": lineup_data.get("awayTeam", {}).get("totalStarterMarketValue"),

        # --- TV (extracted from rendered browser DOM) ---
        "tv_channel": page_props.get("_browser_tv_channel", ""),

        # --- BETTING ODDS (from The Odds API) ---
        "odds": _fetch_odds(home_team.get("name", ""), away_team.get("name", ""), general.get("leagueName", "")),
    }

    return result


def _fetch_odds(home_team, away_team, league_name):
    """Fetch betting odds from The Odds API."""
    try:
        from odds import get_match_odds
        return get_match_odds(home_team, away_team, league_name)
    except Exception:
        return None


def _extract_weather(weather):
    if not weather:
        return None
    return {
        "temperature": weather.get("temperature"),
        "description": weather.get("description", ""),
        "wind_speed": weather.get("windSpeed"),
        "humidity": weather.get("relativeHumidity"),
        "rain_chance": weather.get("precipChance"),
    }


def _extract_coach(team_lineup):
    coach = team_lineup.get("coach", {})
    if not coach:
        return None
    return {
        "name": coach.get("name", ""),
        "country": coach.get("countryName", ""),
    }


def _extract_lineup(team_lineup):
    formation = team_lineup.get("formation", "")
    starters = team_lineup.get("starters", [])
    players = []
    for p in starters:
        if isinstance(p, dict):
            name = p.get("name", "")
            if isinstance(name, dict):
                name = name.get("fullName", name.get("lastName", ""))
            players.append({
                "name": name,
                "shirt": p.get("shirtNumber", p.get("shirt")),
                "position_id": p.get("positionId"),
                "age": p.get("age"),
                "country": p.get("countryName", ""),
                "market_value": p.get("marketValue"),
                "rating": p.get("rating", {}).get("num") if isinstance(p.get("rating"), dict) else p.get("rating"),
                "events": p.get("events", {}),
            })
        elif isinstance(p, list):
            for sub_p in p:
                if isinstance(sub_p, dict):
                    name = sub_p.get("name", "")
                    if isinstance(name, dict):
                        name = name.get("fullName", name.get("lastName", ""))
                    players.append({
                        "name": name,
                        "shirt": sub_p.get("shirtNumber", sub_p.get("shirt")),
                        "position_id": sub_p.get("positionId"),
                        "age": sub_p.get("age"),
                        "country": sub_p.get("countryName", ""),
                        "market_value": sub_p.get("marketValue"),
                        "rating": sub_p.get("rating", {}).get("num") if isinstance(sub_p.get("rating"), dict) else sub_p.get("rating"),
                        "events": sub_p.get("events", {}),
                    })
    return {"formation": formation, "players": players}


def _extract_injuries(team_lineup):
    unavailable = team_lineup.get("unavailable", [])
    injuries = []
    for p in unavailable:
        inj = p.get("unavailability", {})
        injuries.append({
            "name": p.get("name", ""),
            "type": inj.get("type", ""),
            "reason": inj.get("reason", ""),
            "expected_return": inj.get("expectedReturn", ""),
        })
    return injuries


def _extract_team_form(team_form):
    """Extract form for both teams."""
    result = []
    for i, team_matches in enumerate(team_form):
        if isinstance(team_matches, list):
            matches = []
            for m in team_matches:
                if isinstance(m, dict):
                    matches.append({
                        "result": m.get("resultString", ""),
                        "home": m.get("home", {}).get("name", "") if isinstance(m.get("home"), dict) else "",
                        "away": m.get("away", {}).get("name", "") if isinstance(m.get("away"), dict) else "",
                        "score": m.get("score", ""),
                        "date": m.get("date", ""),
                    })
            result.append(matches)
    return result


def _extract_insights(insights):
    """Extract all match insights."""
    result = []
    for ins in insights:
        result.append({
            "team_id": ins.get("teamId"),
            "text": ins.get("text", ""),
            "player_id": ins.get("playerId"),
            "type": ins.get("type", ""),
        })
    return result


def _extract_top_scorers(top_scorers):
    """Extract top scorer comparison."""
    if not top_scorers:
        return None
    result = {}
    for key in ["homePlayer", "awayPlayer"]:
        p = top_scorers.get(key, {})
        if p:
            stats = p.get("stats", {})
            result[key] = {
                "name": p.get("fullName", p.get("lastName", "")),
                "goals": stats.get("goals"),
                "assists": stats.get("goalAssist"),
                "xg": stats.get("expectedGoals"),
                "rating": stats.get("playerRating"),
                "matches": stats.get("gamesPlayed"),
                "minutes": stats.get("minsPlayed"),
            }
    return result


def _extract_poll(poll):
    """Extract fan poll / odds data."""
    oddspoll = poll.get("oddspoll", {})
    if not oddspoll:
        return None
    facts = []
    for f in oddspoll.get("Facts", []):
        facts.append({
            "type": f.get("OddsType", ""),
            "label": f.get("DefaultLabel", ""),
            "template": f.get("DefaultTemplate", ""),
            "values": f.get("StatValues", []),
        })
    return {
        "home": oddspoll.get("HomeTeam", ""),
        "away": oddspoll.get("AwayTeam", ""),
        "facts": facts,
    }


def _extract_h2h(h2h):
    """Extract head-to-head data."""
    if not h2h:
        return None
    summary = h2h.get("summary", [])
    matches = []
    for m in h2h.get("matches", [])[:5]:
        home = m.get("home", {})
        away = m.get("away", {})
        status = m.get("status", {})
        matches.append({
            "home": home.get("name", ""),
            "away": away.get("name", ""),
            "score": status.get("scoreStr", ""),
            "date": status.get("utcTime", m.get("time", {}).get("utcTime", "")),
        })
    return {
        "summary": summary,  # [home_wins, draws, away_wins]
        "matches": matches,
    }


def _extract_events(events_data):
    """Extract match events (goals, cards, subs)."""
    events_list = events_data.get("events", [])
    result = []
    for ev in events_list:
        ev_type = ev.get("type", "")
        if ev_type in ("Goal", "Card", "Substitution"):
            entry = {
                "type": ev_type,
                "time": ev.get("timeStr", ""),
                "player": ev.get("player", {}).get("name", ""),
                "is_home": ev.get("isHome"),
                "home_score": ev.get("homeScore"),
                "away_score": ev.get("awayScore"),
            }
            if ev_type == "Goal":
                entry["assist"] = ev.get("assistStr", "")
            elif ev_type == "Card":
                entry["card"] = ev.get("card", "")
            elif ev_type == "Substitution":
                swap = ev.get("swap", [])
                entry["player_on"] = swap[0].get("name", "") if len(swap) > 0 else ""
                entry["player_off"] = swap[1].get("name", "") if len(swap) > 1 else ""
            result.append(entry)
    return result


def _extract_stats(stats):
    """Extract match statistics."""
    if not stats:
        return None
    periods = stats.get("Periods", {})
    all_stats = periods.get("All", {}).get("stats", [])
    result = []
    for group in all_stats:
        title = group.get("title", "")
        stat_items = []
        for s in group.get("stats", []):
            if s.get("type") == "title":
                continue
            vals = s.get("stats", [])
            stat_items.append({
                "name": s.get("title", ""),
                "home": vals[0] if len(vals) > 0 else None,
                "away": vals[1] if len(vals) > 1 else None,
            })
        result.append({"title": title, "stats": stat_items})
    return result


def _extract_previews(match_facts):
    """Extract preview articles."""
    previews = []
    for key in ["preReview", "postReview"]:
        articles = match_facts.get(key, [])
        if isinstance(articles, list):
            for a in articles:
                previews.append({
                    "title": a.get("title", ""),
                    "source": a.get("source", ""),
                    "url": a.get("shareUrl", ""),
                })
    return previews


def summarize_full_match(data):
    """Convert extracted match data into a comprehensive text summary for AI."""
    if not data:
        return "No match data available."

    lines = []

    # Header
    home = data["home"]["name"]
    away = data["away"]["name"]
    h_score = data["home"]["score"]
    a_score = data["away"]["score"]
    if data["is_live"]:
        lines.append(f"LIVE MATCH: {home} {h_score} - {a_score} {away}")
    elif data["finished"]:
        lines.append(f"RESULT: {home} {h_score} - {a_score} {away}")
    else:
        lines.append(f"UPCOMING: {home} vs {away}")
    lines.append(f"Competition: {data['league']} Round {data['round']}")
    lines.append(f"Date: {data['date']}")

    # Venue
    lines.append(f"Stadium: {data['stadium']}, {data['city']}, {data['country']}")
    if data.get("capacity"):
        lines.append(f"Capacity: {data['capacity']}, Surface: {data['surface']}")

    # Referee
    if data.get("referee"):
        lines.append(f"Referee: {data['referee']} ({data['referee_country']})")

    # TV Channel (filter out generic placeholders)
    tv = data.get("tv_channel", "")
    if tv and "find out where" not in tv.lower() and "streaming info" not in tv.lower() and len(tv) > 5:
        lines.append(f"TV/Broadcast: {tv}")
    else:
        lines.append("TV/Broadcast: Check your local TV listings or FotMob app for broadcast info in your region.")

    # Betting odds
    odds = data.get("odds")
    if odds:
        from odds import format_odds_text
        lines.append(format_odds_text(odds))

    # Poll / Prediction context
    poll = data.get("poll")
    if poll:
        for fact in poll.get("facts", []):
            if fact.get("type") == "1x2":
                template = fact.get("template", "")
                values = fact.get("values", [])
                home_name = data["home"]["name"]
                away_name = data["away"]["name"]
                # Fill template with team names
                filled = template
                for v in values:
                    if v == "home_team":
                        filled = filled.replace("{0}", home_name, 1).replace("{1}", away_name, 1)
                    elif v == "away_team":
                        filled = filled.replace("{0}", away_name, 1).replace("{1}", home_name, 1)
                    else:
                        filled = filled.replace("{" + str(values.index(v)) + "}", str(v), 1)
                lines.append(f"Match prediction context: {filled}")

    # Weather
    w = data.get("weather")
    if w:
        lines.append(f"Weather: {w['temperature']}C, {w['description']}, Humidity {w['humidity']}%, Rain {w['rain_chance']}%")

    # Coaches
    if data.get("home_coach"):
        lines.append(f"{home} coach: {data['home_coach']['name']}")
    if data.get("away_coach"):
        lines.append(f"{away} coach: {data['away_coach']['name']}")

    # Lineups
    for side, key in [(home, "home_lineup"), (away, "away_lineup")]:
        lu = data.get(key, {})
        if lu and lu.get("players"):
            names = [f"#{p['shirt'] or '?'} {p['name']}" for p in lu["players"]]
            lines.append(f"{side} ({lu['formation']}): {', '.join(names)}")

    # Injuries
    for side, key in [(home, "home_injuries"), (away, "away_injuries")]:
        injuries = data.get(key, [])
        if injuries:
            inj_strs = [f"{i['name']} ({i['expected_return']})" for i in injuries]
            lines.append(f"{side} injured/unavailable: {', '.join(inj_strs)}")

    # Insights
    insights = data.get("insights", [])
    if insights:
        lines.append("Match insights:")
        for ins in insights:
            lines.append(f"  - {ins['text']}")

    # Top scorers
    ts = data.get("top_scorers")
    if ts:
        for key in ["homePlayer", "awayPlayer"]:
            p = ts.get(key, {})
            if p:
                lines.append(f"Top scorer: {p['name']} - {p.get('goals',0)} goals, {p.get('assists',0)} assists, xG {p.get('xg','')}, rating {p.get('rating','')}")

    # Team form
    form = data.get("team_form", [])
    if form:
        for i, team_form in enumerate(form):
            side = home if i == 0 else away
            results = [f"{m.get('result','')} {m.get('score','')}" for m in team_form[:5]]
            lines.append(f"{side} form: {', '.join(results)}")

    # H2H
    h2h = data.get("h2h")
    if h2h:
        summary = h2h.get("summary", [])
        if len(summary) == 3:
            lines.append(f"H2H record: {home} {summary[0]}W, {summary[1]}D, {away} {summary[2]}W")
        for m in h2h.get("matches", [])[:3]:
            lines.append(f"  {m['home']} {m['score']} {m['away']} ({m['date'][:10]})")

    # Events (live/finished)
    events = data.get("events", [])
    if events:
        lines.append("Match events:")
        for ev in events:
            if ev["type"] == "Goal":
                lines.append(f"  GOAL {ev['time']}': {ev['player']} ({home if ev.get('is_home') else away}) {ev.get('assist','')}")
            elif ev["type"] == "Card":
                lines.append(f"  CARD {ev['time']}': {ev['player']} ({ev.get('card','')})")
            elif ev["type"] == "Substitution":
                lines.append(f"  SUB {ev['time']}': {ev.get('player_on','')} on, {ev.get('player_off','')} off")

    # Stats
    stats = data.get("stats")
    if stats:
        for group in stats[:2]:
            lines.append(f"{group['title']}:")
            for s in group["stats"]:
                lines.append(f"  {s['name']}: {home} {s['home']} - {s['away']} {away}")

    # Previews
    previews = data.get("previews", [])
    if previews:
        lines.append("Preview articles:")
        for p in previews:
            lines.append(f"  {p['title']} ({p['source']})")

    # Market values
    hv = data.get("home_squad_value")
    av = data.get("away_squad_value")
    if hv and av:
        lines.append(f"Squad market values: {home} EUR {hv:,} vs {away} EUR {av:,}")

    return "\n".join(lines)
