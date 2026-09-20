"""Durable, channel-bound waiting list ahead of the single media worker."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time

from fastapi import HTTPException

from .youtube_account import YouTubeError

WAITING = {"queued", "importing"}
MAX_WAITING = 200


class YouTubeImports:
    def __init__(self, store, account, lock, import_video):
        self.store, self.account, self.lock = store, account, lock
        self.import_video = import_video  # Called only while the workspace lock is held.
        self.records = {path.stem.removeprefix("import-task-"): account.files.read(path.stem)
                        for path in account.files.path.glob("import-task-*.json")}

    def save(self, item):
        if not re.fullmatch(r"[a-f0-9]{32}", item["id"]):
            raise ValueError("Invalid import record ID")
        self.account.files.write("import-task-" + item["id"], item)
        self.records[item["id"]] = dict(item)
        return item

    def get(self, key):
        if key not in self.records:
            raise YouTubeError("找不到匯入紀錄。", 404)
        return dict(self.records[key])

    def add(self, videos: list[dict], options: dict, channel: dict):
        """The caller validates the request and holds the workspace lock."""
        selected = {}
        for video in videos:
            selected.setdefault(video["id"], video)
        entries, added = [], 0
        for video in selected.values():
            key = hashlib.sha256(f"{channel['id']}:{video['id']}".encode()).hexdigest()[:32]
            previous = self.records.get(key)
            if previous and (previous["status"] in WAITING or previous.get("project_id")
                             and self.store.get("projects", previous["project_id"])):
                entries.append(previous)
                continue
            entries.append({"id": key, "video_id": video["id"], "title": video["title"], "channel": channel,
                            "options": options, "status": "queued", "project_id": None, "error": None,
                            "created": time.time(), "retry_at": 0})
            added += 1
        if sum(item["status"] in WAITING for item in self.records.values()) + added > MAX_WAITING:
            raise YouTubeError("等待匯入的影片已達 200 部，請等部分完成後再加入。", 429)
        for item in entries:
            if item is not self.records.get(item["id"]):
                self.save(item)
        return {"added": added, "existing": len(entries) - added}

    def cancel(self, key):
        item = self.get(key)
        if item["status"] != "queued":
            raise YouTubeError("這部影片已開始處理，請到工作區管理下載任務。", 409)
        self.save(item | {"status": "cancelled", "error": None})

    def retry(self, key):
        item = self.get(key)
        if item["status"] not in {"failed", "cancelled"}:
            raise YouTubeError("這筆匯入不需要重新加入；已開始的下載請在工作區重試。", 409)
        if sum(entry["status"] in WAITING for entry in self.records.values()) >= MAX_WAITING:
            raise YouTubeError("等待匯入的影片已滿，請稍後再試。", 429)
        self.save(item | {"status": "queued", "error": None, "retry_at": 0, "created": time.time()})

    def recover(self):
        for item in list(self.records.values()):
            if item["status"] == "importing":
                # Import deduplication recovers a project created before a crash.
                self.save(item | {"status": "queued", "retry_at": 0})

    async def advance(self):
        async with self.lock:
            status = self.account.status()
            if not status["connected"] or status["pending"] or status["reconnect_required"]:
                return
            waiting = sorted((item for item in self.records.values() if item["status"] == "queued"
                              and item["channel"]["id"] == status["channel"]["id"]), key=lambda item: item["created"])
            if not waiting or waiting[0]["retry_at"] > time.time():
                return
            jobs = self.store.all("jobs")
            active = [job for job in jobs if job["status"] in {"queued", "running"}]
            # Leave long selections here instead of creating many media tasks.
            if len(active) >= 8 or any(job["kind"] == "prepare" for job in active):
                return
            item = self.save(waiting[0] | {"status": "importing", "error": None})
            try:
                result = await self.import_video(item["video_id"], item["options"])
                project = self.store.get("projects", result["project_id"])
                self.save(item | {"status": "submitted", "project_id": result["project_id"],
                                  "title": project.get("title", item["title"]) if project else item["title"]})
            except asyncio.CancelledError:
                self.save(item | {"status": "queued"})
                raise
            except (YouTubeError, HTTPException) as error:
                code = error.status if isinstance(error, YouTubeError) else error.status_code
                transient = code in {401, 429, 502, 503, 504}
                self.save(item | {"status": "queued" if transient else "failed", "retry_at": time.time() + 60,
                                  "error": str(error) if isinstance(error, YouTubeError) else str(error.detail)})
            except Exception:
                self.save(item | {"status": "failed", "error": "未能加入匯入，請重試這部影片。"})

    def public_records(self):
        if not self.records:
            return []
        projects = {item["id"]: item for item in self.store.all("projects")}
        # Store returns newest first, including any manually retried preparation.
        preparing = {}
        for job in self.store.all("jobs"):
            if job["kind"] == "prepare":
                preparing.setdefault(job["project_id"], job)
        account = self.account.status()
        channel_id = (account["channel"] or {}).get("id")
        rows = []
        for item in sorted(self.records.values(), key=lambda entry: (entry["status"] not in WAITING, entry["created"])):
            row = {key: item[key] for key in ("id", "video_id", "title", "channel", "status", "project_id", "error")}
            row["auto_analyze"] = item["options"]["auto_analyze"]
            row["progress"] = 0
            if item["status"] == "queued" and (channel_id != item["channel"]["id"] or account["reconnect_required"] or account["pending"]):
                row["status"] = "waiting_account"
            if item["status"] == "submitted":
                project, job = projects.get(item["project_id"]), preparing.get(item["project_id"])
                if not project:
                    row.update(status="removed", project_id=None)
                elif project.get("ready"):
                    row.update(status="ready", progress=100)
                elif job and job["status"] in {"queued", "running"}:
                    row.update(status="preparing", progress=job.get("progress", 0))
                else:
                    row.update(status="needs_attention", error="下載或預覽尚未完成，請開啟工作區重試。")
            rows.append(row)
        priority = {"importing": 0, "preparing": 0, "queued": 1, "waiting_account": 1, "failed": 2, "needs_attention": 2}
        # Keep the current download visible above even a long waiting list.
        rows.sort(key=lambda row: priority.get(row["status"], 3))
        return rows
