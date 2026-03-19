"""Natural Language Processing layer for FotMob CLI.

Multi-layered approach (same pattern as currency_conversion project):
1. Exact intent matching against comprehensive phrase dictionary
2. Noise word stripping (remove filler like "what is", "show me", "please")
3. Fuzzy matching with thefuzz (handle typos like "arsnal", "premire league")
4. Entity extraction (team names, league names, player names)
"""

import re
from thefuzz import fuzz

# =============================================================================
# INTENT DEFINITIONS
# =============================================================================
# Each intent maps to an action the CLI can perform.

INTENTS = {
    "standings",        # League table / standings
    "fixtures",         # Match schedule / results (league-level)
    "team_fixtures",    # Team match history / recent matches
    "live",             # Live match tracking
    "team",             # Team overview / info
    "form",             # Team recent form
    "squad",            # Team roster / players
    "last_match",       # Last match result
    "next_match",       # Next upcoming match
    "top_scorers",      # League top scorers / stats
    "player",           # Player profile / stats
    "match",            # Match details (events, xG, lineups)
    "transfers",        # Transfer news
    "news",             # Football news
    "search",           # Generic search
    "leagues",          # List available leagues
    "help",             # Show help
}

# =============================================================================
# PHRASE → INTENT MAPPING
# Comprehensive dictionary of natural language phrases humans might use.
# Sorted by intent category. Includes slang, misspellings, variations.
# =============================================================================

