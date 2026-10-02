"""User-owned Google OAuth and YouTube metadata; no source-media upload here."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

SCOPES = {"https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/youtube.upload"}
PLAYLIST_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{1,150}\Z")
API = "https://www.googleapis.com/youtube/v3/"
TOKEN = "https://oauth2.googleapis.com/token"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class YouTubeError(Exception):
    def __init__(self, message: str, status: int = 400, *, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class PrivateFiles:
    """Atomic, owner-only local state, excluded from source control and HTTP serving."""

    def __init__(self, root: Path):
        self.path = root / "runs" / "web" / "youtube"
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.chmod(0o700)

    def read(self, name: str, default=None):
        path = self.path / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write(self, name: str, value):
        path = self.path / f"{name}.json"
        temporary = self.path / f".{secrets.token_hex(12)}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self, name: str):
        (self.path / f"{name}.json").unlink(missing_ok=True)


def google_error(response: httpx.Response):
    """Do not surface provider payloads, tokens, authorization codes or upload URLs."""
    reasons = set()
    try:
        data = response.json()
        detail = data.get("error", {})
        if isinstance(detail, str):
            reasons.add(detail)
        elif isinstance(detail, dict):
            # Google uses both the legacy errors list and google.rpc.ErrorInfo.
            for field in ("errors", "details"):
                entries = detail.get(field, [])
                if isinstance(entries, list):
                    reasons.update(entry["reason"] for entry in entries if isinstance(entry, dict)
                                   and isinstance(entry.get("reason"), str))
    except (ValueError, AttributeError, TypeError):
        pass
    if any("quota" in reason.lower() for reason in reasons) or response.status_code == 429:
        raise YouTubeError("YouTube 額度暫時用完，請稍後再試。已完成的工作會保留。", 429)
    if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
        raise YouTubeError("請在產生 OAuth 設定檔的同一個 Google Cloud 專案啟用 YouTube Data API v3，再重新整理。", 422,
                           code="accessNotConfigured")
    if "liveStreamingNotEnabled" in reasons:
        raise YouTubeError("目前連接的 YouTube 頻道尚未啟用直播，Google 無法提供直播存檔清單。"
                           "請確認選到平常直播的頻道，或到 YouTube 完成直播啟用；首次啟用最多可能需要 24 小時。", 403,
                           code="liveStreamingNotEnabled")
    if "insufficientLivePermissions" in reasons:
        raise YouTubeError("目前授權無法讀取這個頻道的直播。請確認連接的是擁有直播存檔的頻道，"
                           "再由「帳號選項」中斷連接並重新授權。", 403, code="insufficientLivePermissions")
    if reasons & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
        raise YouTubeError("YouTube 授權缺少這項操作所需的權限。請中斷連接後重新登入，"
                           "同意操作需要的 YouTube 權限；加入清單請使用「授權播放清單」。", 403, code="insufficientPermissions")
    if reasons & {"playlistNotFound", "playlistForbidden", "playlistItemsNotAccessible", "playlistOperationUnsupported"}:
        raise YouTubeError("這個播放清單已不存在或無法編輯，請到 YouTube 確認清單與頻道權限。", 422)
    if "playlistContainsMaximumNumberOfVideos" in reasons:
        raise YouTubeError("播放清單已滿，請先在 YouTube 整理清單後重試。", 422)
    if "youtubeSignupRequired" in reasons:
        raise YouTubeError("這個 Google 帳號尚未建立 YouTube 頻道。請先在 YouTube 建立頻道，或重新登入並選擇已有的頻道。", 403,
                           code="youtubeSignupRequired")
    if response.status_code == 401 or "invalid_grant" in reasons:
        raise YouTubeError("YouTube 授權已失效，請重新連接帳號。", 401)
    if response.status_code == 403:
        raise YouTubeError("YouTube 未允許此操作。請確認授權範圍、頻道權限與 API 設定。", 403)
    raise YouTubeError("YouTube 暫時無法完成請求，請稍後重試。", 502)


class YouTubeAccount:
    def __init__(self, root: Path, client: httpx.AsyncClient | None = None):
        self.files = PrivateFiles(root)
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.pending: dict | None = None
        self.error: str | None = None
        self.lock = asyncio.Lock()

    def status(self):
        account = self.files.read("account", {})
        if self.pending and self.pending["expires"] < time.time() and not self.pending.get("exchanging"):
            self.pending = None
            self.error = "登入已逾時，請重新連接 YouTube。"
        return {"configured": bool(self.files.read("client")), "connected": bool(account.get("channel")),
                "channel": account.get("channel"), "pending": bool(self.pending), "error": self.error,
                "reconnect_required": bool(account.get("reconnect_required")),
                "playlist_write_enabled": PLAYLIST_SCOPE in account.get("scopes", [])}

    def configure(self, config: dict):
        if self.status()["connected"] or self.pending:
            raise YouTubeError("請先取消登入或中斷 YouTube 連接，再更換設定。", 409)
        if len(json.dumps(config)) > 32_000:
            raise YouTubeError("設定檔過大，請選擇 Google 下載的 OAuth JSON。", 422)
        kind = "installed" if "installed" in config else "web"
        data = config.get(kind)
        if (not isinstance(data, dict) or not isinstance(data.get("client_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+\.apps\.googleusercontent\.com", data["client_id"])
                or not isinstance(data.get("client_secret"), str) or not 1 <= len(data["client_secret"]) <= 4096):
            raise YouTubeError("這不是 Google OAuth 用戶端設定檔。請選擇桌面應用程式或網頁應用程式的 JSON。", 422)
        self.files.write("client", {"kind": kind, "client_id": data["client_id"], "client_secret": data["client_secret"]})
        self.error = None

    def begin(self, redirect_uri: str, *, playlists: bool = False):
        config = self.files.read("client")
        if not config:
            raise YouTubeError("請先選擇 Google OAuth 設定檔。", 422)
        if self.pending and self.pending["expires"] > time.time():
            raise YouTubeError("已有登入視窗，請完成登入或先取消。", 409)
        parsed = urlparse(redirect_uri)
        if config["kind"] == "installed" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise YouTubeError("桌面 OAuth 需用 localhost 開啟工作區；遠端網址請改用網頁 OAuth，並登記下方的回呼網址。", 422)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        self.pending = {"state": state, "verifier": verifier, "redirect_uri": redirect_uri, "expires": time.time() + 600}
        self.error = None
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        query = {"client_id": config["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
                 "scope": " ".join(sorted(SCOPES | ({PLAYLIST_SCOPE} if playlists or self.status()["playlist_write_enabled"] else set()))),
                 "access_type": "offline", "prompt": "consent",
                 "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(query), "state": state}

    async def complete(self, state: str, cookie: str, code: str, denied: bool = False):
        async with self.lock:
            pending = self.pending
            if (not pending or pending["expires"] < time.time() or not state or not cookie
                    or not secrets.compare_digest(state, pending["state"]) or not secrets.compare_digest(cookie, state)):
                raise YouTubeError("登入驗證已失效。請回到原本的工作區重新連接。", 400)
            if denied or not code:
                self.pending = None
                self.error = "你已取消 Google 授權，可以隨時重新連接。"
                raise YouTubeError(self.error)
            # Keep the public pending state until channel discovery finishes, so
            # the browser does not stop polling in the middle of the exchange.
            pending["exchanging"] = True
            try:
                await self.exchange(pending, code)
            finally:
                self.pending = None  # One use, also on failure/cancellation.

    async def exchange(self, pending: dict, code: str):
        config = self.files.read("client")
        response = await self.request("POST", TOKEN, data={"client_id": config["client_id"],
            "client_secret": config["client_secret"], "code": code, "grant_type": "authorization_code",
            "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"]})
        if response.status_code != 200:
            google_error(response)
        token = response.json()
        if not SCOPES.issubset(set(token.get("scope", "").split())) or not token.get("refresh_token"):
            raise YouTubeError("請同意讀取 YouTube 資料和上傳影片兩項權限，再重新連接。", 403)
        channels = await self.request("GET", API + "channels", params={"part": "snippet", "mine": "true"},
                                      headers={"Authorization": "Bearer " + token["access_token"]})
        if channels.status_code != 200:
            google_error(channels)
        items = channels.json().get("items", [])
        if len(items) != 1:
            raise YouTubeError("請在 Google 登入時選擇一個已建立的 YouTube 頻道。", 422)
        item = items[0]
        self.files.write("account", {"access_token": token["access_token"], "refresh_token": token["refresh_token"],
            "expires": time.time() + float(token.get("expires_in", 3600)),
            "scopes": token.get("scope", "").split(),
            "channel": {"id": item["id"], "title": item["snippet"]["title"]}})
        self.error = None

    async def request(self, method: str, url: str, **kwargs):
        try:
            return await self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise YouTubeError("無法連接 YouTube，請檢查網路後重試。", 502) from None

    async def access_token(self, force: bool = False):
        async with self.lock:
            data = self.files.read("account", {})
            if not data.get("refresh_token") or data.get("reconnect_required"):
                raise YouTubeError("請先連接 YouTube 帳號。", 401)
            if force or data["expires"] < time.time() + 60:
                config = self.files.read("client")
                response = await self.request("POST", TOKEN, data={"client_id": config["client_id"],
                    "client_secret": config["client_secret"], "refresh_token": data["refresh_token"], "grant_type": "refresh_token"})
                if response.status_code != 200:
                    if response.status_code in {400, 401}:
                        self.files.write("account", data | {"reconnect_required": True})
                    google_error(response)
                token = response.json()
                data.update(access_token=token["access_token"], expires=time.time() + float(token.get("expires_in", 3600)))
                if "scope" in token:
                    data["scopes"] = token["scope"].split()
                self.files.write("account", data)
            return data["access_token"]

    async def authorized(self, method: str, url: str, **kwargs):
        headers = kwargs.pop("headers", {})
        for attempt in range(2):
            token = await self.access_token(force=bool(attempt))
            response = await self.request(method, url, headers={**headers, "Authorization": "Bearer " + token}, **kwargs)
            if response.status_code != 401:
                return response
        google_error(response)

    async def api(self, resource: str, **params):
        response = await self.authorized("GET", API + resource, params=params)
        if response.status_code != 200:
            google_error(response)
        return response.json()

    def require_playlist_access(self):
        if not self.status()["playlist_write_enabled"]:
            raise YouTubeError("請先按「授權播放清單」，同意管理播放清單的權限。仍可選擇不加入清單直接上傳。", 403,
                               code="playlistPermissionRequired")

    async def playlists(self, channel_id: str, page_token: str = ""):
        result = await self.api("playlists", part="snippet,status,contentDetails", mine="true", maxResults=50,
                                **({"pageToken": page_token} if page_token else {}))
        return {"items": [{"id": item["id"], "title": item["snippet"]["title"],
                           "privacy": item.get("status", {}).get("privacyStatus", "private"),
                           "count": item.get("contentDetails", {}).get("itemCount", 0)}
                          for item in result.get("items", []) if item.get("snippet", {}).get("channelId") == channel_id],
                "next_page_token": result.get("nextPageToken", "")}

    async def owned_playlist(self, playlist_id: str, channel_id: str):
        if not PLAYLIST_ID.fullmatch(playlist_id):
            raise YouTubeError("播放清單編號無效。", 422)
        result = await self.api("playlists", part="snippet", id=playlist_id)
        item = next((item for item in result.get("items", []) if item.get("id") == playlist_id), None)
        if not item or item.get("snippet", {}).get("channelId") != channel_id:
            raise YouTubeError("請選擇目前 YouTube 頻道擁有的播放清單，或重新整理清單。", 422)
        return item

    async def add_to_playlist(self, playlist_id: str, video_id: str, channel_id: str):
        self.require_playlist_access()
        await self.owned_playlist(playlist_id, channel_id)
        # Check before every insertion, including retries after a lost response.
        existing = await self.api("playlistItems", part="id", playlistId=playlist_id, videoId=video_id, maxResults=1)
        if existing.get("items"):
            return
        response = await self.authorized("POST", API + "playlistItems", params={"part": "snippet"},
            json={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        if response.status_code not in {200, 201}:
            google_error(response)
        if not response.json().get("id"):
            raise YouTubeError("尚未確認加入播放清單的結果，請稍後重試。", 502)

    async def broadcasts(self, page_token: str = ""):
        result = await self.api("liveBroadcasts", part="snippet,status", broadcastStatus="completed", broadcastType="all",
                                maxResults=25, **({"pageToken": page_token} if page_token else {}))
        items = result.get("items", [])
        videos = await self.api("videos", part="contentDetails,status,liveStreamingDetails", id=",".join(i["id"] for i in items)) if items else {}
        details = {v["id"]: v for v in videos.get("items", [])}
        channel = self.status()["channel"]
        rows = []
        for item in items:
            snippet = item["snippet"]
            if snippet.get("channelId") != channel["id"] or not VIDEO_ID.fullmatch(item["id"]):
                continue
            video = details.get(item["id"], {})
            status = video.get("status", {})
            duration = iso_duration(video.get("contentDetails", {}).get("duration", ""))
            reason = ("私人影片請改用本機錄影" if status.get("privacyStatus") == "private" else
                      "直播存檔仍在處理，請稍後重新整理" if not duration or status.get("uploadStatus") != "processed" else
                      "目前支援 10 秒至 6 小時，請改用分段錄影" if not 10 <= duration <= 21600 else "")
            rows.append({"id": item["id"], "title": snippet.get("title", "未命名直播"), "duration": duration,
                "ended_at": snippet.get("actualEndTime", ""), "privacy": status.get("privacyStatus", "unknown"),
                "available": not reason, "reason": reason})
        return {"items": rows, "next_page_token": result.get("nextPageToken", "")}

    async def disconnect(self):
        async with self.lock:
            data = self.files.read("account", {})
            self.pending = None
            self.files.remove("account")
            self.error = None
            # Local access ends even if Google's revocation service is unavailable.
            if data.get("refresh_token"):
                try:
                    response = await self.request("POST", "https://oauth2.googleapis.com/revoke", data={"token": data["refresh_token"]})
                    if response.status_code != 200:
                        raise YouTubeError("revocation incomplete")
                except YouTubeError:
                    return "本機連接已移除；遠端撤銷未完成，可至 Google 帳號的第三方連線移除授權。"
        return "已中斷 YouTube 連接。"

    async def close(self):
        await self.client.aclose()


def iso_duration(value: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    return sum(int(n or 0) * unit for n, unit in zip(match.groups(), (86400, 3600, 60, 1))) if match else 0
