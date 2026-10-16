import pytest

from rental_agent.goal import SearchGoal
from tests.conftest import make_listing

GOAL = SearchGoal()


@pytest.mark.parametrize("price,ok", [(5200, True), (5199, True), (1, True), (5201, False), (0, False), (None, False)])
def test_price_boundary(price, ok):
    assert GOAL.matches(make_listing(price=price)) is ok


@pytest.mark.parametrize("rooms,ok", [(3.0, True), (3, True), (2.5, False), (3.5, False), (4, False), (None, False)])
def test_exactly_three_rooms(rooms, ok):
    assert GOAL.matches(make_listing(rooms=rooms)) is ok


@pytest.mark.parametrize("city,ok", [("תל אביב יפו", True), ("תל אביב", True), ("Tel Aviv", True),
                                     ("רמת גן", False), ("גבעתיים", False), ("בת ים", False)])
def test_tel_aviv_only(city, ok):
    assert GOAL.matches(make_listing(city=city)) is ok


def test_city_falls_back_to_title_when_missing():
    assert GOAL.matches(make_listing(city=None, title="דירת 3 חדרים בתל אביב"))
    assert not GOAL.matches(make_listing(city=None, title="דירת 3 חדרים ברמת גן"))


@pytest.mark.parametrize("ptype,ok", [("דירה", True), ("דירת גן", True), ("פנטהאוז", True), ("סאבלט", False),
                                      ("חדר", False), ("משרד", False), (None, True)])
def test_entire_apartment_types(ptype, ok):
    assert GOAL.matches(make_listing(ptype=ptype)) is ok


def test_shared_apartment_keyword_rejected():
    ok, reasons = GOAL.check(make_listing(description="חדר בדירת שותפים, 3 חדרים"))
    assert not ok and any("שותפ" in r for r in reasons)


def test_describe_mentions_criteria():
    text = GOAL.describe()
    assert "5,200" in text and "3 rooms" in text and "Tel Aviv" in text