PHRASE_INTENTS = {
    # --- STANDINGS ---
    "standings": "standings",
    "standing": "standings",
    "table": "standings",
    "league table": "standings",
    "league standings": "standings",
    "ranking": "standings",
    "rankings": "standings",
    "position": "standings",
    "positions": "standings",
    "league position": "standings",
    "league positions": "standings",
    "who is top": "standings",
    "who is first": "standings",
    "who is leading": "standings",
    "who is winning the league": "standings",
    "who leads": "standings",
    "league leaders": "standings",
    "points table": "standings",
    "classification": "standings",
    "classement": "standings",
    "tabla": "standings",
    "tabelle": "standings",
    "classifica": "standings",

    # --- FIXTURES (league-level) ---
    "fixtures": "fixtures",
    "fixture": "fixtures",
    "schedule": "fixtures",
    "gameweek": "fixtures",
    "matchday": "fixtures",
    "match day": "fixtures",
    "game week": "fixtures",
    "this week": "fixtures",
    "this weekend": "fixtures",
    "weekend matches": "fixtures",
    "weekend games": "fixtures",
    "today matches": "fixtures",
    "today games": "fixtures",
    "tonight": "fixtures",
    "tomorrow matches": "fixtures",
    "who plays today": "fixtures",
    "who is playing": "fixtures",
    "who plays this weekend": "fixtures",
    "what matches are on": "fixtures",
    "what games are on": "fixtures",

    # --- TEAM FIXTURES (team-level match history) ---
    "last matches": "team_fixtures",
    "last games": "team_fixtures",
    "recent matches": "team_fixtures",
    "recent games": "team_fixtures",
    "recent results": "team_fixtures",
    "match history": "team_fixtures",
    "game history": "team_fixtures",
    "past matches": "team_fixtures",
    "past games": "team_fixtures",
    "past results": "team_fixtures",
    "all matches": "team_fixtures",
    "all games": "team_fixtures",
    "matches played": "team_fixtures",

    # --- LIVE TRACKING ---
    "live": "live",
    "live score": "live",
    "live scores": "live",
    "live match": "live",
    "live update": "live",
    "live updates": "live",
    "what is happening": "live",
    "whats happening": "live",
    "what's happening": "live",
    "track": "live",
    "track live": "live",
    "follow": "live",
    "follow live": "live",
    "watch": "live",
    "score update": "live",
    "score updates": "live",
    "current score": "live",
    "live commentary": "live",
    "match update": "live",
    "match updates": "live",
    "games played": "team_fixtures",

    # --- TEAM ---
    "team": "team",
    "club": "team",
    "overview": "team",
    "info": "team",
    "about": "team",
    "tell me about": "team",
    "information": "team",

    # --- FORM ---
    "form": "form",
    "current form": "form",
    "recent form": "form",
    "streak": "form",
    "run": "form",
    "how are they doing": "form",
    "how is": "form",
    "how are": "form",

    # --- SQUAD ---
    "squad": "squad",
    "roster": "squad",
    "players": "squad",
    "lineup": "squad",
    "lineups": "squad",
    "line up": "squad",
    "team sheet": "squad",
    "who plays for": "squad",
    "list players": "squad",
    "name the players": "squad",
    "player list": "squad",
    "squad list": "squad",
    "members": "squad",
    "team members": "squad",

    # --- LAST MATCH ---
    "last match": "last_match",
    "last game": "last_match",
    "last result": "last_match",
    "previous match": "last_match",
    "previous game": "last_match",
    "previous result": "last_match",
    "latest result": "last_match",
    "latest match": "last_match",
    "latest score": "last_match",
    "most recent match": "last_match",
    "most recent game": "last_match",
    "did they win": "last_match",
    "did they lose": "last_match",
    "did they draw": "last_match",

    # --- LAST MATCH (verb patterns — "did X win/lose") ---
    "lose": "last_match",
    "lost": "last_match",
    "won": "last_match",
    "win": "last_match",
    "beat": "last_match",
    "beaten": "last_match",
    "drew": "last_match",
    "defeated": "last_match",

    # --- NEXT MATCH ---
    "next match": "next_match",
    "next game": "next_match",
    "next fixture": "next_match",
    "upcoming match": "next_match",
    "upcoming game": "next_match",
    "upcoming fixture": "next_match",
    "when do they play": "next_match",
    "when do they play next": "next_match",
    "when is the next": "next_match",
    "who do they play next": "next_match",
    "next opponent": "next_match",
    "who are they playing": "next_match",
    "when is the game": "next_match",

    # --- TOP SCORERS ---
    "top scorer": "top_scorers",
    "top scorers": "top_scorers",
    "scorers": "top_scorers",
    "goal scorers": "top_scorers",
    "golden boot": "top_scorers",
    "top goals": "top_scorers",
    "most goals": "top_scorers",
    "leading scorer": "top_scorers",
    "leading scorers": "top_scorers",
    "top assists": "top_scorers",
    "most assists": "top_scorers",
    "assist leaders": "top_scorers",
    "top ratings": "top_scorers",
    "best players": "top_scorers",
    "best rated": "top_scorers",
    "top rated": "top_scorers",
    "clean sheets": "top_scorers",
    "most clean sheets": "top_scorers",
    "yellow cards": "top_scorers",
    "red cards": "top_scorers",
    "most cards": "top_scorers",

    # --- PLAYER ---
    "stats": "player",
    "statistics": "player",
    "stat": "player",
    "profile": "player",
    "player stats": "player",
    "player profile": "player",
    "player info": "player",
    "how many goals": "player",
    "how many assists": "player",
    "season stats": "player",
    "career": "player",

    # --- MATCH DETAILS ---
    "match details": "match",
    "match detail": "match",
    "match info": "match",
    "xg": "match",
    "expected goals": "match",
    "who scored": "match",
    "goals scored": "match",
    "match events": "match",
    "match stats": "match",
    "match statistics": "match",
    "match lineups": "match",
    "match lineup": "match",

    # --- TRANSFERS ---
    "transfer": "transfers",
    "transfers": "transfers",
    "signing": "transfers",
    "signings": "transfers",
    "transfer news": "transfers",
    "transfer rumors": "transfers",
    "transfer rumours": "transfers",
    "who signed": "transfers",
    "new signing": "transfers",
    "new signings": "transfers",
    "deals": "transfers",
    "bought": "transfers",
    "sold": "transfers",
    "latest transfers": "transfers",
    "recent transfers": "transfers",
    "transfer window": "transfers",
    "market": "transfers",
    "transfer market": "transfers",

    # --- NEWS ---
    "news": "news",
    "headlines": "news",
    "latest news": "news",
    "football news": "news",
    "soccer news": "news",
    "articles": "news",
    "what happened": "news",
    "whats new": "news",
    "what's new": "news",
    "breaking": "news",
    "breaking news": "news",
    "updates": "news",

    # --- SEARCH ---
    "search": "search",
    "find": "search",
    "look up": "search",
    "lookup": "search",

    # --- LEAGUES ---
    "leagues": "leagues",
    "all leagues": "leagues",
    "available leagues": "leagues",
    "list leagues": "leagues",
    "which leagues": "leagues",
    "what leagues": "leagues",
    "league list": "leagues",
    "competitions": "leagues",

    # --- HELP ---
    "help": "help",
    "commands": "help",
    "what can you do": "help",
    "how to use": "help",
    "how does this work": "help",
    "usage": "help",
    "options": "help",
    "guide": "help",
    "tutorial": "help",
}


