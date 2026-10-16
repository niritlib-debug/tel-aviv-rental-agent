"""Goal component: the search criteria and the single, code-enforced match check."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Listing

# Spellings under which Tel Aviv appears in listings. Matching is on normalized text.
TEL_AVIV_ALIASES = ("תל אביב יפו", "תל אביב-יפו", "תל אביב", "tel aviv", "tel-aviv", "יפו", "jaffa")


def _norm(text: str | None) -> str:
    return " ".join((text or "").replace("־", "-").replace("–", "-").lower().split())


@dataclass(frozen=True)
class SearchGoal:
    city: str = "תל אביב יפו"
    rooms: float = 3
    max_price: int = 5200
    allowed_property_types: tuple[str, ...] = ("דירה", "דירת גן", "דופלקס", "פנטהאוז", "גג/פנטהאוז", "טריפלקס", "מרתף/פרטר", "יחידת דיור")
    excluded_keywords: tuple[str, ...] = ("שותפ", "חדר בדירה", "חדר להשכרה", "סאבלט")

    def is_in_city(self, listing: Listing) -> bool:
        city = _norm(listing.city)
        if city:
            return any(city == _norm(a) for a in TEL_AVIV_ALIASES)
        # No structured city: require an alias in the title.
        title = _norm(listing.title)
        return any(_norm(a) in title for a in TEL_AVIV_ALIASES)

    def check(self, listing: Listing) -> tuple[bool, list[str]]:
        """Return (matches, reasons-for-rejection). Never relaxed by the LLM."""
        reasons: list[str] = []
        if not self.is_in_city(listing):
            reasons.append(f"city is not Tel Aviv-Yafo ({listing.city or listing.title!r})")
        if listing.rooms is None:
            reasons.append("rooms unknown")
        elif abs(listing.rooms - self.rooms) > 1e-9:
            reasons.append(f"rooms {listing.rooms:g} != {self.rooms:g}")
        if listing.price is None:
            reasons.append("price unknown")
        elif listing.price <= 0 or listing.price > self.max_price:
            reasons.append(f"price {listing.price} outside 1..{self.max_price}")
        if listing.property_type and listing.property_type not in self.allowed_property_types:
            reasons.append(f"property type {listing.property_type!r} is not an entire apartment")
        text = f"{listing.title} {listing.description} {listing.property_type or ''}"
        for kw in self.excluded_keywords:
            if kw in text:
                reasons.append(f"excluded keyword {kw!r} (not an entire apartment)")
                break
        return (not reasons, reasons)

    def matches(self, listing: Listing) -> bool:
        return self.check(listing)[0]

    def describe(self) -> str:
        return (
            f"Find entire apartments for rent in {self.city} (Tel Aviv-Yafo only) with exactly "
            f"{self.rooms:g} rooms and monthly rent of at most ₪{self.max_price:,}. "
            f"Allowed property types: {', '.join(self.allowed_property_types)}. "
            "Rooms in shared apartments are not acceptable."
        )
