"""Polite HTTP client: honest User-Agent, robots.txt, timeouts, retries with backoff."""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
BOT_CHALLENGE_MARKERS = ("Radware Page", "perfdrive.com", "shieldsquare", "captcha", "cf-chl-")


class SourceError(RuntimeError):
    """A data source could not be used for this run (network, robots, bot wall, login...)."""


class PoliteHttp:
    def __init__(self, user_agent: str, timeout: float = 20.0, retries: int = 3, backoff: float = 2.0,
                 session: requests.Session | None = None, sleep=time.sleep):
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "he,en;q=0.8"})
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._sleep = sleep

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
                if resp.status_code >= 400:
                    rp.parse([])  # no robots.txt -> everything allowed
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException as exc:
                raise SourceError(f"could not read robots.txt for {base}: {exc}") from exc
            self._robots[base] = rp
        return rp.can_fetch(self.user_agent, url)

    def request(self, method: str, url: str, *, check_robots: bool = True, **kwargs) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise SourceError(f"blocked by robots.txt: {url}")
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code in RETRY_STATUS:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    delay = self.backoff ** attempt
                    log.warning("%s %s failed (%s); retry %d/%d in %.0fs", method, url, exc, attempt, self.retries - 1, delay)
                    self._sleep(delay)
        raise SourceError(f"{method} {url} failed after {self.retries} attempts: {last_exc}")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)


def looks_like_bot_challenge(text: str) -> bool:
    head = text[:5000].lower()
    return any(m.lower() in head for m in BOT_CHALLENGE_MARKERS)