# =============================================================================
# LEAGUE NAME DICTIONARY
# Comprehensive mapping including abbreviations, nicknames, misspellings.
# =============================================================================

LEAGUE_DICT = {
    # Premier League
    "premier league": 47, "pl": 47, "epl": 47,
    "english premier league": 47, "english league": 47,
    "prem": 47, "premiership": 47, "barclays": 47,
    "premire league": 47, "premier legue": 47, "premier leage": 47,
    "premeir league": 47, "primier league": 47,

    # La Liga
    "la liga": 87, "laliga": 87, "spanish league": 87,
    "liga": 87, "liga espanola": 87, "primera division": 87,
    "la lига": 87, "la liag": 87,

    # Bundesliga
    "bundesliga": 54, "german league": 54,
    "bundes": 54, "bundesliga 1": 54,
    "bundeslgia": 54, "budesliga": 54,

    # Serie A
    "serie a": 55, "seriea": 55, "italian league": 55,
    "seria a": 55, "calcio": 55, "serie a tim": 55,

    # Ligue 1
    "ligue 1": 53, "ligue1": 53, "french league": 53,
    "ligue one": 53, "ligue un": 53, "liga 1 france": 53,
    "legue 1": 53,

    # Champions League
    "champions league": 42, "ucl": 42, "cl": 42,
    "champions": 42, "uefa champions league": 42,
    "championsleague": 42, "chamions league": 42,
    "champion league": 42, "champions legue": 42,

    # Europa League
    "europa league": 73, "uel": 73,
    "europa": 73, "uefa europa league": 73,
    "europe league": 73, "europa legue": 73,

    # Eredivisie
    "eredivisie": 57, "dutch league": 57,
    "netherlands league": 57, "holland league": 57,
    "eredivise": 57, "eridivisie": 57,

    # MLS
    "mls": 130, "major league soccer": 130,
    "american league": 130, "us league": 130,

    # Others
    "world cup": 77, "fifa world cup": 77,
    "fa cup": 132, "facup": 132, "english cup": 132,
    "euro": 50, "euros": 50, "european championship": 50,
    "copa america": 68, "copa": 68,
    "league cup": 133, "efl cup": 133, "carabao cup": 133,
    "conference league": 10419, "uecl": 10419,
    "scottish premiership": 62, "spfl": 62, "scottish league": 62,
    "liga portugal": 61, "portuguese league": 61, "primeira liga": 61,
    "super lig": 71, "turkish league": 71, "turkish super league": 71,
    "saudi league": 10562, "saudi pro league": 10562, "roshn": 10562,
}


# =============================================================================
# NOISE WORDS
# Words to strip from queries to extract entity names.
# =============================================================================

NOISE_WORDS = {
    # Question starters
    "what", "who", "when", "where", "how", "why", "which",
    "is", "are", "was", "were", "will", "would", "could", "can", "should",
    "do", "does", "did", "has", "have", "had",

    # Articles & prepositions
    "the", "a", "an", "of", "for", "in", "on", "at", "to", "from",
    "with", "by", "as",

    # Conjunctions
    "and", "or", "but", "nor",

    # Filler / politeness
    "please", "show", "me", "give", "get", "tell", "provide", "display",
    "list", "name",

    # Pronouns / possessives
    "their", "its", "his", "her", "they", "them", "my", "our",
    "i", "we", "you",

    # Common verbs (non-intent)
    "want", "need", "like", "know", "see", "check",

    # Misc
    "currently", "right", "now", "today", "current",
    "some", "any", "all", "about",
}

# Words that indicate match result queries — strip these to find team name
RESULT_NOISE = {
    "did", "lose", "lost", "won", "win", "beat", "beaten", "draw", "drew",
    "defeated", "they", "their", "last", "match", "game", "previous",
    "result", "latest", "recent", "most", "?",
}

# Words that indicate squad queries — strip these to find team name
SQUAD_NOISE = {
    "squad", "roster", "players", "lineup", "lineups", "line", "up",
    "team", "sheet", "who", "plays", "for", "list", "name", "members",
    "of",
}

# Words that indicate form queries
FORM_NOISE = {
    "form", "current", "recent", "streak", "run", "how", "doing",
    "performing", "they",
}

