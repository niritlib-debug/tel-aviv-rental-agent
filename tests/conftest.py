from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from rental_agent.config import Settings
from rental_agent.memory import Memory
from rental_agent.models import Listing
from rental_agent.tools.http import PoliteHttp

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Asia/Jerusalem")


@pytest.fixture
def komo_html() -> str:
    return (FIXTURES / "komo_results.html").read_text(encoding="utf-8")


@pytest.fixture
def memory():
    m = Memory(":memory:")
    yield m
    m.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "t.db"), report_dir=str(tmp_path / "reports"))


def make_listing(source_id="1", price=4800, rooms=3.0, city="תל אביב יפו", ptype="דירה", **kw) -> Listing:
    return Listing(source=kw.pop("source", "komo"), source_id=source_id,
                   url=kw.pop("url", f"https://www.komo.co.il/code/nadlan/details/?modaaNum={source_id}"),
                   title=kw.pop("title", f"{city}, שכונה, רחוב {source_id}"), city=city, price=price, rooms=rooms,
                   property_type=ptype, description=kw.pop("description", f"{ptype} {rooms} חדרים"), **kw)


def at(y, mo, d, h=8, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


class FakeResponse:
    def __init__(self, status=200, text="", json_data=None, headers=None):
        self.status_code = status
        self.text = text
        self._json = json_data
        self.headers = headers or {}
        self.encoding = "utf-8"

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession(requests.Session):
    """Routes requests to canned responses; records calls."""

    def __init__(self, routes: dict):
        super().__init__()
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp.pop(0) if isinstance(resp, list) else resp
        return FakeResponse(404, "")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


def fake_http(routes: dict) -> PoliteHttp:
    return PoliteHttp("test-agent/1.0", session=FakeSession(routes), sleep=lambda s: None)
