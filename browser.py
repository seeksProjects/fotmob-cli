"""Browser-based data fetcher for Turnstile-protected FotMob endpoints.

Uses seleniumbase with undetected Chrome to load FotMob pages and extract
data from __NEXT_DATA__ (server-side rendered JSON).

Features:
- Auto-recovery: restarts browser after failures
- Timeout handling: catches and recovers from timeouts
- Graceful degradation: returns None instead of crashing
"""

import json
import logging
import atexit

logger = logging.getLogger(__name__)

_browser_instance = None
_sb_context = None
_failure_count = 0
_MAX_FAILURES = 2  # Restart browser after this many consecutive failures


def _get_browser():
    """Get or create a persistent browser instance. Auto-restarts after failures."""
    global _browser_instance, _sb_context, _failure_count

    if _failure_count >= _MAX_FAILURES:
        logger.info("Browser hit %d failures, restarting...", _failure_count)
        _kill_browser()
        _failure_count = 0

    if _browser_instance is None:
        try:
            from seleniumbase import SB
            _sb_context = SB(uc=True, headless=True)
            _browser_instance = _sb_context.__enter__()
            atexit.register(_cleanup_browser)
        except Exception as e:
            logger.error("Failed to start browser: %s", e)
            return None
    return _browser_instance


def _kill_browser():
    """Force kill the browser instance."""
    global _browser_instance, _sb_context
    if _sb_context is not None:
        try:
            _sb_context.__exit__(None, None, None)
        except Exception:
            pass
    _browser_instance = None
    _sb_context = None


def _cleanup_browser():
    """Clean up browser on exit."""
    _kill_browser()


def _mark_success():
    """Reset failure count on success."""
    global _failure_count
    _failure_count = 0


def _mark_failure():
    """Increment failure count."""
    global _failure_count
    _failure_count += 1


def _safe_browser_call(func):
    """Decorator that catches browser errors and marks failures for recovery."""
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            if result is not None:
                _mark_success()
            return result
        except Exception as e:
            _mark_failure()
            logger.warning("Browser call failed: %s", e)
            return None
    return wrapper


def _extract_next_data(sb):
    """Extract __NEXT_DATA__ JSON from the current page."""
    try:
        raw = sb.execute_script(
            'var el = document.getElementById("__NEXT_DATA__");'
            'return el ? el.textContent : null;'
        )
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug("Failed to extract __NEXT_DATA__: %s", e)
    return None


@_safe_browser_call
def get_match_details(match_id, match_url=None):
    """Fetch full match details via browser page load.

    Returns dict (pageProps) or None if failed.
    """
    sb = _get_browser()
    if sb is None:
        return None

    if match_url:
        url = f"https://www.fotmob.com{match_url}" if match_url.startswith("/") else match_url
    else:
        url = f"https://www.fotmob.com/matches/{match_id}"

    sb.open(url)
    sb.sleep(4)

    data = _extract_next_data(sb)
    if data:
        page_props = data.get("props", {}).get("pageProps", {})
        if "general" in page_props:
            # Extract TV info from rendered DOM
            try:
                from match_data import extract_tv_and_odds_from_browser
                tv_odds = extract_tv_and_odds_from_browser(sb)
                page_props["_browser_tv_channel"] = tv_odds.get("tv", "")
            except Exception:
                pass
            return page_props

        # Retry once — page might not have loaded fully
        sb.sleep(3)
        data = _extract_next_data(sb)
        if data:
            page_props = data.get("props", {}).get("pageProps", {})
            if "general" in page_props:
                return page_props

    return None


@_safe_browser_call
def get_match_commentary(match_id, match_url=None, limit=10):
    """Fetch live commentary from a match page.

    Returns list of dicts with 'minute' and 'text' keys, or empty list.
    """
    sb = _get_browser()
    if sb is None:
        return []

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
                tab.click(); break;
            }
        }
    """)
    sb.sleep(3)

    js = """
    var items = [];
    var els = document.querySelectorAll("[class*='ticker'], [class*='Ticker']");
    for (var el of els) {
        var text = el.textContent.trim().replace(/[\\u200e\\u200f]/g, '');
        if (text.length > 10 && text.length < 400) {
            var m = text.match(/^(\\d+(?:\\+\\d+)?)['\\u2032\\u2019]/);
            if (m) {
                var clean = text.replace(/^\\d+(?:\\+\\d+)?['\\u2032\\u2019]/, '').trim();
                var parts = clean.split(/(?:Goalkeeper|Defender|Left-back|Right-back|Center-back|Midfielder|Central Midfielder|Defensive Midfielder|Attacking Midfielder|Winger|Left Winger|Right Winger|Striker|Forward)/);
                var description = parts.length > 1 ? parts[parts.length - 1].trim() : clean;
                if (!description) description = clean;
                items.push({minute: m[1], text: description});
            }
        }
    }
    return JSON.stringify(items);
    """
    result = json.loads(sb.execute_script(js))
    return result[:limit] if result else []


@_safe_browser_call
def get_player_data(player_id, player_url=None):
    """Fetch full player data via browser page load.

    Returns dict or None.
    """
    sb = _get_browser()
    if sb is None:
        return None

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
