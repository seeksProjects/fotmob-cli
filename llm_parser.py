"""LLM-powered query parser with fallback chain: Gemini → Groq → keyword NLP.

Sends the user's natural language query to an LLM with a system prompt
that instructs it to return structured JSON with the intent and entities.
"""

import json
import logging

from config import GEMINI_API_KEY as GEMINI_KEY, GROQ_API_KEY as GROQ_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a football CLI query parser. Your ONLY job is to parse user queries into structured JSON.

Available actions and their parameters:
- standings: Show league table. Params: {league: "premier league"}
- fixtures: Show league match schedule. Params: {league: "ucl", round: 5} (round is optional)
- team: Show team overview/info/form. Params: {team: "Arsenal"}
- team_fixtures: Show a team's recent/past matches. Params: {team: "Arsenal", limit: 5}
- squad: Show team roster/players. Params: {team: "Barcelona"}
- last_match: Show a team's last match result. Params: {team: "PSG"}
- next_match: Show a team's next upcoming match. Params: {team: "Real Madrid"}
- top_scorers: Show league stat leaders. Params: {league: "pl", stat: "goals"} (stat can be: goals, assists, rating, clean sheets, yellow cards, red cards)
- player: Show player stats/profile. Params: {player: "Haaland"}
- transfers: Show transfer news. Params: {team: "Arsenal"} (team is optional — omit for global transfers)
- news: Show football headlines. Params: {}
- search: Search for anything. Params: {query: "Messi"}
- leagues: List available leagues. Params: {}
- live: Track live match updates. Params: {team: "Arsenal"} or {league: "pl"}
- help: Show help. Params: {}

IMPORTANT RULES:
- Fix typos: "arsnal" → "Arsenal", "premire league" → "premier league"
- Understand context: "haaland man city when?" → player action for Haaland (transfer history is in player profile)
- "2 days ago champions result" → fixtures action for champions league
- "who is top of la liga" → standings for la liga
- "did chelsea lose" → last_match for Chelsea
- "give me ars last 5 matches" → team_fixtures for Arsenal, limit 5
- "what is happening in X vs Y" → live for the team
- Short queries like "arsenal" → team action
- Short queries like "pl" or "premier league" → standings action
- "messi" or "haaland" (just a name) → player action if it's clearly a player, otherwise search
- "live arsenal" or "track arsenal" → live action

RESPOND WITH ONLY valid JSON. No markdown, no explanation. Example:
{"action": "team_fixtures", "params": {"team": "Arsenal", "limit": 5}}
{"action": "standings", "params": {"league": "premier league"}}
{"action": "player", "params": {"player": "Haaland"}}
{"action": "last_match", "params": {"team": "PSG"}}
{"action": "news", "params": {}}"""


# =============================================================================
# Provider state tracking
# =============================================================================

_gemini_client = None
_groq_client = None
_gemini_available = None   # None = untested, True/False = tested
_groq_available = None     # None = untested, True/False = tested
_active_provider = None    # Which provider is currently working


def _clean_llm_response(text):
    """Clean LLM response text and parse JSON."""
    text = text.strip()
    # Remove markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])  # Remove first line (```json)
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


# =============================================================================
# GEMINI
# =============================================================================

def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_KEY)
    return _gemini_client


def _try_gemini(query):
    global _gemini_available
    if _gemini_available is False:
        return None
    try:
        client = _get_gemini()
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=f"{SYSTEM_PROMPT}\n\nUser query: {query}",
        )
        result = _clean_llm_response(response.text)
        _gemini_available = True
        return result
    except json.JSONDecodeError:
        logger.debug("Gemini returned non-JSON response")
        _gemini_available = True
        return None
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "403" in err or "401" in err:
            logger.debug("Gemini unavailable: %s", err)
            _gemini_available = False
        else:
            logger.debug("Gemini error: %s", err)
        return None


# =============================================================================
# GROQ
# =============================================================================

def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_KEY)
    return _groq_client


def _try_groq(query):
    global _groq_available
    if _groq_available is False:
        return None
    if not GROQ_KEY:
        _groq_available = False
        return None
    try:
        client = _get_groq()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = response.choices[0].message.content
        result = _clean_llm_response(text)
        _groq_available = True
        return result
    except json.JSONDecodeError:
        logger.debug("Groq returned non-JSON response")
        _groq_available = True
        return None
    except Exception as e:
        err = str(e)
        if "429" in err or "rate" in err.lower():
            logger.debug("Groq rate-limited: %s", err)
            # Groq rate limit — temporary, don't permanently disable
            return None
        if "401" in err or "403" in err or "invalid" in err.lower():
            logger.debug("Groq unavailable: %s", err)
            _groq_available = False
        else:
            logger.debug("Groq error: %s", err)
        return None


# =============================================================================
# PUBLIC API
# =============================================================================

def parse_with_llm(query):
    """Parse a user query using the LLM fallback chain: Gemini → Groq.

    Returns a dict like {"action": "team", "params": {"team": "Arsenal"}}
    or None if all LLMs are unavailable.
    """
    global _active_provider

    # Try Gemini first
    result = _try_gemini(query)
    if result:
        _active_provider = "Gemini"
        return result

    # Try Groq as fallback
    result = _try_groq(query)
    if result:
        _active_provider = "Groq"
        return result

    _active_provider = None
    return None


def is_available():
    """Check if any LLM provider is currently available."""
    return _gemini_available is not False or _groq_available is not False


def get_active_provider():
    """Return the name of the currently active LLM provider, or None."""
    if _gemini_available is True:
        return "Gemini"
    if _groq_available is True:
        return "Groq"
    if _gemini_available is None or _groq_available is None:
        return "untested"
    return None


def get_status_text():
    """Return a rich-formatted status string for the startup banner."""
    # Probe both providers
    parse_with_llm("test")

    if _gemini_available:
        return "[green]Gemini AI active[/green]"
    elif _groq_available:
        return "[green]Groq AI active (Llama 3.3 70B)[/green]"
    else:
        parts = []
        if _gemini_available is False:
            parts.append("Gemini: quota exhausted")
        if _groq_available is False:
            parts.append("Groq: " + ("no API key" if not GROQ_KEY else "unavailable"))
        return "[yellow]LLMs unavailable (" + ", ".join(parts) + "), using keyword NLP[/yellow]"


def set_groq_key(key):
    """Set the Groq API key at runtime."""
    global GROQ_KEY, _groq_client, _groq_available
    GROQ_KEY = key
    _groq_client = None
    _groq_available = None
