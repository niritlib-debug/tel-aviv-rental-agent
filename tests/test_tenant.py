import pytest

from rental_agent.tenant import (ROOMMATES_ONLY, ROOMMATES_WANTED, SHORT_TERM, SINGLE_OK, UNKNOWN, TenantRules,
                                 classify_tenant, normalize)

# SPEC §3 acceptance examples (ad wording from live Komo listings, 2026-10-16; no personal details)
ACCEPTANCE = [
    ("דרוש שותף לדירת-גג בתל אביב. כניסה ב1 לאוקטובר.", ROOMMATES_WANTED),   # 4930853
    ("מחפשת שותפה לאמא שלי, רוב היום לא בבית.", ROOMMATES_WANTED),           # 4938846
    ("**ללא תיווך לטווח קצר עד 111 מחיר ללילה**", SHORT_TERM),               # 4931095
    ("דירת 3 חדרים בתל גיבורים, מתאימה ליחיד או לזוג.", SINGLE_OK),          # 4941056
    ("דירה משופצת עם נוף לפארק מושלמת לשותפים או לזוגות צעירים", UNKNOWN),  # 4913610
]


@pytest.mark.parametrize("text,expected", ACCEPTANCE)
def test_spec_acceptance_examples(text, expected):
    assert classify_tenant(text)[0] == expected


@pytest.mark.parametrize("text,expected", [
    ("חדר להשכרה בדירת 3 חדרים", ROOMMATES_WANTED),
    ("חדר בדירת שותפים בפלורנטין", ROOMMATES_WANTED),
    ("Looking for a roommate in a 3 bedroom flat", ROOMMATES_WANTED),
    ("הדירה מיועדת לשותפים", ROOMMATES_ONLY),
    ("לשותפים בלבד!", ROOMMATES_ONLY),
    ("מתאימה לרווקה או לזוג", SINGLE_OK),
    ("Great for a single tenant", SINGLE_OK),
    ("דירת 3 חדרים להשכרה ארוכת טווח", UNKNOWN),
])
def test_rules(text, expected):
    assert classify_tenant(text)[0] == expected


def test_negation_beats_roommate_wording():
    assert classify_tenant("לא מתאים לשותפים, מתאים לזוג") == (SINGLE_OK, "לא מתאים לשותפים")
    assert classify_tenant("ללא שותפים בבקשה")[0] == SINGLE_OK


def test_short_term_beats_everything():
    assert classify_tenant("מתאים ליחיד, השכרה לטווח קצר בלבד")[0] == SHORT_TERM


def test_whole_word_matching():
    assert classify_tenant("אפשרות הפיכה ליחידת דיור")[0] == UNKNOWN  # "ליחיד" inside "ליחידת"
    assert classify_tenant("3 חדרים להשכרה")[0] == UNKNOWN            # not "חדר להשכרה"


def test_normalize():
    assert normalize("דירת־גג, ליחיד/ה!") == "דירת גג ליחיד ה"
    assert normalize("שׁוּתָּף") == "שותף"  # niqqud removed


def test_amenity_label_text_alone_is_not_roommate_wording():
    # Every Komo page lists the label "מותאם לשותפים"; it must not reject on its own.
    assert classify_tenant("מעלית מיזוג מותאם לשותפים חיות מחמד")[0] == UNKNOWN


def test_custom_rules():
    rules = TenantRules.from_config({"single_ok": ["מתאים לסטודנט"]})
    assert classify_tenant("מתאים לסטודנט", rules)[0] == SINGLE_OK
    assert classify_tenant("ליחיד", rules)[0] == UNKNOWN  # list replaced, not merged


def test_unknown_config_key():
    with pytest.raises(ValueError):
        TenantRules.from_config({"roomates": ["typo"]})
