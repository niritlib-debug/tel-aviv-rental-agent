import pytest

from rental_agent.goal import SearchGoal
from rental_agent.tools.http import SourceError
from rental_agent.tools.web_search import (TAVILY_URL, build_query, extract_parking, extract_price, extract_rooms,
                                           is_listing_url,
                                           results_to_listings, web_search)
from tests.conftest import FakeResponse, fake_http


@pytest.mark.parametrize("text,price", [("₪4,800 לחודש", 4800), ("4800 ש\"ח", 4800), ("מחיר: 5.200 ₪", 5200),
                                        ("NIS 4500", 4500), ("קומה 3", None), ("₪150", None)])
def test_extract_price(text, price):
    assert extract_price(text) == price


@pytest.mark.parametrize("text,rooms", [("דירת 3 חדרים", 3.0), ("3.5 חדרים", 3.5), ("3 rooms", 3.0), ("שלוש", None)])
def test_extract_rooms(text, rooms):
    assert extract_rooms(text) == rooms


def test_only_listing_urls():
    assert is_listing_url("https://www.yad2.co.il/realestate/item/abc123")
    assert not is_listing_url("https://www.yad2.co.il/realestate/rent?city=5000")


RESULTS = [
    {"url": "https://www.yad2.co.il/realestate/item/abc123", "title": "דירה 3 חדרים להשכרה בתל אביב", "content": "פלורנטין, 4,900 ₪, חניה בטאבו"},
    {"url": "https://www.yad2.co.il/realestate/item/nocity", "title": "דירה 3 חדרים", "content": "4,900 ₪"},
    {"url": "https://www.yad2.co.il/realestate/rent?city=5000", "title": "דירות להשכרה בתל אביב 3 חדרים", "content": "₪4,000"},
    {"url": "https://www.madlan.co.il/listings/xyz", "title": "3 חדרים בתל אביב", "content": "no price here"},
]


def test_results_to_listings_requires_all_fields():
    listings = results_to_listings(RESULTS)
    assert len(listings) == 1
    l = listings[0]
    assert l.source == "web:yad2.co.il" and l.price == 4900 and l.rooms == 3.0 and l.verified is False
    assert SearchGoal().matches(l)


def test_web_search_request_shape():
    http = fake_http({TAVILY_URL: FakeResponse(200, json_data={"results": RESULTS})})
    listings = web_search(SearchGoal(), http, "tvly-test")
    assert len(listings) == 1
    method, url, kwargs = http.session.calls[0]
    assert method == "POST" and kwargs["headers"]["Authorization"] == "Bearer tvly-test"
    assert "yad2.co.il" in kwargs["json"]["include_domains"]


def test_web_search_bad_key():
    http = fake_http({TAVILY_URL: FakeResponse(401, "unauthorized")})
    with pytest.raises(SourceError, match="API key"):
        web_search(SearchGoal(), http, "bad")


def test_web_search_requires_key():
    with pytest.raises(SourceError):
        web_search(SearchGoal(), fake_http({}), "")


@pytest.mark.parametrize("text,parking", [("כולל חניה", True), ("חנייה בבניין", True), ("with parking", True),
                                          ("ללא חניה", False), ("אין חניה", False), ("מרפסת ומעלית", None)])
def test_extract_parking(text, parking):
    assert extract_parking(text) is parking


def test_query_asks_for_parking():
    from rental_agent.goal import SearchGoal
    assert "חניה" in build_query(SearchGoal()) and "חניה" not in build_query(SearchGoal(require_parking=False))
