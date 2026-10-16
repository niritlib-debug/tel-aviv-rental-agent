"""Notifiers: console, Markdown report file, optional Telegram."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import Listing
from .http import PoliteHttp, SourceError

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    run_id: int
    started_at: datetime
    mode: str
    new: list[Listing] = field(default_factory=list)
    changed: list[tuple[Listing, list[tuple[str, str, str]]]] = field(default_factory=list)
    reappeared: list[Listing] = field(default_factory=list)
    unchanged: list[Listing] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    status: str = "ok"

    def to_markdown(self) -> str:
        ts = self.started_at.strftime("%Y-%m-%d %H:%M %Z")
        lines = [f"# Tel Aviv rentals — run #{self.run_id} ({ts})", "",
                 f"Mode: {self.mode} · Status: {self.status} · New: {len(self.new)} · "
                 f"Changed: {len(self.changed)} · Reappeared: {len(self.reappeared)} · "
                 f"Still available: {len(self.unchanged)}", ""]

        def item(listing: Listing) -> str:
            note = self.notes.get(listing.id)
            return f"- {listing.short()}" + (f" — _{note}_" if note else "")

        if self.new:
            lines += ["## New", *map(item, self.new), ""]
        if self.changed:
            lines.append("## Changed")
            for listing, diffs in self.changed:
                lines.append(item(listing))
                lines += [f"  - {f}: {old} → {new}" for f, old, new in diffs]
            lines.append("")
        if self.reappeared:
            lines += ["## Reappeared", *map(item, self.reappeared), ""]
        if self.unchanged:
            lines += ["## Still available", *map(item, self.unchanged), ""]
        if not (self.new or self.changed or self.reappeared or self.unchanged):
            lines += ["No matching listings this run.", ""]
        if self.errors:
            lines += ["## Errors / warnings", *(f"- {e}" for e in self.errors), ""]
        return "\n".join(lines)

    def to_short_text(self) -> str:
        """Compact text for chat notifications: only new/changed/reappeared."""
        lines = [f"Tel Aviv 3-room rentals ≤ budget — run #{self.run_id}"]
        for label, items in (("NEW", self.new), ("CHANGED", [l for l, _ in self.changed]), ("BACK", self.reappeared)):
            lines += [f"{label}: {l.short()}" for l in items]
        if len(lines) == 1:
            lines.append("No new or changed listings.")
        return "\n".join(lines)


class ConsoleNotifier:
    def send(self, report: RunReport) -> None:
        print(report.to_markdown())


class MarkdownReportNotifier:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def send(self, report: RunReport) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{report.started_at:%Y-%m-%d_%H%M}_run{report.run_id}.md"
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path


class TelegramNotifier:
    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str, http: PoliteHttp, only_when_news: bool = True):
        self.token, self.chat_id, self.http, self.only_when_news = token, chat_id, http, only_when_news

    def send(self, report: RunReport) -> None:
        if self.only_when_news and not (report.new or report.changed or report.reappeared):
            return
        self.send_text(report.to_short_text())

    def send_text(self, text: str) -> None:
        resp = self.http.post(self.API.format(token=self.token), check_robots=False,
                              json={"chat_id": self.chat_id, "text": text[:4000],  # Telegram limit is 4096
                                    "disable_web_page_preview": True})
        if resp.status_code != 200:
            raise SourceError(f"Telegram sendMessage failed: HTTP {resp.status_code}")
