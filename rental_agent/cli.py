"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .agent import Agent
from .config import ConfigError, load_settings
from .memory import Memory
from .scheduler import due_slot, next_run_times, run_forever


def _github_output(**values: str) -> None:
    """Expose values to later GitHub Actions steps (no-op elsewhere)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for key, value in values.items():
                fh.write(f"{key}={value}\n")


def _agent(settings, memory, no_llm: bool) -> Agent:
    if no_llm:
        settings.llm_enabled = False
    return Agent(settings, memory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rental_agent", description="Tel Aviv 3-room rental search agent")
    parser.add_argument("--config", help="path to config.toml (default: $RENTAL_AGENT_CONFIG or ./config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run-once", help="run one search now")
    p.add_argument("--no-llm", action="store_true", help="deterministic mode even if ANTHROPIC_API_KEY is set")
    p.add_argument("--dry-run", action="store_true", help="do not write listings to memory")
    p.add_argument("--slot", default="", help="scheduled slot id from `due` (e.g. 2026-10-16T08:00)")
    p = sub.add_parser("due", help="guard for UTC cron: is an Israel-time slot due now? (prints run=true/false)")
    p.add_argument("--manual", default="false", help="true = a person started the run: always due")
    p = sub.add_parser("export-dashboard", help="write the static dashboard (index.html + JSON)")
    p.add_argument("--out", default="site", help="output directory (default: site)")
    p = sub.add_parser("schedule", help="run forever on the configured schedule")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--run-now", action="store_true", help="also run once immediately at startup")
    p = sub.add_parser("list", help="show listings in memory")
    p.add_argument("--all", action="store_true", help="include stale listings")
    p = sub.add_parser("history", help="show recent runs")
    p.add_argument("--limit", type=int, default=10)
    sub.add_parser("next-runs", help="show the next scheduled run times")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "next-runs":
        for t in next_run_times(settings, 4):
            print(t.strftime("%Y-%m-%d %H:%M %Z"))
        return 0

    with Memory(settings.db_path) as memory:
        if args.cmd == "run-once":
            report = _agent(settings, memory, args.no_llm).run_once(dry_run=args.dry_run, slot=args.slot or None)
            return 0 if report.status != "failed" else 1
        if args.cmd == "due":
            manual = args.manual.strip().lower() in ("1", "true", "yes")
            slot = None if manual else due_slot(settings, datetime.now(ZoneInfo(settings.timezone)), memory.slot_done)
            run = manual or slot is not None
            _github_output(run="true" if run else "false", slot=slot or "")
            print(f"run={'true' if run else 'false'} slot={slot or ('manual' if manual else '-')}")
            return 0
        if args.cmd == "export-dashboard":
            from .dashboard import export_dashboard
            out = export_dashboard(memory, settings, args.out, datetime.now(ZoneInfo(settings.timezone)))
            print(f"dashboard written to {out}")
            return 0
        if args.cmd == "schedule":
            agent = _agent(settings, memory, args.no_llm)
            run_forever(settings, agent.run_once, run_now=args.run_now)
            return 0
        if args.cmd == "list":
            rows = memory.listings(include_stale=args.all)
            for r in rows:
                parking = {1: " · parking", 0: " · no parking"}.get(r["has_parking"], "")
                if r.get("tenant_fit") == "single_ok":
                    parking += " · suits a single tenant"
                elif r["source"] == "komo" and not r.get("details_checked_at"):
                    parking += " · ⚠ not checked for roommates"
                print(f"[{r['status']}] ₪{r['price']:,} · {r['rooms']:g} rooms{parking} · {r['title']} · {r['url']}"
                      f"{'' if r['verified'] else ' [unverified]'} (first seen {r['first_seen'][:16]})")
            print(f"{len(rows)} listing(s)")
            return 0
        if args.cmd == "history":
            for r in memory.recent_runs(args.limit):
                errs = json.loads(r["errors"] or "[]")
                print(f"#{r['id']} {r['started_at'][:16]} {r['status']:<8} {r['mode'] or '':<20} "
                      f"matches={r['n_matches']} new={r['n_new']} changed={r['n_changed']} errors={len(errs)}")
            return 0
    return 1
