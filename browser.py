"""Browser-based data fetcher for Turnstile-protected FotMob endpoints.

Uses seleniumbase with undetected Chrome to load FotMob pages and extract
data from __NEXT_DATA__ (server-side rendered JSON). This bypasses
Cloudflare Turnstile which blocks direct API calls to:
- /api/matchDetails
- /api/playerData
"""

import json
import logging
import atexit

logger = logging.getLogger(__name__)
from seleniumbase import SB

_browser_instance = None
_sb_context = None


def _get_browser():
    """Get or create a persistent browser instance."""
    global _browser_instance, _sb_context
    if _browser_instance is None:
        _sb_context = SB(uc=True, headless=True)
        _browser_instance = _sb_context.__enter__()
        atexit.register(_cleanup_browser)
    return _browser_instance


def _cleanup_browser():
    """Clean up browser on exit."""
    global _browser_instance, _sb_context
    if _sb_context is not None:
        try:
            _sb_context.__exit__(None, None, None)
        except Exception as e:
            logger.debug("Browser cleanup error: %s", e)
        _browser_instance = None
        _sb_context = None


def _extract_next_data(sb):
    """Extract __NEXT_DATA__ JSON from the current page."""
    raw = sb.execute_script(
        'var el = document.getElementById("__NEXT_DATA__");'
        'return el ? el.textContent : null;'
    )
    if raw:
        return json.loads(raw)
    return None


def get_match_details(match_id, match_url=None):
    """Fetch full match details via browser page load.

    Parameters
    ----------
    match_id : str or int
        The FotMob match ID.
    match_url : str, optional
        Full page URL. If not provided, uses a generic URL pattern.

    Returns
    -------
    dict
        The match data from pageProps, or None if failed.
    """
    sb = _get_browser()

    if match_url:
        url = f"https://www.fotmob.com{match_url}" if match_url.startswith("/") else match_url
    else:
        url = f"https://www.fotmob.com/matches/{match_id}"

    sb.open(url)
    sb.sleep(3)

    # If redirected to a slug URL, the page should have loaded
    # But if it landed on a generic page, try navigating to the final URL
    final_url = sb.get_current_url()
    if f"#{match_id}" not in final_url and match_id not in final_url.split("/")[-1]:
        sb.sleep(2)

    data = _extract_next_data(sb)
    if data:
        page_props = data.get("props", {}).get("pageProps", {})
        # Check if this is actually match data (has 'general' key)
        if "general" in page_props:
            # Extract TV and odds from rendered DOM
            try:
                from match_data import extract_tv_and_odds_from_browser
                tv_odds = extract_tv_and_odds_from_browser(sb)
                page_props["_browser_tv_channel"] = tv_odds.get("tv", "")
                page_props["_browser_odds_provider"] = tv_odds.get("oddsProvider", "")
            except Exception:
                pass
            return page_props
        # Might need to reload with the slug URL
        # Try getting the redirect URL and reload
        sb.sleep(3)
        data = _extract_next_data(sb)
        if data:
            return data.get("props", {}).get("pageProps", {})
    return None


def get_match_commentary(match_id, match_url=None, limit=10):
    """Fetch live commentary from a match page.

    Clicks the Commentary tab and extracts minute-by-minute text entries.
    Returns a list of dicts with 'minute' and 'text' keys (newest first).
    """
    sb = _get_browser()

    if match_url:
        url = f"https://www.fotmob.com{match_url}" if match_url.startswith("/") else match_url
    else:
        url = f"https://www.fotmob.com/matches/{match_id}"

    sb.open(url)
    sb.sleep(4)

    # Click Commentary tab
    sb.execute_script("""
        var tabs = document.querySelectorAll("a, button, span");
        for (var tab of tabs) {
            if (tab.textContent.trim().toLowerCase() === "commentary") {
                tab.click();
                break;
            }
        }
    """)
    sb.sleep(3)

    # Extract commentary entries
    js = """
    var items = [];
    var els = document.querySelectorAll("[class*='ticker'], [class*='Ticker']");
    for (var el of els) {
        var text = el.textContent.trim().replace(/[\\u200e\\u200f]/g, '');
        if (text.length > 10 && text.length < 400) {
            var m = text.match(/^(\\d+(?:\\+\\d+)?)['\\u2032\\u2019]/);
            if (m) {
                // Clean up: remove shirt numbers and position labels stuck to player names
                var clean = text.replace(/^\\d+(?:\\+\\d+)?['\\u2032\\u2019]/, '').trim();
                // Remove patterns like "7Cristian PavónRight-back" → just keep the description
                var descMatch = clean.match(/(?:.*?(?:Goalkeeper|Defender|Left-back|Right-back|Center-back|Midfielder|Central Midfielder|Defensive Midfielder|Attacking Midfielder|Winger|Left Winger|Right Winger|Striker|Forward))?(.+)/);
                var description = descMatch ? descMatch[1].trim() : clean;
                // If description starts with a number+name+position, find the actual commentary
                var parts = clean.split(/(?:Goalkeeper|Defender|Left-back|Right-back|Center-back|Midfielder|Central Midfielder|Defensive Midfielder|Attacking Midfielder|Winger|Left Winger|Right Winger|Striker|Forward)/);
                if (parts.length > 1) {
                    description = parts[parts.length - 1].trim();
                }
                if (!description) description = clean;
                items.push({minute: m[1], text: description});
            }
        }
    }
    return JSON.stringify(items);
    """
    try:
        result = json.loads(sb.execute_script(js))
        return result[:limit]
    except Exception:
        return []


def get_player_data(player_id, player_url=None):
    """Fetch full player data via browser page load.

    Parameters
    ----------
    player_id : str or int
        The FotMob player ID.
    player_url : str, optional
        Full page URL. If not provided, uses a generic URL pattern.

    Returns
    -------
    dict
        The player data, or None if failed.
    """
    sb = _get_browser()

    if player_url:
        url = f"https://www.fotmob.com{player_url}" if player_url.startswith("/") else player_url
    else:
        url = f"https://www.fotmob.com/players/{player_id}/overview"

    sb.open(url)
    sb.sleep(4)

    data = _extract_next_data(sb)
    if data:
        page_props = data.get("props", {}).get("pageProps", {})
        return page_props.get("data", page_props)
    return None
