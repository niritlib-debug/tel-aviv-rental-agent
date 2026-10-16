"""Web search tool via the Tavily Search API (https://docs.tavily.com).

Search results are titles + snippets, so extracted fields are best-effort and
listings are marked ``verified=False``. Candidates are kept only if city, rooms
and price can all be read from the text — nothing is guessed.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlsplit

from ..goal import TEL_AVIV_ALIASES, SearchGoal
from ..models import Listing
from .http import PoliteHttp, SourceError

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
DOMAINS = ["yad2.co.il", "madlan.co.il", "homeless.co.il", "komo.co.il", "facebook.com"]

_PRICE_RES = [
    re.compile(r"(?:₪|ש\"ח|שח|NIS|ILS)\s*(\d{1,2}[,.]?\d{3})", re.I),
    re.compile(r"(\d{1,2}[,.]?\d{3})\s*(?:₪|ש\"ח|שח|NIS|ILS|שקל)", re.I),
]
_ROOMS_RES = [
    re.compile(r"(\d+(?:\.\d)?)\s*(?:חדרים|חד'|חד׳|rooms?)", re.I),
    re.compile(r"(?:דירת|דירה)\s*(\d+(?:\.\d)?)\s*(?:חדרים|חד)", re.I),
]
# Listing-page URL patterns only (search/category pages are not listings).
_LISTING_URL_RES = [
    re.compile(r"yad2\.co\.il/realestate/item/"),
    re.compile(r"madlan\.co\.il/listings/"),
    re.compile(r"homeless\.co\.il/.*(?:viewad|adid)", re.I),
    re.compile(r"komo\.co\.il/code/nadlan/details/"),
    re.compile(r"facebook\.com/(?:groups/[^/]+/(?:posts|permalink)|marketplace/item)/"),
]


def extract_price(text: str) -> int | None:
    for rx in _PRICE_RES:
        for m in rx.finditer(text):
            value = int(re.sub(r"[,.]", "", m.group(1)))
            if 1000 <= value <= 50000:  # plausible monthly rent
                return value
    return None


def extract_rooms(text: str) -> float | None:
    for rx in _ROOMS_RES:
        m = rx.search(text)
        if m:
            return float(m.group(1))
    return None


def extract_city(text: str) -> str | None:
    low = text.lower()
    for alias in TEL_AVIV_ALIASES:
        if alias.lower() in low:
            return "תל אביב יפו"
    return None


def is_listing_url(url: str) -> bool:
    return any(rx.search(url) for rx in _LISTING_URL_RES)


def build_query(goal: SearchGoal) -> str:
    return f"דירת {goal.rooms:g} חדרים להשכרה בתל אביב עד {goal.max_price} ש\"ח"


def results_to_listings(results: list[dict]) -> list[Listing]:
    out = []
    for r in results:
        url = (r.get("url") or "").strip()
        if not url or not is_listing_url(url):
            continue
        text = f"{r.get('title', '')} {r.get('content', '')}"
        price, rooms, city = extract_price(text), extract_rooms(text), extract_city(text)
        if price is None or rooms is None or city is None:
            continue
        domain = urlsplit(url).netloc.lower().removeprefix("www.")
        out.append(Listing(
            source=f"web:{domain}",
            source_id=hashlib.sha1(url.encode()).hexdigest()[:16],
            url=url,
            title=(r.get("title") or "").strip()[:200],
            city=city,
            price=price,
            rooms=rooms,
            description=(r.get("content") or "").strip()[:500],
            verified=False,
        ))
    return out


def web_search(goal: SearchGoal, http: PoliteHttp, api_key: str, max_results: int = 20) -> list[Listing]:
    if not api_key:
        raise SourceError("TAVILY_API_KEY is not set")
    payload = {
        "query": build_query(goal),
        "max_results": max_results,
        "include_domains": DOMAINS,
        "search_depth": "basic",
    }
    resp = http.post(TAVILY_URL, json=payload, headers={"Authorization": f"Bearer {api_key}"}, check_robots=False)
    if resp.status_code in (401, 403):
        raise SourceError(f"Tavily rejected the API key (HTTP {resp.status_code})")
    if resp.status_code != 200:
        raise SourceError(f"Tavily returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        results = resp.json().get("results", [])
    except ValueError as exc:
        raise SourceError("Tavily returned invalid JSON") from exc
    listings = results_to_listings(results)
    log.info("web_search: %d results, %d usable listing candidates", len(results), len(listings))
    return listings
