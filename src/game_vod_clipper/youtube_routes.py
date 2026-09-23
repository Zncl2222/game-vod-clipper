"""YouTube workspace routes and an opt-in watcher that stops at human review."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .youtube_account import VIDEO_ID, YouTubeAccount, YouTubeError, iso_duration
from .youtube_imports import YouTubeImports
from .youtube_uploads import YouTubeUploads
from .youtube import DownloadQuality

ACTIVE = {"queued", "running"}


class ImportBroadcast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str = Field(min_length=1, max_length=100)
    auto_analyze: bool = True
    model: str = Field(default="", max_length=120)
    download_quality: DownloadQuality = "best"


class WatchSettings(ImportBroadcast):
    enabled: bool


class ImportChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(default="YouTube 直播", min_length=1, max_length=200)


class ImportBatch(ImportBroadcast):
    videos: list[ImportChoice] = Field(min_length=1, max_length=100)


class UploadClip(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    channel_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    privacy: Literal["private", "unlisted", "public"] = "private"
    made_for_kids: bool
    notify_subscribers: bool = False
    playlist_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,150}$")

    @field_validator("title", "description")
    @classmethod
    def valid_metadata(cls, value):
        if "<" in value or ">" in value or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("標題與說明不可包含角括號或控制字元。")
        if len(value.encode("utf-8")) > 5000:
            raise ValueError("說明過長，請縮短至 5000 位元組內。")
        return value


class RestartUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed_no_video: Literal[True]


class OAuthLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].startswith("/api/youtube/callback"):
                args[2] = "/api/youtube/callback"
                record.args = tuple(args)
        return True


class YouTubeWorkspace:
    def __init__(self, store, import_source, analyze, check_model):
        self.store = store
        self.import_source, self.analyze, self.check_model = import_source, analyze, check_model
        self.account = YouTubeAccount(store.root)
        self.uploads = YouTubeUploads(store, self.account)
        self.lock = asyncio.Lock()
        self.imports = YouTubeImports(store, self.account, self.lock,
                                      lambda key, options: self._import_video(key, ImportBroadcast(**options)))
        self.sync_lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.stopped = asyncio.Event()

    def preferences(self):
        defaults = {"enabled": False, "auto_analyze": True, "model": "", "download_quality": "best", "since": 0,
                    "last_checked": None, "error": None}
        return defaults | self.account.files.read("watch", {})

    def status(self):
        return {**self.account.status(), "watch": self.preferences(),
                "uploads": self.uploads.public_records(), "imports": self.imports.public_records()}

    def ensure_channel(self, channel_id: str):
        channel = self.account.status()["channel"]
        if not channel or channel["id"] != channel_id:
            raise YouTubeError("YouTube 頻道已變更，請重新整理清單。", 409)
        return channel

    def ensure_idle(self):
        if self.uploads.tasks:
            raise YouTubeError("請先暫停上傳，再變更 YouTube 連接。", 409)

    def imported_project(self, video_id: str):
        return next((p for p in self.store.all("projects") if p.get("youtube_video_id") == video_id
                     or p.get("url") == f"https://www.youtube.com/watch?v={video_id}"), None)

    async def broadcasts(self, token=""):
        result = await self.account.broadcasts(token)
        by_url = {}
        for project in self.store.all("projects"):
            if project.get("youtube_video_id"):
                by_url.setdefault(f"https://www.youtube.com/watch?v={project['youtube_video_id']}", project)
            if project.get("url"):
                by_url.setdefault(project["url"], project)
        for item in result["items"]:
            project = by_url.get(f"https://www.youtube.com/watch?v={item['id']}")
            item["project_id"] = project["id"] if project else None
        return result

    def watch_is_current(self, settings: dict):
        current = self.preferences()
        return current["enabled"] and all(current.get(key) == settings.get(key)
                                          for key in ("generation", "channel_id", "since"))

    async def import_video(self, video_id: str, options: ImportBroadcast, *, watch_settings: dict | None = None):
        if not VIDEO_ID.fullmatch(video_id):
            raise YouTubeError("影片編號無效。", 422)
        async with self.lock:
            # Disabling/changing the watcher must win before any queued import
            # acquires this lock and starts a download.
            if watch_settings is not None and not self.watch_is_current(watch_settings):
                return None
            return await self._import_video(video_id, options)

    async def _import_video(self, video_id: str, options: ImportBroadcast):
        """Validate and import while the caller holds the workspace lock."""
        self.ensure_channel(options.channel_id)
        existing = self.imported_project(video_id)
        if existing:
            return {"project_id": existing["id"], "existing": True}
        if options.auto_analyze:
            await self.check_model(options.model)
        response = await self.account.api("videos", part="snippet,status,contentDetails,liveStreamingDetails", id=video_id)
        item = next(iter(response.get("items", [])), {})
        if item.get("snippet", {}).get("channelId") != options.channel_id:
            raise YouTubeError("只能從已連接頻道匯入自己的直播。", 422)
        status = item.get("status", {})
        if status.get("privacyStatus") == "private":
            raise YouTubeError("私人直播目前請使用本機錄影匯入。", 422)
        if (not item.get("liveStreamingDetails", {}).get("actualEndTime") or status.get("uploadStatus") != "processed"):
            raise YouTubeError("請等直播結束、存檔處理完成後再匯入。", 422)
        if not 10 <= iso_duration(item.get("contentDetails", {}).get("duration", "")) <= 21600:
            raise YouTubeError("目前支援 10 秒至 6 小時的直播存檔。", 422)
        result = await self.import_source(video_id, options.download_quality)
        project_id = result["project"]["id"]
        self.store.patch("projects", project_id, title=item["snippet"].get("title", "YouTube 直播"),
            youtube_video_id=video_id, youtube_channel_id=options.channel_id,
            youtube_analysis_state="waiting" if options.auto_analyze else "manual", youtube_model=options.model)
        history = self.account.files.read("imports", {})
        history[f"{options.channel_id}:{video_id}"] = project_id
        self.account.files.write("imports", history)
        return {"project_id": project_id, "existing": False}

    async def set_watch(self, options: WatchSettings):
        async with self.lock:
            self.ensure_channel(options.channel_id)
            if options.enabled and options.auto_analyze:
                await self.check_model(options.model)
            previous = self.preferences()
            # Enabling starts with future completions, never the entire back catalog.
            since = previous["since"] if previous["enabled"] and previous.get("channel_id") == options.channel_id else time.time()
            settings = {**previous, **options.model_dump(), "since": since, "error": None,
                        "generation": previous.get("generation", 0) + 1,
                        "cursor": previous.get("cursor", "") if previous["enabled"] else ""}
            self.account.files.write("watch", settings)
            return settings

    async def sync(self):
        if self.sync_lock.locked():
            return self.preferences()
        async with self.sync_lock:
            settings = self.preferences()
            if not settings["enabled"]:
                return settings
            try:
                async with self.lock:
                    if not self.watch_is_current(settings):
                        return self.preferences()
                    self.ensure_channel(settings["channel_id"])
                    token = settings.get("cursor", "")
                    result = await self.broadcasts(token)
                for item in result["items"]:
                    if not self.watch_is_current(settings):
                        break
                    try:
                        ended = datetime.fromisoformat(item["ended_at"].replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        continue
                    seen = f"{settings['channel_id']}:{item['id']}" in self.account.files.read("imports", {})
                    if ended < settings["since"] or not item["available"] or seen or item["project_id"]:
                        continue
                    if sum(j["status"] in ACTIVE and j["kind"] == "analyze" for j in self.store.all("jobs")) >= 8:
                        # Revisit this page instead of skipping unqueued videos.
                        raise YouTubeError("工作佇列已滿，下一次檢查會接著匯入。", 429)
                    imported = await self.import_video(item["id"], ImportBroadcast(**{k: settings[k] for k in ("channel_id", "auto_analyze", "model", "download_quality")}),
                                                       watch_settings=settings)
                    if imported is None:
                        break
                current = self.preferences()
                if self.watch_is_current(settings):
                    self.account.files.write("watch", current | {"last_checked": time.time(), "error": None, "cursor": result["next_page_token"]})
            except (YouTubeError, HTTPException) as error:
                if self.watch_is_current(settings):
                    self.account.files.write("watch", self.preferences() | {"last_checked": time.time(),
                        "error": str(error) if isinstance(error, YouTubeError) else str(error.detail)})
            return self.preferences()

    async def advance(self):
        for project in self.store.all("projects"):
            if not project.get("ready") or project.get("youtube_analysis_state") != "waiting":
                continue
            if sum(j["status"] in ACTIVE and j["kind"] == "analyze" for j in self.store.all("jobs")) >= 8:
                break
            # Persist before awaiting dispatch; its deterministic request ID prevents duplicates.
            self.store.patch("projects", project["id"], youtube_analysis_state="starting")
            try:
                job = await self.analyze(project, project["youtube_model"], "youtube-import:" + project["id"])
                self.store.patch("projects", project["id"], youtube_analysis_state="queued", youtube_analysis_job=job["id"])
            except Exception:
                if self.store.get("projects", project["id"]):
                    self.store.patch("projects", project["id"], youtube_analysis_state="needs_attention",
                                     youtube_analysis_error="自動搜尋未能啟動。請在工作區確認 AI 連線後，按搜尋成功挑戰。")

    async def loop(self):
        while not self.stopped.is_set():
            try:
                await self.imports.advance()
                await self.advance()
                watch = self.preferences()
                if watch["enabled"] and time.time() - (watch["last_checked"] or 0) >= (30 if watch.get("cursor") else 600):
                    await self.sync()
            except asyncio.CancelledError:
                return
            except Exception:
                self.account.files.write("watch", self.preferences() | {"error": "背景同步暫時中斷，請重新整理或稍後再試。", "last_checked": time.time()})
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=3)
            except TimeoutError:
                pass

    def start(self):
        self.uploads.recover()
        self.imports.recover()
        for project in self.store.all("projects"):
            if project.get("youtube_analysis_state") == "starting":
                self.store.patch("projects", project["id"], youtube_analysis_state="waiting")
        self.stopped.clear()
        self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.stopped.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.uploads.close()
        await self.account.close()

    def mount(self, app):
        access_logger = logging.getLogger("uvicorn.access")
        if not any(isinstance(f, OAuthLogFilter) for f in access_logger.filters):
            access_logger.addFilter(OAuthLogFilter())

        @app.exception_handler(YouTubeError)
        async def error_handler(request, error):
            return JSONResponse({"detail": str(error), "code": error.code}, status_code=error.status)

        @app.get("/api/youtube")
        async def status():
            return self.status()

        @app.put("/api/youtube/config")
        async def configure(request: Request):
            raw = await request.body()
            if len(raw) > 32_000:
                raise YouTubeError("設定檔過大。", 422)
            try:
                config = await request.json()
            except ValueError:
                raise YouTubeError("請選擇有效的 Google OAuth JSON 設定檔。", 422) from None
            if not isinstance(config, dict):
                raise YouTubeError("請選擇 Google OAuth JSON 設定檔。", 422)
            async with self.lock:
                self.ensure_idle()
                self.account.configure(config)
            return self.status()

        @app.post("/api/youtube/login")
        async def login(request: Request, playlists: bool = False):
            async with self.lock:
                self.ensure_idle()
                origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
                parsed = urlparse(origin)
                if parsed.scheme not in {"http", "https"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
                    raise YouTubeError("工作區網址無效。", 422)
                result = self.account.begin(origin.rstrip("/") + "/api/youtube/callback", playlists=playlists)
                response = JSONResponse({"url": result["url"]})
                response.set_cookie("bosscut_youtube_state", result["state"], httponly=True, samesite="lax",
                                    secure=parsed.scheme == "https", max_age=600, path="/api/youtube/callback")
                return response

        @app.post("/api/youtube/login/cancel")
        async def cancel_login():
            async with self.lock:
                self.account.pending = None
            return self.status()

        @app.get("/api/youtube/callback")
        async def callback(request: Request):
            try:
                async with self.lock:
                    self.ensure_idle()
                    await self.account.complete(request.query_params.get("state", ""), request.cookies.get("bosscut_youtube_state", ""),
                                                request.query_params.get("code", ""), "error" in request.query_params)
                    watch = self.preferences()
                    if watch.get("channel_id") != self.account.status()["channel"]["id"]:
                        self.account.files.write("watch", watch | {"enabled": False})
                message = "YouTube 已連接。回到原本的 BossCut 視窗即可選擇直播。"
                code = 200
            except YouTubeError as error:
                message, code = str(error), error.status
                self.account.error = message
            response = HTMLResponse('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                '<title>YouTube 連接 · BossCut</title><body><main><h1>YouTube 帳號連接</h1><p>' + html.escape(message) +
                '</p><a href="/">返回 BossCut 工作區</a></main></body></html>', status_code=code,
                headers={"Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            if not self.account.pending:
                response.delete_cookie("bosscut_youtube_state", path="/api/youtube/callback")
            return response

        @app.post("/api/youtube/disconnect")
        async def disconnect():
            async with self.lock:
                self.ensure_idle()
                self.account.files.write("watch", self.preferences() | {"enabled": False})
                message = await self.account.disconnect()
            return {**self.status(), "message": message}

        @app.get("/api/youtube/broadcasts")
        async def broadcasts(page_token: str = ""):
            if len(page_token) > 2000:
                raise YouTubeError("分頁參數無效。", 422)
            async with self.lock:
                return await self.broadcasts(page_token)

        @app.post("/api/youtube/broadcasts/{video_id}/import", status_code=202)
        async def import_broadcast(video_id: str, body: ImportBroadcast):
            return await self.import_video(video_id, body)

        @app.post("/api/youtube/imports", status_code=202)
        async def import_batch(body: ImportBatch):
            async with self.lock:
                channel = self.ensure_channel(body.channel_id)
                if self.account.pending or self.account.status()["reconnect_required"]:
                    raise YouTubeError("請先完成 YouTube 帳號連接，再加入匯入佇列。", 409)
                if body.auto_analyze:
                    await self.check_model(body.model)
                result = self.imports.add([video.model_dump() for video in body.videos],
                                          body.model_dump(exclude={"videos"}), channel)
                return {**result, "items": self.imports.public_records()}

        @app.post("/api/youtube/imports/{import_id}/cancel")
        async def cancel_import(import_id: str):
            async with self.lock:
                self.imports.cancel(import_id)
                return self.status()

        @app.post("/api/youtube/imports/{import_id}/retry")
        async def retry_import(import_id: str):
            async with self.lock:
                item = self.imports.get(import_id)
                self.ensure_channel(item["channel"]["id"])
                self.imports.retry(import_id)
                return self.status()

        @app.put("/api/youtube/watch")
        async def watch(body: WatchSettings):
            return await self.set_watch(body)

        @app.post("/api/youtube/sync")
        async def sync():
            return await self.sync()

        @app.get("/api/youtube/uploads")
        async def uploads():
            return self.uploads.public_records()

        @app.get("/api/youtube/playlists")
        async def playlists(channel_id: str, page_token: str = ""):
            if len(page_token) > 2000:
                raise YouTubeError("分頁參數無效。", 422)
            async with self.lock:
                self.ensure_channel(channel_id)
                if self.account.pending:
                    raise YouTubeError("請先完成或取消 YouTube 授權。", 409)
                return await self.account.playlists(channel_id, page_token)

        @app.post("/api/youtube/uploads/{upload_id}/playlist/retry")
        async def retry_playlist(upload_id: str):
            async with self.lock:
                if self.account.pending:
                    raise YouTubeError("請先完成或取消 YouTube 授權。", 409)
                return await self.uploads.retry_playlist(upload_id)

        @app.post("/api/youtube/uploads/{export_id}", status_code=202)
        async def upload(export_id: str, body: UploadClip):
            async with self.lock:
                if self.account.pending:
                    raise YouTubeError("請先完成或取消 YouTube 登入，再上傳。", 409)
                return await self.uploads.start(export_id, body.model_dump(exclude={"channel_id"}), body.channel_id)

        @app.post("/api/youtube/uploads/{upload_id}/resume")
        async def resume(upload_id: str):
            async with self.lock:
                if self.account.pending:
                    raise YouTubeError("請先完成或取消 YouTube 登入。", 409)
                return await self.uploads.resume(upload_id)

        @app.post("/api/youtube/uploads/{upload_id}/pause")
        async def pause(upload_id: str):
            return await self.uploads.pause(upload_id)

        @app.post("/api/youtube/uploads/{upload_id}/restart")
        async def restart(upload_id: str, body: RestartUpload):
            async with self.lock:
                if self.account.pending:
                    raise YouTubeError("請先完成或取消 YouTube 登入。", 409)
                return await self.uploads.restart(upload_id)
