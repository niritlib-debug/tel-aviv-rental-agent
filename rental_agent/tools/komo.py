"""Komo (www.komo.co.il) rentals tool — verified, server-rendered listing pages.

Only page 1 of results is public; further pages redirect to a login page, which
this tool does not attempt.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..goal import SearchGoal
from ..models import Listing
from .http import PoliteHttp, SourceError, looks_like_bot_challenge

log = logging.getLogger(__name__)

BASE_URL = "https://www.komo.co.il"
SEARCH_PATH = "/code/nadlan/apartments-for-rent.asp"
DETAILS_URL = BASE_URL + "/code/nadlan/details/?modaaNum={id}"

_PRICE_RE = re.compile(r"(\d[\d,]*)")
_ROOMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*חדרים")
_SIZE_RE = re.compile(r"\((\d+)\s*מ\"ר\)")
_FLOOR_RE = re.compile(r"קומה:\s*([^\s<]+(?:\s*מתוך\s*\d+)?)")
_TYPE_RE = re.compile(r"^\s*(.+?)\s+\d+(?:\.\d+)?\s*חדרים")


class KomoParseWarning(UserWarning):
    pass


def search_params(goal: SearchGoal) -> dict:
    rooms = f"{goal.rooms:g}"
    return {"cityName": goal.city, "fromRooms": rooms, "toRooms": rooms, "toPrice": str(goal.max_price)}


def _int(text: str | None) -> int | None:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_listings(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Listing] = []
    for card in soup.select("div.modaa__box[key], div.modaaRowAd[key]"):
        source_id = (card.get("key") or "").strip()
        if not source_id.isdigit():
            continue
        title_el = card.select_one("h2.title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        parts = [p.strip() for p in title.split(",")]
        price_el = card.select_one("div.price")
        price = _int(price_el.get_text(" ", strip=True)) if price_el else None
        desc_el = card.select_one("div.description")
        desc = " ".join(desc_el.get_text(" ", strip=True).replace("\xa0", " ").split()) if desc_el else ""
        rooms_m, size_m, floor_m, type_m = (r.search(desc) for r in (_ROOMS_RE, _SIZE_RE, _FLOOR_RE, _TYPE_RE))
        street = parts[2] if len(parts) > 2 and parts[2] != "לא צוין רחוב" else None
        out.append(Listing(
            source="komo",
            source_id=source_id,
            url=DETAILS_URL.format(id=source_id),
            title=title,
            city=parts[0] if parts and parts[0] else None,
            neighborhood=parts[1] if len(parts) > 1 else None,
            street=street,
            price=price,
            rooms=float(rooms_m.group(1)) if rooms_m else None,
            size_sqm=int(size_m.group(1)) if size_m else None,
            floor=floor_m.group(1).strip() if floor_m else None,
            property_type=type_m.group(1).strip() if type_m else None,
            description=desc,
            verified=True,
        ))
    return out


def search_komo(goal: SearchGoal, http: PoliteHttp) -> tuple[list[Listing], list[str]]:
    """Fetch and parse page 1 of Komo results. Returns (listings, warnings)."""
    resp = http.get(BASE_URL + SEARCH_PATH, params=search_params(goal), allow_redirects=False)
    if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
        raise SourceError(f"Komo redirected to {resp.headers.get('Location', '?')} (login or block); not following")
    if resp.status_code != 200:
        raise SourceError(f"Komo returned HTTP {resp.status_code}")
    resp.encoding = resp.encoding or "utf-8"
    html = resp.text
    if looks_like_bot_challenge(html):
        raise SourceError("Komo returned a bot-protection page; not bypassing")
    listings = parse_listings(html)
    warnings = []
    if not listings and "נמצאו 0 מודעות" not in html:
        warnings.append("komo: page loaded but 0 listing cards parsed — markup may have changed")
    log.info("komo: parsed %d listings", len(listings))
    return listings, warnings
