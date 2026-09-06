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

    def set_candidate_review(self, project_id: str, candidate_id: str, review: str, generation: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            project = json.loads(row[0])
            if project.get("analysis_generation", 0) != generation:
                raise ValueError("影片分析已重置，請重新選取片段。")
            project.setdefault("candidate_reviews", {})[candidate_id] = review
            db.execute("UPDATE projects SET data=? WHERE id=?",
                       (json.dumps(project, ensure_ascii=False), project_id))

    def reset_analysis(self, project_id: str) -> dict:
        """Invalidate browser drafts and forget only this project's derived analysis."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError(project_id)
            project = json.loads(row[0])
            project["analysis_generation"] = project.get("analysis_generation", 0) + 1
            project["candidate_reviews"] = {}
            project["draft"] = {
                "start": 0, "victory": project["duration"] - 8,
                "postroll": 8, "reviewed": False,
                "origin": "manual", "revision": project["draft"]["revision"] + 1,
            }
            for key, data in db.execute("SELECT id, data FROM jobs").fetchall():
                job = json.loads(data)
                if job["project_id"] == project_id and job["kind"] == "analyze":
                    db.execute("DELETE FROM jobs WHERE id=?", (key,))
            db.execute("UPDATE projects SET data=? WHERE id=?",
                       (json.dumps(project, ensure_ascii=False), project_id))
        return project

    @staticmethod
    def _table(table):
        if table not in {"projects", "jobs"}:
            raise ValueError("Unknown table")
