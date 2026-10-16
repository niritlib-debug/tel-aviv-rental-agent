"""Outer loop: run the agent on a cron schedule in the Asia/Jerusalem time zone."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.combining import OrTrigger

from .config import Settings

log = logging.getLogger(__name__)


def build_trigger(settings: Settings):
    tz = ZoneInfo(settings.timezone)
    triggers = [CronTrigger(hour=h, minute=m, timezone=tz) for h, m in settings.schedule_hours_minutes]
    return triggers[0] if len(triggers) == 1 else OrTrigger(triggers)


def next_run_times(settings: Settings, count: int = 4, start: datetime | None = None) -> list[datetime]:
    trigger = build_trigger(settings)
    tz = ZoneInfo(settings.timezone)
    now = start or datetime.now(tz)
    out, prev = [], None
    for _ in range(count):
        nxt = trigger.get_next_fire_time(prev, now)
        if nxt is None:
            break
        out.append(nxt)
        prev, now = nxt, nxt
    return out


def safe_job(job: Callable[[], object]) -> Callable[[], None]:
    def wrapper() -> None:
        try:
            job()
        except Exception:  # keep the scheduler alive no matter what
            log.exception("scheduled run failed")
    return wrapper


def run_forever(settings: Settings, job: Callable[[], object], run_now: bool = False) -> None:
    scheduler = BlockingScheduler(timezone=ZoneInfo(settings.timezone))
    scheduler.add_job(safe_job(job), build_trigger(settings), id="rental-search",
                      misfire_grace_time=3600, coalesce=True, max_instances=1)
    if run_now:
        safe_job(job)()
    for t in next_run_times(settings, 2):
        log.info("next run: %s", t.isoformat())
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")
