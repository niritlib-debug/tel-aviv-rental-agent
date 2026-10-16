"""Listing data model shared by tools, goal, memory and reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKED_FIELDS = ("price", "title", "description", "size_sqm", "floor")

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    """Lower-case scheme/host, drop fragment and tracking params, keep the rest."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), parts.path, urlencode(query), ""))


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str = ""
    city: str | None = None
    neighborhood: str | None = None
    street: str | None = None
    price: int | None = None
    rooms: float | None = None
    size_sqm: int | None = None
    floor: str | None = None
    property_type: str | None = None
    description: str = ""
    has_parking: bool | None = None  # None = unknown
    # Filled from the listing page / tenant classifier (SPEC §4.6)
    tenant_fit: str | None = None
    tenant_evidence: str = ""
    full_description: str = ""
    site_suits_roommates: bool | None = None
    details_checked_at: str | None = None  # ISO time of the last successful listing-page fetch
    verified: bool = True
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.url = normalize_url(self.url)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"

    def content_hash(self) -> str:
        payload = json.dumps({f: getattr(self, f) for f in TRACKED_FIELDS}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d

    def short(self) -> str:
        price = f"₪{self.price:,}" if self.price is not None else "price n/a"
        rooms = f"{self.rooms:g} rooms" if self.rooms is not None else "rooms n/a"
        parking = {True: " · parking", False: " · no parking"}.get(self.has_parking, "")
        tenant = " · suits a single tenant" if self.tenant_fit == "single_ok" else ""
        if self.source == "komo" and not self.details_checked_at:
            tenant += " · ⚠ not checked for roommates"
        flag = "" if self.verified else " [unverified: from search snippet]"
        return f"{self.title} · {rooms} · {price}{parking}{tenant} · {self.url}{flag}"
