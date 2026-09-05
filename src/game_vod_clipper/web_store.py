"""Small durable store shared by the API and its isolated media worker."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "runs" / "web" / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for table in ("projects", "jobs"):
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, table: str, key: str) -> dict | None:
        self._table(table)
        with self.connect() as db:
            row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, table: str) -> list[dict]:
        self._table(table)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT data FROM {table} ORDER BY rowid DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, table: str, value: dict):
        self._table(table)
        with self.connect() as db:
            db.execute(
                f"INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (value["id"], json.dumps(value, ensure_ascii=False, allow_nan=False)),
            )

    def patch(self, table: str, key: str, **changes):
        self._table(table)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()
            if not row:
                raise KeyError(key)
            value = json.loads(row[0]) | changes
            db.execute(
                f"UPDATE {table} SET data=? WHERE id=?",
                (json.dumps(value, ensure_ascii=False, allow_nan=False), key),
            )
        return value

    @staticmethod
    def _table(table):
        if table not in {"projects", "jobs"}:
            raise ValueError("Unknown table")
