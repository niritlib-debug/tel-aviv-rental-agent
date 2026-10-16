"""Goal component: the search criteria and the single, code-enforced match check."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Listing
from .tenant import REJECTED_FOR_SINGLE_TENANT, SHORT_TERM, TenantRules, classify_tenant

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
    excluded_keywords: tuple[str, ...] = ("סאבלט",)  # roommate wording lives in tenant_rules
    require_parking: bool = True
    single_tenant_only: bool = True
    unchecked_policy: str = "warn"  # warn | skip — Komo listings whose page could not be checked
    tenant_rules: TenantRules = field(default_factory=TenantRules)

    def is_in_city(self, listing: Listing) -> bool:
        city = _norm(listing.city)
        if city:
            return any(city == _norm(a) for a in TEL_AVIV_ALIASES)
        # No structured city: require an alias in the title.
        title = _norm(listing.title)
        return any(_norm(a) in title for a in TEL_AVIV_ALIASES)

    def tenant_fit(self, listing: Listing) -> str:
        """Use the classification made from the listing page, or classify the text we have."""
        if listing.tenant_fit:
            return listing.tenant_fit
        text = f"{listing.title} {listing.description} {listing.full_description}"
        return classify_tenant(text, self.tenant_rules)[0]

    def check(self, listing: Listing, card_only: bool = False) -> tuple[bool, list[str]]:
        """Return (matches, reasons-for-rejection). Never relaxed by the LLM.

        ``card_only`` skips the tenant rules, which need the full listing page (SPEC F2d).
        """
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
        if self.require_parking and listing.has_parking is not True:
            reasons.append("no parking" if listing.has_parking is False else "parking not confirmed")
        if listing.property_type and listing.property_type not in self.allowed_property_types:
            reasons.append(f"property type {listing.property_type!r} is not an entire apartment")
        text = f"{listing.title} {listing.description} {listing.property_type or ''}"
        for kw in self.excluded_keywords:
            if kw in text:
                reasons.append(f"excluded keyword {kw!r} (not an entire apartment)")
                break
        if not card_only:
            fit = self.tenant_fit(listing)
            if fit == SHORT_TERM:
                reasons.append("short-term / per-night rental, not a monthly rent")
            elif self.single_tenant_only and fit in REJECTED_FOR_SINGLE_TENANT:
                reasons.append(f"not for a single tenant ({fit})")
            if (self.single_tenant_only and self.unchecked_policy == "skip"
                    and listing.source == "komo" and not listing.details_checked_at):
                reasons.append("listing page not checked for roommates yet")
        return (not reasons, reasons)

    def matches(self, listing: Listing) -> bool:
        return self.check(listing)[0]

    def describe(self) -> str:
        return (
            f"Find entire apartments for rent in {self.city} (Tel Aviv-Yafo only) with exactly "
            f"{self.rooms:g} rooms and a stated monthly rent of at most ₪{self.max_price:,} "
            "(listings without a price are not acceptable). "
            + ("The apartment must include a parking space. " if self.require_parking else "") +
            f"Allowed property types: {', '.join(self.allowed_property_types)}. "
            + ("It must be rentable by a single tenant on their own: no roommate-wanted ads, no rooms in "
               "shared flats, no roommates-only flats. " if self.single_tenant_only else "")
            + "Long-term monthly rentals only (no short-term or per-night ads)."
        )
