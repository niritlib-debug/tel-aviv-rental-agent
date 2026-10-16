"""The agent: one run = goal + tools + memory, orchestrated by the LLM or deterministically."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .goal import SearchGoal
from .llm import LLMError, LLMPlanner
from .memory import CHANGED, NEW, REAPPEARED, Memory
from .models import Listing
from .tools.http import PoliteHttp, SourceError
from .tools.komo import search_komo
from .tools.notify import ConsoleNotifier, MarkdownReportNotifier, RunReport, TelegramNotifier
from .tools.web_search import web_search

log = logging.getLogger(__name__)


class ToolBox:
    """Executes tools for one run and keeps the run's candidate buffer."""

    def __init__(self, goal: SearchGoal, settings: Settings, http: PoliteHttp, memory: Memory,
                 sources: dict[str, Callable[[], list[Listing]]] | None = None):
        self.goal = goal
        self.settings = settings
        self.http = http
        self.memory = memory
        self.candidates: dict[str, Listing] = {}
        self.errors: list[str] = []
        self.sources_ok: set[str] = set()
        self.sources_failed: set[str] = set()
        self.sources = sources if sources is not None else self._default_sources()

    def _default_sources(self) -> dict[str, Callable[[], list[Listing]]]:
        sources: dict[str, Callable[[], list[Listing]]] = {}
        if self.settings.komo_enabled:
            def komo() -> list[Listing]:
                listings, warnings = search_komo(self.goal, self.http)
                self.errors.extend(warnings)
                return listings
            sources["search_komo"] = komo
        if self.settings.use_web_search:
            sources["web_search"] = lambda: web_search(self.goal, self.http, self.settings.tavily_api_key or "")
        return sources

    @property
    def tool_names(self) -> list[str]:
        return ["memory_summary", *self.sources]

    def run_source(self, name: str) -> list[Listing]:
        try:
            listings = self.sources[name]()
        except SourceError as exc:
            self.sources_failed.add(name)
            self.errors.append(f"{name}: {exc}")
            raise
        except Exception as exc:  # unexpected parser bug etc. — keep the run alive
            self.sources_failed.add(name)
            self.errors.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
            raise SourceError(str(exc)) from exc
        self.sources_ok.add(name)
        self.sources_failed.discard(name)
        for listing in listings:
            self.candidates.setdefault(listing.id, listing)
        return listings

    def execute(self, name: str, tool_input: dict) -> str:
        """Tool entry point for the LLM. Returns JSON text."""
        if name == "memory_summary":
            return json.dumps(self.memory.summary(), ensure_ascii=False)
        if name not in self.sources:
            raise SourceError(f"tool {name!r} is not available")
        listings = self.run_source(name)
        rows = []
        for l in listings:
            ok, reasons = self.goal.check(l)
            known = self.memory.get(l.id)
            rows.append({"id": l.id, "title": l.title, "price": l.price, "rooms": l.rooms,
                         "property_type": l.property_type, "has_parking": l.has_parking, "url": l.url, "verified": l.verified,
                         "already_known": bool(known), "known_price": known["price"] if known else None,
                         "passes_goal": ok, "reasons": reasons})
        return json.dumps({"count": len(rows), "candidates": rows}, ensure_ascii=False)

    def goal_matches(self) -> list[Listing]:
        out = []
        for l in self.candidates.values():
            ok, reasons = self.goal.check(l)
            if ok:
                out.append(l)
            else:
                log.debug("rejected %s: %s", l.id, "; ".join(reasons))
        return out


def _dedupe_by_url(listings: list[Listing]) -> list[Listing]:
    seen, out = set(), []
    for l in listings:
        if l.url not in seen:
            seen.add(l.url)
            out.append(l)
    return out


