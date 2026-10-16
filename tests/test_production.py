"""Guard, failure alert and dashboard export (Architecture.md §4.1, §4.4, §4.5)."""

import json
from datetime import datetime, timezone

import pytest

from rental_agent.cli import main
from rental_agent.config import Settings
from rental_agent.dashboard import export_dashboard
from rental_agent.scheduler import due_slot
from rental_agent.tools.http import SourceError
from tests.conftest import Clock, at, details_for, make_listing


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


NEVER_DONE = lambda slot: False  # noqa: E731


# ---- guard -------------------------------------------------------------------

@pytest.mark.parametrize("now,expected", [
    # summer (IDT, UTC+3): 05 UTC = 08:00 runs; 06 UTC = 09:00 is inside the window
    (utc(2026, 7, 15, 5), "2026-07-15T08:00"),
    (utc(2026, 7, 15, 17), "2026-07-15T20:00"),
    # winter (IST, UTC+2): 05 UTC = 07:00 is too early; 06 UTC = 08:00 runs
    (utc(2026, 1, 15, 5), None),
    (utc(2026, 1, 15, 6), "2026-01-15T08:00"),
    (utc(2026, 1, 15, 17), None),
    (utc(2026, 1, 15, 18), "2026-01-15T20:00"),
    # GitHub started 75 minutes late: still inside the 2 h window
    (utc(2026, 7, 15, 6, 15), "2026-07-15T08:00"),
    # outside any window
    (utc(2026, 7, 15, 12), None),
])
def test_guard_picks_israel_slot(now, expected):
    assert due_slot(Settings(), now, NEVER_DONE) == expected


def test_guard_skips_slot_already_done():
    done = {"2026-07-15T08:00"}
    assert due_slot(Settings(), utc(2026, 7, 15, 6), done.__contains__) is None  # second summer trigger


def test_failed_slot_is_retried(memory):
    run = memory.start_run(at(2026, 7, 15, 8), "deterministic", "2026-07-15T08:00")
    memory.finish_run(run, at(2026, 7, 15, 8, 1), "failed", mode="deterministic", n_candidates=0, n_matches=0,
                      n_new=0, n_changed=0, errors=["komo down"])
    assert not memory.slot_done("2026-07-15T08:00")
    assert due_slot(Settings(), utc(2026, 7, 15, 6), memory.slot_done) == "2026-07-15T08:00"
    run = memory.start_run(at(2026, 7, 15, 9), "deterministic", "2026-07-15T08:00")
    memory.finish_run(run, at(2026, 7, 15, 9, 1), "partial", mode="deterministic", n_candidates=1, n_matches=1,
                      n_new=1, n_changed=0, errors=[])
    assert memory.slot_done("2026-07-15T08:00")


def test_guard_window_crosses_midnight():
    s = Settings(times=("23:30",))
    assert due_slot(s, at(2026, 10, 17, 0, 45), NEVER_DONE) == "2026-10-16T23:30"


def test_cli_due_writes_github_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "gh_output"
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[memory]\ndb_path = "{tmp_path / "r.db"}"\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert main(["--config", str(cfg), "due", "--manual", "true"]) == 0
    assert "run=true\nslot=\n" in out.read_text()
    assert "slot=manual" in capsys.readouterr().out


# ---- failure alert -----------------------------------------------------------

def _agent(settings, memory, sources, alerts):
    from rental_agent.agent import Agent
    return Agent(settings, memory, sources=sources, notifiers=[], details_fetcher=details_for(),
                 sleep=lambda s: None, now=Clock(at(2026, 10, 16)), alerter=alerts.append)


def _boom():
    raise SourceError("komo down")


def test_alert_on_second_failure_and_on_recovery(settings, memory):
    alerts = []
    failing = _agent(settings, memory, {"search_komo": _boom}, alerts)
    failing.run_once()
    assert alerts == []                                   # one failure: no alert
    failing.run_once()
    assert len(alerts) == 1 and "last 2 runs failed" in alerts[0] and "komo down" in alerts[0]
    failing.run_once()
    assert len(alerts) == 1                               # no repeat while still failing
    _agent(settings, memory, {"search_komo": lambda: [make_listing("1")]}, alerts).run_once()
    assert len(alerts) == 2 and "recovered" in alerts[1] and "3 failed runs" in alerts[1]


def test_alert_send_failure_does_not_break_run(settings, memory):
    from rental_agent.agent import Agent

    def bad_alerter(text):
        raise RuntimeError("telegram down")
    agent = Agent(settings, memory, sources={"search_komo": _boom}, notifiers=[], details_fetcher=details_for(),
                  now=Clock(at(2026, 10, 16)), alerter=bad_alerter)
    agent.run_once()
    assert agent.run_once().status == "failed"


def test_consecutive_failures_ignores_running_rows(memory):
    memory.start_run(at(2026, 10, 16), "x")  # crashed run left as 'running'
    assert memory.consecutive_failures() == 0


# ---- dashboard -----------------------------------------------------------------

def test_export_dashboard(settings, memory, tmp_path):
    r = memory.start_run(at(2026, 10, 16, 8), "deterministic", "2026-10-16T08:00")
    memory.upsert(make_listing("1", price=5200, tenant_fit="single_ok", details_checked_at="2026-10-16T08:00:00+03:00",
                               neighborhood="פלורנטין"), r, at(2026, 10, 16, 8))
    memory.upsert(make_listing("1", price=4900, tenant_fit="single_ok", neighborhood="פלורנטין"), r, at(2026, 10, 16, 20))
    memory.finish_run(r, at(2026, 10, 16, 8, 1), "ok", mode="deterministic", n_candidates=1, n_matches=1,
                      n_new=1, n_changed=0, errors=[])
    out = export_dashboard(memory, settings, tmp_path / "site", at(2026, 10, 16, 20, 5))
    assert {p.name for p in out.iterdir()} == {"index.html", "listings.json", "runs.json", ".nojekyll"}
    data = json.loads((out / "listings.json").read_text(encoding="utf-8"))
    item = data["listings"][0]
    assert item["price"] == 4900 and item["tenant_fit"] == "single_ok" and item["has_parking"] is True
    assert item["price_history"][0]["old_value"] == "5200" and item["price_history"][0]["new_value"] == "4900"
    assert data["meta"]["last_success_at"].startswith("2026-10-16T08:01")
    assert data["meta"]["goal"]["max_price"] == 5200
    runs = json.loads((out / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert runs[0]["slot"] == "2026-10-16T08:00" and runs[0]["errors"] == []
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "listings.json" in html and "<script src=" not in html  # self-contained, no external scripts


def test_memory_file_is_complete_after_close(tmp_path):
    """WAL is checkpointed on close, so committing rentals.db alone keeps all data."""
    import sqlite3
    from rental_agent.memory import Memory
    path = tmp_path / "rentals.db"
    with Memory(path) as m:
        m.upsert(make_listing("1"), m.start_run(at(2026, 10, 16), "x"), at(2026, 10, 16))
    assert not (tmp_path / "rentals.db-wal").exists() or (tmp_path / "rentals.db-wal").stat().st_size == 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
