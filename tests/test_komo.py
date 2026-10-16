import pytest

from rental_agent.goal import SearchGoal
from rental_agent.tools.http import SourceError
from rental_agent.tools.komo import parse_listings, search_komo, search_params
from tests.conftest import FakeResponse, fake_http

ROBOTS_OK = FakeResponse(200, "User-agent: *\nDisallow: /api/\n")
SEARCH = "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"


def test_parse_fixture(komo_html):
    listings = {l.source_id: l for l in parse_listings(komo_html)}
    assert len(listings) == 6
    a = listings["1000001"]
    assert a.id == "komo:1000001"
    assert a.url == "https://www.komo.co.il/code/nadlan/details/?modaaNum=1000001"
    assert (a.city, a.neighborhood, a.street) == ("תל אביב יפו", "פלורנטין", "רחוב הדוגמה 5")
    assert (a.price, a.rooms, a.size_sqm, a.property_type) == (4800, 3.0, 70, "דירה")
    assert a.floor == "2 מתוך 4"
    assert listings["1000002"].street is None  # "לא צוין רחוב"
    assert listings["1000004"].price is None  # no price
    assert listings["1000006"].rooms == 3.5


def test_goal_filters_fixture(komo_html):
    matches = [l.source_id for l in parse_listings(komo_html) if SearchGoal().matches(l)]
    assert matches == ["1000001", "1000002"]  # sublet, no-price, Ramat Gan and 3.5 rooms rejected


def test_search_params():
    assert search_params(SearchGoal()) == {"cityName": "תל אביב יפו", "fromRooms": "3", "toRooms": "3", "toPrice": "5200"}


def test_search_komo_ok(komo_html):
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK, SEARCH: FakeResponse(200, komo_html)})
    listings, warnings = search_komo(SearchGoal(), http)
    assert len(listings) == 6 and warnings == []
    method, url, kwargs = http.session.calls[-1]
    assert kwargs["params"]["toPrice"] == "5200" and kwargs["allow_redirects"] is False


def test_login_redirect_is_not_followed():
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      SEARCH: FakeResponse(302, "", headers={"Location": "https://account.komo.co.il/?r=..."})})
    with pytest.raises(SourceError, match="redirected"):
        search_komo(SearchGoal(), http)


def test_bot_challenge_detected():
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      SEARCH: FakeResponse(200, "<html><title>Radware Page</title></html>")})
    with pytest.raises(SourceError, match="bot-protection"):
        search_komo(SearchGoal(), http)


def test_robots_disallow_blocks_request():
    http = fake_http({"https://www.komo.co.il/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /code/\n")})
    with pytest.raises(SourceError, match="robots.txt"):
        search_komo(SearchGoal(), http)
    assert all("apartments-for-rent" not in url for _, url, _ in http.session.calls)


def test_markup_change_produces_warning():
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK, SEARCH: FakeResponse(200, "<html>new design</html>")})
    listings, warnings = search_komo(SearchGoal(), http)
    assert listings == [] and "markup" in warnings[0]


def test_retries_then_fails_on_5xx():
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      SEARCH: [FakeResponse(503), FakeResponse(503), FakeResponse(503)]})
    with pytest.raises(SourceError, match="after 3 attempts"):
        search_komo(SearchGoal(), http)


def test_retry_recovers(komo_html):
    http = fake_http({"https://www.komo.co.il/robots.txt": ROBOTS_OK,
                      SEARCH: [FakeResponse(503), FakeResponse(200, komo_html)]})
    listings, _ = search_komo(SearchGoal(), http)
    assert len(listings) == 6