class Agent:
    def __init__(self, settings: Settings, memory: Memory, http: PoliteHttp | None = None,
                 llm_client: Any = None, sources: dict | None = None, notifiers: list | None = None,
                 now: Callable[[], datetime] | None = None):
        self.settings = settings
        self.memory = memory
        self.http = http or PoliteHttp(settings.user_agent)
        self.tz = ZoneInfo(settings.timezone)
        self.now = now or (lambda: datetime.now(self.tz))
        self.sources = sources
        self.llm_client = llm_client
        if self.llm_client is None and settings.use_llm:
            import anthropic
            self.llm_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.notifiers = notifiers if notifiers is not None else self._default_notifiers()

    def _default_notifiers(self) -> list:
        notifiers: list = [ConsoleNotifier(), MarkdownReportNotifier(self.settings.report_dir)]
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            notifiers.append(TelegramNotifier(self.settings.telegram_bot_token, self.settings.telegram_chat_id, self.http))
        return notifiers

    def run_once(self, use_llm: bool | None = None, dry_run: bool = False) -> RunReport:
        use_llm = (self.llm_client is not None) if use_llm is None else (use_llm and self.llm_client is not None)
        started = self.now()
        mode = "llm" if use_llm else "deterministic"
        run_id = self.memory.start_run(started, mode)
        box = ToolBox(self.settings.goal, self.settings, self.http, self.memory, self.sources)
        report = RunReport(run_id=run_id, started_at=started, mode=mode)
        notes: dict[str, str] = {}
        selected_ids: set[str] | None = None

        try:
            if use_llm:
                planner = LLMPlanner(self.llm_client, self.settings.llm_model, self.settings.llm_max_steps)
                try:
                    result = planner.run(self.settings.goal.describe(), box.tool_names, box.execute)
                    selected_ids = set()
                    for m in result.matches:
                        if m["id"] in box.candidates:
                            selected_ids.add(m["id"])
                            notes[m["id"]] = str(m.get("note", ""))[:200]
                        else:
                            box.errors.append(f"llm submitted unknown id {m['id']!r} — ignored")
                except LLMError as exc:
                    box.errors.append(f"llm: {exc}; falling back to deterministic mode")
                    mode = report.mode = "llm->deterministic"

            # Deterministic plan, also used to fill gaps after an LLM failure.
            for name in box.sources:
                if name not in box.sources_ok and name not in box.sources_failed:
                    try:
                        box.run_source(name)
                    except SourceError:
                        pass

            valid = box.goal_matches()
            valid_ids = {l.id for l in valid}
            if selected_ids is not None:
                rejected = selected_ids - valid_ids
                for rid in rejected:
                    box.errors.append(f"llm selected {rid} but it fails the goal — ignored")
                chosen = [l for l in valid if l.id in selected_ids]
                missed = [l for l in valid if l.id not in selected_ids]
                if missed:  # the goal is authoritative: never silently drop a valid match
                    log.info("LLM omitted %d valid matches; including them", len(missed))
                    chosen += missed
            else:
                chosen = valid
            chosen = _dedupe_by_url(chosen)

            if not dry_run:
                for listing in chosen:
                    status, diffs = self.memory.upsert(listing, run_id, started)
                    if status == NEW:
                        report.new.append(listing)
                    elif status == CHANGED:
                        report.changed.append((listing, diffs))
                    elif status == REAPPEARED:
                        report.reappeared.append(listing)
                    else:
                        report.unchanged.append(listing)
                if box.sources_ok:
                    self.memory.mark_stale(started, self.settings.stale_after_days)
            else:
                report.new = chosen

            report.notes = notes
            if not box.sources:
                box.errors.append("no sources enabled")
            if box.sources and not box.sources_ok:
                report.status = "failed"
            elif box.sources_failed:
                report.status = "partial"
            report.errors = box.errors

            for notifier in self.notifiers:
                try:
                    notifier.send(report)
                except Exception as exc:
                    report.errors.append(f"notifier {type(notifier).__name__}: {exc}")
        except Exception as exc:
            report.status = "failed"
            report.errors = box.errors + [f"run failed: {type(exc).__name__}: {exc}"]
            log.exception("run %s failed", run_id)
        finally:
            self.memory.finish_run(
                run_id, self.now(), report.status, mode=report.mode, n_candidates=len(box.candidates),
                n_matches=len(report.new) + len(report.changed) + len(report.reappeared) + len(report.unchanged),
                n_new=len(report.new), n_changed=len(report.changed), errors=report.errors)
        return report
