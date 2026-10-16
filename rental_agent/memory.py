"""Memory component: SQLite persistence, deduplication and change tracking."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import TRACKED_FIELDS, Listing

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id            TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  url           TEXT NOT NULL,
  title         TEXT, city TEXT, neighborhood TEXT, street TEXT,
  price         INTEGER, rooms REAL, size_sqm INTEGER, floor TEXT,
  property_type TEXT, description TEXT,
  verified      INTEGER NOT NULL DEFAULT 1,
  content_hash  TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active',
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  last_run_id   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_url ON listings(url);
CREATE TABLE IF NOT EXISTS listing_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id TEXT NOT NULL REFERENCES listings(id),
  run_id INTEGER, field TEXT NOT NULL, old_value TEXT, new_value TEXT,
  changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_changes_listing ON listing_changes(listing_id);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, mode TEXT,
  n_candidates INTEGER DEFAULT 0, n_matches INTEGER DEFAULT 0,
  n_new INTEGER DEFAULT 0, n_changed INTEGER DEFAULT 0,
  errors TEXT
);
"""

NEW, CHANGED, REAPPEARED, UNCHANGED = "new", "changed", "reappeared", "unchanged"


class Memory:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        with self.conn:
            if version < 1:
                self.conn.executescript(SCHEMA)
            if version < 2:
                self.conn.execute("ALTER TABLE listings ADD COLUMN has_parking INTEGER")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- runs -------------------------------------------------------------
    def start_run(self, now: datetime, mode: str) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO runs(started_at, status, mode) VALUES (?, 'running', ?)",
                                    (now.isoformat(), mode))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, now: datetime, status: str, *, mode: str, n_candidates: int,
                   n_matches: int, n_new: int, n_changed: int, errors: list[str]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at=?, status=?, mode=?, n_candidates=?, n_matches=?, n_new=?, "
                "n_changed=?, errors=? WHERE id=?",
                (now.isoformat(), status, mode, n_candidates, n_matches, n_new, n_changed,
                 json.dumps(errors, ensure_ascii=False), run_id))

    def recent_runs(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- listings ---------------------------------------------------------
    def get(self, listing_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
        return dict(row) if row else None

    def _find_existing(self, listing: Listing) -> dict | None:
        row = self.conn.execute("SELECT * FROM listings WHERE id=? OR url=? LIMIT 1",
                                (listing.id, listing.url)).fetchone()
        return dict(row) if row else None

    def upsert(self, listing: Listing, run_id: int, now: datetime) -> tuple[str, list[tuple[str, str, str]]]:
        """Insert or update a listing. Returns (status, [(field, old, new), ...])."""
        ts = now.isoformat()
        existing = self._find_existing(listing)
        values = dict(
            url=listing.url, title=listing.title, city=listing.city, neighborhood=listing.neighborhood,
            street=listing.street, price=listing.price, rooms=listing.rooms, size_sqm=listing.size_sqm,
            floor=listing.floor, property_type=listing.property_type, description=listing.description,
            verified=int(listing.verified), content_hash=listing.content_hash(),
            has_parking=None if listing.has_parking is None else int(listing.has_parking),
        )
        with self.conn:
            if existing is None:
                self.conn.execute(
                    "INSERT INTO listings(id, source, source_id, " + ", ".join(values) +
                    ", status, first_seen, last_seen, last_run_id) VALUES (?, ?, ?, " +
                    ", ".join("?" * len(values)) + ", 'active', ?, ?, ?)",
                    (listing.id, listing.source, listing.source_id, *values.values(), ts, ts, run_id))
                return NEW, []

            diffs = []
            if existing["content_hash"] != values["content_hash"]:
                for f in TRACKED_FIELDS:
                    old, new = existing[f], getattr(listing, f)
                    if old != new:
                        diffs.append((f, "" if old is None else str(old), "" if new is None else str(new)))
                self.conn.executemany(
                    "INSERT INTO listing_changes(listing_id, run_id, field, old_value, new_value, changed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)", [(existing["id"], run_id, f, o, n, ts) for f, o, n in diffs])
            was_stale = existing["status"] == "stale"
            self.conn.execute(
                "UPDATE listings SET " + ", ".join(f"{k}=?" for k in values) +
                ", status='active', last_seen=?, last_run_id=? WHERE id=?",
                (*values.values(), ts, run_id, existing["id"]))
        if diffs:
            return CHANGED, diffs
        return (REAPPEARED if was_stale else UNCHANGED), []

    def mark_stale(self, now: datetime, stale_after_days: int) -> int:
        cutoff = (now - timedelta(days=stale_after_days)).isoformat()
        with self.conn:
            cur = self.conn.execute("UPDATE listings SET status='stale' WHERE status='active' AND last_seen < ?",
                                    (cutoff,))
        return cur.rowcount

    def listings(self, include_stale: bool = False) -> list[dict]:
        sql = "SELECT * FROM listings" + ("" if include_stale else " WHERE status='active'")
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY last_seen DESC, price ASC")]

    def changes(self, listing_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM listing_changes WHERE listing_id=? ORDER BY id", (listing_id,))
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        counts = dict(self.conn.execute("SELECT status, COUNT(*) FROM listings GROUP BY status").fetchall())
        runs = self.recent_runs(5)
        return {
            "active_listings": counts.get("active", 0),
            "stale_listings": counts.get("stale", 0),
            "known_ids": [r["id"] for r in self.conn.execute("SELECT id FROM listings WHERE status='active' LIMIT 200")],
            "recent_runs": [{k: r[k] for k in ("id", "started_at", "status", "mode", "n_matches", "n_new", "n_changed")}
                            for r in runs],
        }
