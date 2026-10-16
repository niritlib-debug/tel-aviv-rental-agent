from datetime import timedelta

import pytest

from rental_agent.agent import Agent, ToolBox
from rental_agent.goal import SearchGoal
from rental_agent.tools.http import SourceError
from rental_agent.tools.komo import fetch_komo_details, parse_details
from tests.conftest import Clock, FakeResponse, at, details_for, details_html, fake_http, make_listing

ROBOTS_OK = FakeResponse(200, "User-agent: *\nDisallow: /api/\n")


def test_parse_details():
    d = parse_details(details_html("מתאימה ליחיד או לזוג.", parking="1", shutafim_ticked=True))
    assert d.full_text == "מתאימה ליחיד או לזוג."
    assert d.amenities == {"mizug", "shutafim"}  # only <li class="... add">
    assert d.parking_spaces == 1


def test_untucked_amenities_ignored_and_empty_parking():
    d = parse_details(details_html(parking=""))
    assert "shutafim" not in d.amenities and "longRent" not in d.amenities
    assert d.parking_spaces is None


def test_missing_description_is_an_error():
    with pytest.raises(SourceError, match="teurWrap"):
        parse_details("<html><body>new design</body></html>")


def test_fetch_details_ok_and_redirect():
    listing = make_listing("42")
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      "https://www.komo.co.il/code/nadlan/details/": FakeResponse(200, details_html("טקסט"))})
    assert fetch_komo_details(listing, http).full_text == "טקסט"
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      "https://www.komo.co.il/code/nadlan/details/": FakeResponse(302, headers={"Location": "/"})})
    with pytest.raises(SourceError, match="redirected"):
        fetch_komo_details(listing, http)


def _box(settings, memory, fetcher, clock, sleeps=None):
    return ToolBox(settings.goal, settings, http=None, memory=memory, sources={}, details_fetcher=fetcher,
                   now=clock, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def _store(memory, listing, when):
    memory.upsert(listing, memory.start_run(when, "x"), when)


def test_enrich_new_listing_fetches_and_classifies(settings, memory):
    fetch, sleeps = details_for({"1": "דרוש שותף", "2": "מתאימה ליחיד"}), []
    box = _box(settings, memory, fetch, Clock(at(2026, 10, 16)), sleeps)
    a, b = make_listing("1"), make_listing("2")
    box.enrich(a), box.enrich(b)
    assert fetch.calls == ["komo:1", "komo:2"] and sleeps == [settings.details_delay_seconds]  # pause between
    assert a.tenant_fit == "roommates_wanted" and b.tenant_fit == "single_ok"
    assert a.details_checked_at.startswith("2026-10-16")


def test_card_level_failures_are_not_fetched(settings, memory):
    fetch = details_for()
    _box(settings, memory, fetch, Clock(at(2026, 10, 16))).enrich(make_listing("1", price=9000))
    assert fetch.calls == []


def test_fresh_stored_details_are_reused(settings, memory):
    clock = Clock(at(2026, 10, 16, 8))
    first = make_listing("1")
    _box(settings, memory, details_for({"1": "מתאימה ליחיד"}), clock).enrich(first)
    _store(memory, first, clock())

    clock.t += timedelta(hours=12)
    fetch = details_for()
    again = make_listing("1")
    _box(settings, memory, fetch, clock).enrich(again)
    assert fetch.calls == [] and again.tenant_fit == "single_ok"

    clock.t += timedelta(hours=13)  # older than 24 h -> refetch
    _box(settings, memory, fetch, clock).enrich(make_listing("1"))
    assert fetch.calls == ["komo:1"]


def test_changed_card_triggers_refetch(settings, memory):
    clock = Clock(at(2026, 10, 16, 8))
    first = make_listing("1")
    _box(settings, memory, details_for(), clock).enrich(first)
    _store(memory, first, clock())
    fetch = details_for()
    _box(settings, memory, fetch, clock).enrich(make_listing("1", price=4500))
    assert fetch.calls == ["komo:1"]


def test_fetch_failure_falls_back_to_stored(settings, memory):
    clock = Clock(at(2026, 10, 16, 8))
    first = make_listing("1")
    _box(settings, memory, details_for({"1": "מתאימה ליחיד"}), clock).enrich(first)
    _store(memory, first, clock())

    def boom(listing):
        raise SourceError("timeout")
    clock.t += timedelta(days=2)
    box = _box(settings, memory, boom, clock)
    again = make_listing("1")
    box.enrich(again)
    assert again.tenant_fit == "single_ok" and again.details_checked_at == first.details_checked_at
    assert any("timeout" in e for e in box.errors)


def test_unchecked_policy(settings, memory):
    def boom(listing):
        raise SourceError("timeout")
    listing = make_listing("1")
    _box(settings, memory, boom, Clock(at(2026, 10, 16))).enrich(listing)
    assert listing.details_checked_at is None and listing.tenant_fit == "unknown"
    assert SearchGoal().matches(listing)  # warn (default): reported...
    assert "not checked for roommates" in listing.short()  # ...with a warning
    assert not SearchGoal(unchecked_policy="skip").matches(listing)


def test_page_parking_overrides_card(settings, memory):
    from rental_agent.tools.komo import parse_details as pd
    listing = make_listing("1")
    _box(settings, memory, lambda l: pd(details_html(parking="0")), Clock(at(2026, 10, 16))).enrich(listing)
    assert listing.has_parking is False and not SearchGoal().matches(listing)


def test_agent_end_to_end_excludes_roommate_ads(settings, memory):
    listings = [make_listing("1"), make_listing("2"), make_listing("3"), make_listing("4")]
    fetch = details_for({"1": "דרוש שותף לדירה", "2": "מחיר ללילה, לטווח קצר", "3": "מתאימה ליחיד או לזוג",
                         "4": "מושלמת לשותפים או לזוגות"})
    report = Agent(settings, memory, sources={"search_komo": lambda: listings}, notifiers=[],
                   details_fetcher=fetch, sleep=lambda s: None, now=Clock(at(2026, 10, 16))).run_once()
    assert sorted(l.id for l in report.new) == ["komo:3", "komo:4"]
    md = report.to_markdown()
    assert "suits a single tenant" in md and md.count("suits a single tenant") == 1
    assert memory.get("komo:3")["tenant_fit"] == "single_ok"
