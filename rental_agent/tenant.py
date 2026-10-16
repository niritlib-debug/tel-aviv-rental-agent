"""Tenant classification (SPEC §4.6): can a single tenant rent the whole flat long-term?

Phrase-based and ordered; the first matching rule wins. Phrases match on whole
words after normalisation, so "ליחיד" does not match inside "ליחידת".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SHORT_TERM = "short_term"
ROOMMATES_WANTED = "roommates_wanted"
ROOMMATES_ONLY = "roommates_only"
SINGLE_OK = "single_ok"
UNKNOWN = "unknown"

REJECTED_FOR_SINGLE_TENANT = (ROOMMATES_WANTED, ROOMMATES_ONLY)

DEFAULT_RULES = {
    "short_term": ["ללילה", "לטווח קצר", "per night", "short term", "airbnb"],
    "negated_roommates": ["לא לשותפים", "ללא שותפים", "בלי שותפים", "לא מתאים לשותפים", "לא מתאימה לשותפים",
                          "no roommates"],
    "roommates_wanted": ["דרוש שותף", "דרושה שותפה", "דרושים שותפים", "דרושות שותפות",
                         "מחפש שותף", "מחפש שותפה", "מחפשת שותף", "מחפשת שותפה",
                         "מחפשים שותף", "מחפשים שותפה", "מחפשים שותפים", "מחפשות שותפה",
                         "שותף לדירה", "שותפה לדירה", "חדר בדירת שותפים", "חדר בדירה", "חדר להשכרה", "להשכרה חדר",
                         "roommate wanted", "looking for a roommate", "room in a shared", "room for rent"],
    "roommates_only": ["לשותפים בלבד", "רק לשותפים", "מיועדת לשותפים", "מיועד לשותפים"],
    "single_ok": ["ליחיד", "ליחידה", "לרווק", "לרווקה", "לאדם אחד", "single tenant", "for a single"],
}

_NIQQUD = re.compile(r"[֑-ׇ]")


def normalize(text: str) -> str:
    text = (text or "").replace("־", " ")  # maqaf is inside the niqqud range; split words first
    text = _NIQQUD.sub("", text)
    text = re.sub(r"[׳״'\"`]", "", text)          # geresh / gershayim / quotes
    text = re.sub(r"[־\-–—_/\\|*.,;:!?()\[\]{}]", " ", text)  # maqaf, hyphens, punctuation
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class TenantRules:
    short_term: tuple[str, ...] = tuple(DEFAULT_RULES["short_term"])
    negated_roommates: tuple[str, ...] = tuple(DEFAULT_RULES["negated_roommates"])
    roommates_wanted: tuple[str, ...] = tuple(DEFAULT_RULES["roommates_wanted"])
    roommates_only: tuple[str, ...] = tuple(DEFAULT_RULES["roommates_only"])
    single_ok: tuple[str, ...] = tuple(DEFAULT_RULES["single_ok"])
    _compiled: dict = field(default_factory=dict, compare=False, hash=False, repr=False)

    @classmethod
    def from_config(cls, data: dict | None) -> "TenantRules":
        data = data or {}
        unknown = set(data) - set(DEFAULT_RULES)
        if unknown:
            raise ValueError(f"unknown [goal.tenant] keys: {sorted(unknown)}")
        return cls(**{k: tuple(data.get(k, DEFAULT_RULES[k])) for k in DEFAULT_RULES})

    def _find(self, name: str, text: str) -> str | None:
        rx = self._compiled.get(name)
        if rx is None:
            phrases = sorted({normalize(p) for p in getattr(self, name) if normalize(p)}, key=len, reverse=True)
            rx = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, phrases)) + r")(?!\w)") if phrases else None
            self._compiled[name] = rx
        if rx is None:
            return None
        m = rx.search(text)
        return m.group(1) if m else None


def classify_tenant(text: str, rules: TenantRules | None = None) -> tuple[str, str]:
    """Return (tenant_fit, evidence-phrase). Amenity ticks are deliberately not an input."""
    rules = rules or TenantRules()
    norm = normalize(text)
    for name, verdict in (("short_term", SHORT_TERM), ("negated_roommates", SINGLE_OK),
                          ("roommates_wanted", ROOMMATES_WANTED), ("roommates_only", ROOMMATES_ONLY),
                          ("single_ok", SINGLE_OK)):
        hit = rules._find(name, norm)
        if hit:
            return verdict, hit
    return UNKNOWN, ""
