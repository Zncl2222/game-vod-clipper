"""Resumable uploads of completed exports, with durable duplicate prevention."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from .web_store import Store
from .youtube_account import VIDEO_ID, YouTubeAccount, YouTubeError, google_error

UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
BUSY = {"queued", "uploading", "processing", "adding_to_playlist"}
CHUNK = 8 * 1024 * 1024


def file_hash(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


class YouTubeUploads:
    def __init__(self, store: Store, account: YouTubeAccount):
        self.store, self.account = store, account
        self.files = account.files
        self.lock = asyncio.Lock()
        self.limit = asyncio.Semaphore(1)
        self.tasks: dict[str, asyncio.Task] = {}
        # One protected, atomic file per receipt keeps progress writes independent
        # of history size. The in-memory index belongs to this single-server process.
        self.records = {path.stem.removeprefix("upload-"): self.files.read(path.stem)
                        for path in self.files.path.glob("upload-*.json")}
        for key, item in self.files.read("uploads", {}).items():
            if key not in self.records:
                self.save(item)
        # Existing per-record state wins if a previous migration was interrupted.
        self.files.remove("uploads")

    def all(self):
        return {key: dict(item) for key, item in self.records.items()}

    def save(self, item: dict):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item["id"]):
            raise ValueError("Invalid upload record ID")
        self.files.write("upload-" + item["id"], item)
        self.records[item["id"]] = dict(item)
        return item

    def patch(self, key: str, **changes):
        return self.save(self.get(key) | changes)

    def get(self, key: str):
        item = self.records.get(key)
        if not item:
            raise YouTubeError("找不到上傳紀錄。", 404)
        return dict(item)

    def public(self, item: dict):
        keys = {"id", "export_id", "project_id", "channel", "title", "description", "privacy", "status", "progress",
                "error", "video_id", "created", "made_for_kids", "notify_subscribers",
                "playlist_id", "playlist_title", "playlist_status", "playlist_error"}
        return {k: v for k, v in item.items() if k in keys}

    def public_records(self):
        return [self.public(item) for item in sorted(self.records.values(), key=lambda item: item.get("created", 0), reverse=True)]

    def ensure_capacity(self):
        if len(self.tasks) >= 8:
            raise YouTubeError("上傳佇列已滿，請稍後再試。", 429)

    def recover(self):
        for item in self.all().values():
            if item["status"] in BUSY:
                self.patch(item["id"], status="paused", error="服務曾中斷。按「繼續上傳」會先確認 YouTube 的進度。")

    def validate_export(self, export_id: str):
        job = self.store.get("jobs", export_id)
        if not job or job["kind"] != "export" or job["status"] != "succeeded":
            raise YouTubeError("只能上傳已完成匯出的剪輯成品。", 422)
        draft = job.get("draft") or {}
        project = self.store.get("projects", job["project_id"])
        if not project:
            raise YouTubeError("請先檢查剪輯並匯出成品。", 422)
        values = [draft.get(k) for k in ("start", "victory", "postroll")]
        if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
                or not 0 <= values[0] < values[1] or not 5 <= values[2] <= 10
                or values[1] + values[2] > project["duration"]):
            raise YouTubeError("成品的剪輯範圍無效，請重新匯出。", 422)
        if values[1] + values[2] - values[0] >= project["duration"] - 0.3:
            raise YouTubeError("這份成品涵蓋整支原片，請先剪出需要的片段再上傳。", 422)
        expected = self.store.root / "clips" / "web" / project["id"] / f"{export_id}.mp4"
        path = (self.store.root / job.get("output", "")).resolve()
        if (path != expected or not path.is_file() or path.stat().st_size == 0
                or path == (self.store.root / project.get("source", "")).resolve()):
            raise YouTubeError("找不到原本匯出的成品；不會改為上傳來源影片。", 422)
        try:
            receipt = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise YouTubeError("缺少成品驗證紀錄，請重新匯出。", 422) from None
        validation = ("human_reviewed; " if draft.get("reviewed") else "") + "duration_checked; no_automated_visual_validation"
        if (receipt.get("project_id") != project["id"] or receipt.get("draft") != draft
                or receipt.get("output") != str(path.relative_to(self.store.root))
                or receipt.get("validation") != validation):
            raise YouTubeError("成品驗證紀錄不一致，請重新匯出。", 422)
        return job, path

    async def start(self, export_id: str, metadata: dict, channel_id: str):
        async with self.lock:
            channel = self.account.status()["channel"]
            if not channel or channel["id"] != channel_id:
                raise YouTubeError("YouTube 頻道已變更，請重新開啟上傳視窗。", 409)
            if self.account.status()["reconnect_required"]:
                raise YouTubeError("請重新連接 YouTube 帳號。", 401)
            job, path = self.validate_export(export_id)
            digest = await asyncio.to_thread(file_hash, path)
            key = hashlib.sha256(f"{channel_id}:{digest}".encode()).hexdigest()[:32]
            if key in self.records:
                return self.public(self.get(key))
            self.ensure_capacity()
            playlist_id = metadata.get("playlist_id")
            playlist_title = None
            if playlist_id:
                self.account.require_playlist_access()
                playlist = await self.account.owned_playlist(playlist_id, channel_id)
                playlist_title = playlist["snippet"]["title"]
            item = {"id": key, "export_id": export_id, "project_id": job["project_id"], "channel": channel,
                    **metadata, "path": str(path.relative_to(self.store.root)), "sha256": digest, "size": path.stat().st_size,
                    "status": "queued", "progress": 0, "error": None, "created": time.time(), "session": None,
                    "video_id": None, "offset": 0, "playlist_title": playlist_title,
                    "playlist_status": "pending" if playlist_id else None, "playlist_error": None}
            self.save(item)
            self.launch(key)
            return self.public(item)

    def launch(self, key: str):
        task = asyncio.create_task(self.run(key))
        self.tasks[key] = task
        task.add_done_callback(lambda _: self.tasks.pop(key, None))

    async def resume(self, key: str):
        async with self.lock:
            item = self.get(key)
            if item["status"] in {"succeeded", "needs_review"} or key in self.tasks:
                return self.public(item)
            if (self.account.status()["channel"] or {}).get("id") != item["channel"]["id"]:
                raise YouTubeError("請連回原本的 YouTube 頻道後再續傳。", 409)
            self.ensure_capacity()
            self.patch(key, status="queued", error=None)
            self.launch(key)
            return self.public(self.get(key))

    async def pause(self, key: str):
        self.get(key)
        task = self.tasks.get(key)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self.get(key)["status"] in BUSY:
                self.patch(key, status="paused", error="上傳已暫停，可稍後繼續。")
        return self.public(self.get(key))

    async def retry_playlist(self, key: str):
        async with self.lock:
            item = self.get(key)
            if key in self.tasks:
                return self.public(item)
            if not item.get("video_id") or item.get("playlist_status") != "failed" or item["status"] != "succeeded":
                raise YouTubeError("這筆紀錄沒有需要重試的播放清單操作。", 409)
            if (self.account.status()["channel"] or {}).get("id") != item["channel"]["id"]:
                raise YouTubeError("請連回原本的 YouTube 頻道。", 409)
            self.account.require_playlist_access()
            self.ensure_capacity()
            self.patch(key, status="adding_to_playlist", playlist_status="pending", playlist_error=None)
            self.launch(key)
            return self.public(self.get(key))

    async def restart(self, key: str):
        """Only called after the user explicitly checks Studio for an expired session."""
        async with self.lock:
            item = self.get(key)
            if key in self.tasks or item["status"] != "needs_review" or item.get("video_id"):
                raise YouTubeError("這筆上傳不能重新建立，請先確認目前狀態。", 409)
            if (self.account.status()["channel"] or {}).get("id") != item["channel"]["id"]:
                raise YouTubeError("請連回原本的 YouTube 頻道。", 409)
            self.ensure_capacity()
            self.validate_export(item["export_id"])
            attempts = item.get("previous_attempts", []) + [{"session": item["session"], "checked_absent_at": time.time()}]
            self.patch(key, session=None, offset=0, progress=0, status="queued", error=None, previous_attempts=attempts)
            self.launch(key)
            return self.public(self.get(key))

    async def run(self, key: str):
        try:
            async with self.limit:
                item = self.get(key)
                if (self.account.status()["channel"] or {}).get("id") != item["channel"]["id"]:
                    raise YouTubeError("YouTube 頻道已變更，請連回原頻道。", 409)
                if item.get("video_id"):
                    if item.get("video_processed"):
                        await self.finish_playlist(key)
                    else:
                        await self.processing(key)
                    return
                _, path = self.validate_export(item["export_id"])
                if await asyncio.to_thread(file_hash, path) != item["sha256"]:
                    raise YouTubeError("成品檔案已變更，已停止上傳。請重新匯出。", 409)
                self.patch(key, status="uploading", error=None)
                if not item.get("session"):
                    response = await self.account.authorized("POST", UPLOAD,
                        params={"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": str(item["notify_subscribers"]).lower()},
                        headers={"X-Upload-Content-Length": str(item["size"]), "X-Upload-Content-Type": "video/mp4"},
                        json={"snippet": {"title": item["title"], "description": item["description"], "categoryId": "20"},
                              "status": {"privacyStatus": item["privacy"], "selfDeclaredMadeForKids": item["made_for_kids"]}})
                    if response.status_code not in {200, 201}:
                        google_error(response)
                    session = response.headers.get("location", "")
                    parsed = urlparse(session)
                    if (parsed.scheme != "https" or parsed.hostname not in {"www.googleapis.com", "youtube.googleapis.com"}
                            or parsed.username or parsed.password or parsed.port not in {None, 443}
                            or not parsed.path.startswith("/upload/youtube/v3/videos")):
                        raise YouTubeError("YouTube 沒有回傳有效的續傳連線，請重試。", 502)
                    self.patch(key, session=session)
                else:
                    await self.probe_session(key)
                stalls = 0
                with path.open("rb") as source:
                    while not self.get(key).get("video_id"):
                        item = self.get(key)
                        offset = item["offset"]
                        if offset >= item["size"]:
                            raise YouTubeError("檔案已傳送，尚未收到影片編號。請稍後按繼續上傳確認。", 502)
                        source.seek(offset)
                        block = source.read(CHUNK)
                        try:
                            response = await self.account.authorized("PUT", item["session"], content=block,
                                headers={"Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{offset + len(block) - 1}/{item['size']}"})
                            self.accept_response(key, response)
                        except YouTubeError as error:
                            if error.status not in {429, 502} or stalls >= 2:
                                raise
                            stalls += 1
                            await asyncio.sleep(2 ** stalls)
                            await self.probe_session(key)
                        current = self.get(key)
                        if not current.get("video_id") and current["offset"] <= offset:
                            stalls += 1
                            if stalls > 3:
                                raise YouTubeError("YouTube 未接受更多資料，請稍後繼續上傳。", 502)
                        elif current["offset"] > offset:
                            stalls = 0
                await self.processing(key)
        except asyncio.CancelledError:
            self.patch(key, status="paused", error="上傳已暫停，可稍後繼續。")
        except YouTubeError as error:
            if self.get(key)["status"] != "needs_review":
                self.patch(key, status="failed", error=str(error))
        except Exception:
            # Never persist exception text containing session URLs or credential data.
            self.patch(key, status="failed", error="上傳未完成，進度已保留。請重試或檢查成品檔案。")

    async def probe_session(self, key: str):
        item = self.get(key)
        response = await self.account.authorized("PUT", item["session"], content=b"",
                                                headers={"Content-Range": f"bytes */{item['size']}"})
        self.accept_response(key, response)

    def accept_response(self, key: str, response):
        item = self.get(key)
        if response.status_code in {200, 201}:
            data = response.json()
            video_id = data.get("id", "")
            if not VIDEO_ID.fullmatch(video_id):
                raise YouTubeError("YouTube 尚未回傳影片編號，請稍後繼續上傳確認。", 502)
            self.patch(key, video_id=video_id, offset=item["size"], progress=100, status="processing")
        elif response.status_code == 308:
            value = response.headers.get("range", "")
            match = re.fullmatch(r"bytes=0-(\d+)", value)
            offset = int(match[1]) + 1 if match else 0
            if (value and not match) or not 0 <= offset <= item["size"]:
                raise YouTubeError("續傳進度無法確認，請稍後再試。", 502)
            self.patch(key, offset=offset, progress=round(offset / item["size"] * 100, 1))
        elif response.status_code in {404, 410}:
            self.patch(key, status="needs_review", error="續傳連線已過期。請先到 YouTube Studio 確認是否已上傳，避免重複影片。")
            raise YouTubeError("續傳連線已過期。", 409)
        else:
            google_error(response)

    async def processing(self, key: str):
        self.patch(key, status="processing", error=None)
        for _ in range(12):
            item = self.get(key)
            result = await self.account.api("videos", part="status,processingDetails", id=item["video_id"])
            video = next(iter(result.get("items", [])), {})
            status = video.get("status", {})
            state = video.get("processingDetails", {}).get("processingStatus")
            if state in {"failed", "terminated"} or status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
                self.patch(key, status="needs_review", error="YouTube 未完成影片處理，請到 YouTube Studio 查看原因。")
                return
            if state == "succeeded" or status.get("uploadStatus") == "processed":
                self.patch(key, video_processed=True, privacy=status.get("privacyStatus", item["privacy"]), progress=100)
                await self.finish_playlist(key)
                return
            await asyncio.sleep(5)
        self.patch(key, status="paused", error="影片已上傳，YouTube 仍在處理。稍後按繼續上傳只會查詢狀態。")

    async def finish_playlist(self, key: str):
        item = self.get(key)
        if not item.get("playlist_id") or item.get("playlist_status") == "added":
            self.patch(key, status="succeeded", error=None)
            return
        self.patch(key, status="adding_to_playlist", error=None, playlist_status="adding", playlist_error=None)
        try:
            await self.account.add_to_playlist(item["playlist_id"], item["video_id"], item["channel"]["id"])
        except YouTubeError as error:
            self.patch(key, status="succeeded", playlist_status="failed", playlist_error=str(error))
        except Exception:
            self.patch(key, status="succeeded", playlist_status="failed", playlist_error="無法確認播放清單結果，請重試加入。")
        else:
            self.patch(key, status="succeeded", playlist_status="added", playlist_error=None)

    async def close(self):
        for key in list(self.tasks):
            await self.pause(key)