# Words that indicate next match queries
NEXT_NOISE = {
    "next", "match", "game", "fixture", "upcoming", "when", "play",
    "opponent", "playing", "who", "do", "they", "is", "the", "are",
}


# =============================================================================
# CORE NLP FUNCTIONS
# =============================================================================

FUZZY_THRESHOLD = 70  # Minimum similarity score for fuzzy match


def detect_intent(query):
    """Detect the user's intent from their query.

    Returns (intent, confidence, matched_phrase) or (None, 0, None).

    Strategy:
    1. Exact phrase match (longest match wins)
    2. Fuzzy match against phrase dictionary
    """
    q = query.lower().strip()

    # Step 1: Exact match — longest phrase first
    best_match = None
    best_len = 0
    for phrase, intent in sorted(PHRASE_INTENTS.items(), key=lambda x: -len(x[0])):
        if phrase in q and len(phrase) > best_len:
            best_match = (intent, 100, phrase)
            best_len = len(phrase)

    if best_match:
        return best_match

    # Step 2: Fuzzy match — check each word/bigram against phrases
    words = q.split()
    # Generate n-grams (1, 2, 3 words)
    ngrams = []
    for n in range(1, min(4, len(words) + 1)):
        for i in range(len(words) - n + 1):
            ngrams.append(" ".join(words[i:i + n]))

    best_score = 0
    best_fuzzy = None
    for ngram in ngrams:
        for phrase, intent in PHRASE_INTENTS.items():
            score = fuzz.ratio(ngram, phrase)
            if score > best_score and score >= FUZZY_THRESHOLD:
                best_score = score
                best_fuzzy = (intent, score, phrase)

    if best_fuzzy:
        return best_fuzzy

    return None, 0, None


def extract_league(query):
    """Extract a league from the query.

    Returns (league_id, league_name, remaining_query) or (None, None, query).

    Strategy:
    1. Exact phrase match (longest first)
    2. Fuzzy match against league dictionary
    """
    q = query.lower().strip()

    # Step 1: Exact match (longest first for specificity)
    best_match = None
    best_len = 0
    for name, lid in sorted(LEAGUE_DICT.items(), key=lambda x: -len(x[0])):
        pattern = r'(?:^|\s)' + re.escape(name) + r'(?:\s|$)'
        if re.search(pattern, q) and len(name) > best_len:
            remaining = re.sub(pattern, " ", q).strip()
            best_match = (lid, name, remaining)
            best_len = len(name)

    if best_match:
        return best_match

    # Step 2: Fuzzy match (check words and bigrams)
    words = q.split()
    ngrams = []
    for n in range(1, min(4, len(words) + 1)):
        for i in range(len(words) - n + 1):
            ngrams.append((" ".join(words[i:i + n]), i, i + n))

    best_score = 0
    best_fuzzy = None
    for ngram, start, end in ngrams:
        for name, lid in LEAGUE_DICT.items():
            if len(name) <= 2:
                # Short codes need exact match, not fuzzy
                continue
            score = fuzz.ratio(ngram, name)
            if score > best_score and score >= FUZZY_THRESHOLD:
                remaining_words = words[:start] + words[end:]
                best_score = score
                best_fuzzy = (lid, name, " ".join(remaining_words).strip())

    if best_fuzzy:
        return best_fuzzy

    return None, None, q


def extract_entity(query, noise_set=None):
    """Extract the main entity (team/player name) from a query.

    Removes noise words and intent phrases to isolate the entity name.
    """
    if noise_set is None:
        noise_set = NOISE_WORDS

    words = query.lower().strip().split()
    remaining = [w for w in words if w not in noise_set]
    return " ".join(remaining).strip()


def extract_round_number(query):
    """Extract a round/gameweek number from the query."""
    match = re.search(r'(?:round|gameweek|matchday|gw|week)\s*(\d+)', query.lower())
    if match:
        return match.group(1)
    # Also try just "round X" at end
    match = re.search(r'(\d+)$', query.strip())
    if match:
        return match.group(1)
    return None


def fuzzy_match_league(text):
    """Try to fuzzy match a string to a league name. Returns league_id or None."""
    text = text.lower().strip()
    if not text:
        return None

    best_score = 0
    best_id = None
    for name, lid in LEAGUE_DICT.items():
        if len(name) <= 2:
            continue
        score = fuzz.ratio(text, name)
        if score > best_score and score >= FUZZY_THRESHOLD:
            best_score = score
            best_id = lid

    return best_id
