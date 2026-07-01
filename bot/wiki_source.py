"""Russian Wikipedia lookup for the agronomist assistant (species biology/morphology).

A licence-clean neutral source per LICENSING.md §3 (Википедия по соответствующим видам).
Wikipedia text is CC BY-SA — founder-approved (LICENSING.md §6, v1.2). We inject a short
intro extract as GROUNDING and always hand the model the article URL so it can attribute;
the model paraphrases facts (facts aren't copyrightable) rather than reproducing the text.

Live lookup via the MediaWiki API (no auth), with a small in-process cache so repeat
species don't re-hit the network. Best-effort: any failure returns None and the answer
proceeds on its other grounding.
"""
import logging

import requests

logger = logging.getLogger(__name__)

_API = "https://ru.wikipedia.org/w/api.php"
# Wikimedia asks for a descriptive User-Agent identifying the app + contact.
_HEADERS = {"User-Agent": "FlagleafBot/1.0 (https://flagleaf.ru; agronomy assistant)"}
_CACHE: dict[str, tuple | None] = {}      # term(lower) → (extract, url) | None
_CACHE_MAX = 512


def _search_title(term: str) -> str | None:
    r = requests.get(_API, params={
        "action": "query", "list": "search", "srsearch": term,
        "srlimit": 1, "srnamespace": 0, "format": "json"},
        headers=_HEADERS, timeout=6)
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def _intro_extract(title: str):
    r = requests.get(_API, params={
        "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
        "redirects": 1, "titles": title, "format": "json"},
        headers=_HEADERS, timeout=6)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    if not pages:
        return None, None
    page = next(iter(pages.values()))
    return page.get("extract"), page.get("title")


def lookup(term: str):
    """Return (extract, url) for the RU Wikipedia article best matching `term`, or None."""
    if not term:
        return None
    key = term.strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    result = None
    try:
        title = _search_title(term)
        if title:
            extract, real_title = _intro_extract(title)
            if extract and len(extract) >= 40:
                url = "https://ru.wikipedia.org/wiki/" + (real_title or title).replace(" ", "_")
                result = (extract[:900].strip(), url)
    except Exception:
        logger.exception("wikipedia lookup failed for %r", term)
        return None                       # don't cache transient failures
    if len(_CACHE) < _CACHE_MAX:
        _CACHE[key] = result
    return result
