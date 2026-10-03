"""Small durable store shared by the API and its isolated media worker."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from pathlib import Path

from ..youtube.history import remember
from .locations import project_work


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "runs" / "web" / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for table in ("projects", "jobs", "usage", "youtube_history", "retained_media"):
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )
            db.execute("BEGIN IMMEDIATE")
            for (data,) in db.execute("SELECT data FROM projects").fetchall():
                remember(db, json.loads(data))
        from ..codex.usage import backfill_usage
        backfill_usage(self)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, table: str, key: str) -> dict | None:
        self._table(table)
        with self.connect() as db:
            row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()  # nosec B608 # _table() allowlists identifiers; values are bound.
        return json.loads(row[0]) if row else None

    def all(self, table: str) -> list[dict]:
        self._table(table)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT data FROM {table} ORDER BY rowid DESC"  # nosec B608 # _table() allowlists identifiers; values are bound.
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, table: str, value: dict):
        self._table(table)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                f"INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",  # nosec B608 # _table() allowlists identifiers; values are bound.
                (value["id"], json.dumps(value, ensure_ascii=False, allow_nan=False)),
            )
            if table == "projects":
                remember(db, value)

    def patch(self, table: str, key: str, **changes):
        self._table(table)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"SELECT data FROM {table} WHERE id=?", (key,)).fetchone()  # nosec B608 # _table() allowlists identifiers; values are bound.
            if not row:
                raise KeyError(key)
            value = json.loads(row[0]) | changes
            db.execute(
                f"UPDATE {table} SET data=? WHERE id=?",  # nosec B608 # _table() allowlists identifiers; values are bound.
                (json.dumps(value, ensure_ascii=False, allow_nan=False), key),
            )
            if table == "projects":
                remember(db, value)
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

    def delete_project(self, project_id: str):
        """Remove workspace records atomically; retain source and generated files."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError(project_id)
            remember(db, json.loads(row[0]), deleted=True)
            # Preserve exact media locations even if the user later changes the
            # configured folders. These tiny receipts contain no media data.
            project = json.loads(row[0])
            related = [json.loads(data) for _, data in db.execute("SELECT id, data FROM jobs").fetchall()
                       if json.loads(data).get("project_id") == project_id]
            media = [(project.get("source"), "sources"), (str(project_work(self.root, project) / "preview.mp4"), "previews")]
            media.extend((job.get("output"), "exports") for job in related if job.get("kind") == "export")
            for path, category in media:
                if path:
                    key = hashlib.sha256(path.encode()).hexdigest()
                    db.execute("INSERT OR IGNORE INTO retained_media VALUES (?,?)",
                               (key, json.dumps({"id": key, "path": path, "category": category})))
            keys = [(job["id"],) for job in related]
            db.executemany("DELETE FROM jobs WHERE id=?", keys)
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def delete_clip(self, project_id: str, job_id: str):
        """Remove only a completed export belonging to this project."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            job = json.loads(row[0]) if row else None
            if (not job or job["project_id"] != project_id or job["kind"] != "export"
                    or job["status"] != "succeeded"):
                raise KeyError(job_id)
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def set_candidate_edit(self, project_id: str, candidate_id: str, edit: dict):
        from ..analysis.candidates import project_candidates

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError(project_id)
            project = json.loads(row[0])
            if project.get("analysis_generation", 0) != edit["analysis_generation"]:
                raise ValueError("影片分析已重置，請重新選取片段。")
            jobs = [json.loads(row[0]) for row in db.execute("SELECT data FROM jobs ORDER BY rowid DESC")]
            candidate = next((c for c in project_candidates(project, jobs) if c["id"] == candidate_id), None)
            if not candidate:
                raise KeyError(candidate_id)
            previous = candidate.get("manual_edit", {})
            if previous.get("revision", 0) != edit["revision"]:
                raise ValueError("此片段已在其他視窗調整，請重新載入後再編輯。")
            saved = {key: edit[key] for key in ("start", "victory", "postroll")}
            saved.update(revision=edit["revision"] + 1, updated_at=time.time())
            project.setdefault("candidate_edits", {})[candidate_id] = saved
            project.setdefault("candidate_reviews", {})[candidate_id] = "pending"
            db.execute("UPDATE projects SET data=? WHERE id=?",
                       (json.dumps(project, ensure_ascii=False, allow_nan=False), project_id))

            return next(c for c in project_candidates(project, jobs) if c["id"] == candidate_id)

    def reset_analysis(self, project_id: str, *, progress_only: bool = False) -> dict:
        """Forget viewing progress, optionally retaining candidate records and edits."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise KeyError(project_id)
            project = json.loads(row[0])
            project["editor_generation"] = project.get("editor_generation", project.get("analysis_generation", 0))
            project["analysis_generation"] = project.get("analysis_generation", 0) + 1
            if not progress_only:
                project["editor_generation"] += 1
                project["candidate_reviews"] = {}
                project["candidate_edits"] = {}
                project["draft"] = {
                    "start": 0, "victory": project["duration"] - 8,
                    "postroll": 8, "reviewed": False,
                    "origin": "manual", "revision": project["draft"]["revision"] + 1,
                }
            for key, data in db.execute("SELECT id, data FROM jobs").fetchall():
                job = json.loads(data)
                if job["project_id"] == project_id and job["kind"] == "analyze":
                    if progress_only:
                        # Keep reviewable candidates, but never resume this old run
                        # or count it toward the next search's viewing progress.
                        job.update(progress_reset=True, resumable=False, coverage=[])
                        if job.get("result"):
                            job["result"].update(can_continue=False, coverage=[])
                        db.execute("UPDATE jobs SET data=? WHERE id=?",
                                   (json.dumps(job, ensure_ascii=False), key))
                    else:
                        db.execute("DELETE FROM jobs WHERE id=?", (key,))
            db.execute("UPDATE projects SET data=? WHERE id=?",
                       (json.dumps(project, ensure_ascii=False), project_id))
        return project

    @staticmethod
    def _table(table):
        if table not in {"projects", "jobs", "usage", "youtube_history", "retained_media"}:
            raise ValueError("Unknown table")
