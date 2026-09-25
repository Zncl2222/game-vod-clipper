"""Offline Google protocol, export boundaries, queue and account-isolation checks."""

import asyncio
import json
import stat
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app
from game_vod_clipper.web_store import Store
from game_vod_clipper.youtube_account import API, SCOPES, YouTubeAccount, YouTubeError, google_error
from game_vod_clipper.youtube_routes import ImportBroadcast, WatchSettings, YouTubeWorkspace
from game_vod_clipper.youtube_uploads import UPLOAD, YouTubeUploads

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"web": {"client_id": "test.apps.googleusercontent.com", "client_secret": "test-secret"}}
CHANNEL = {"id": "channel-a", "title": "我的遊戲頻道"}
VIDEO = "abcdefghijk"


def account_data():
    return {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires": time.time() + 3600, "channel": CHANNEL}


def video(**changes):
    return {"id": VIDEO, "snippet": {"channelId": CHANNEL["id"], "title": "直播測試"},
            "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"},
            "contentDetails": {"duration": "PT1H"}, "liveStreamingDetails": {"actualEndTime": "2026-09-20T10:00:00Z"}, **changes}


class RouteTest(unittest.TestCase):
    def test_playlist_pages_require_current_channel_and_filter_foreign_playlists(self):
        self.account.files.write("account", account_data())
        items = [{"id": "PLmine", "snippet": {"channelId": CHANNEL["id"], "title": "Boss 勝利"},
                  "status": {"privacyStatus": "private"}, "contentDetails": {"itemCount": 8}},
                 {"id": "PLforeign", "snippet": {"channelId": "another", "title": "其他頻道"}}]
        with patch.object(self.account, "api", AsyncMock(return_value={"items": items, "nextPageToken": "page-two"})) as call:
            response = self.client.get("/api/youtube/playlists", params={"channel_id": CHANNEL["id"], "page_token": "page-one"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"items": [{"id": "PLmine", "title": "Boss 勝利", "privacy": "private", "count": 8}],
                                               "next_page_token": "page-two"})
            self.assertEqual(call.call_args.kwargs["mine"], "true")
            self.assertEqual(call.call_args.kwargs["pageToken"], "page-one")
            self.assertEqual(self.client.get("/api/youtube/playlists", params={"channel_id": "another"}).status_code, 409)
            self.assertEqual(call.call_count, 1)
        self.assertEqual(self.client.post("/api/youtube/uploads/source", json={"channel_id": CHANNEL["id"],
            "title": "Clip", "made_for_kids": False, "playlist_id": "../bad"}).status_code, 422)

    def test_playlist_authorization_is_optional_and_granted_scopes_are_persisted(self):
        from game_vod_clipper.youtube_account import PLAYLIST_SCOPE
        self.account.configure(CONFIG)
        plain = self.client.post("/api/youtube/login").json()["url"]
        self.assertNotIn(PLAYLIST_SCOPE, parse_qs(urlparse(plain).query)["scope"][0].split())
        self.client.post("/api/youtube/login/cancel")
        enabled = self.client.post("/api/youtube/login?playlists=true").json()["url"]
        query = parse_qs(urlparse(enabled).query)
        self.assertIn(PLAYLIST_SCOPE, query["scope"][0].split())
        async def handler(request):
            if request.url.path == "/token":
                return httpx.Response(200, json={"access_token": "secret", "refresh_token": "secret", "expires_in": 3600,
                    "scope": " ".join(SCOPES | {PLAYLIST_SCOPE})})
            return httpx.Response(200, json={"items": [{"id": CHANNEL["id"], "snippet": {"title": CHANNEL["title"]}}]})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = self.client.get("/api/youtube/callback", params={"state": query["state"][0], "code": "code"})
        self.assertEqual(response.status_code, 200)
        status = self.client.get("/api/youtube").json()
        self.assertTrue(status["playlist_write_enabled"])
        self.assertNotIn("secret", json.dumps(status))
        self.assertIn(PLAYLIST_SCOPE, self.account.files.read("account")["scopes"])

    def setUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="youtube-test-")
        self.root = Path(self.tmp.name)
        self.app = create_app(self.root)
        self.account = self.app.state.youtube.account
        self.requests = []

        def handler(request):
            self.requests.append(request)
            if request.url.path == "/token":
                return httpx.Response(200, json={"access_token": "access-secret", "refresh_token": "refresh-secret",
                    "expires_in": 3600, "scope": " ".join(SCOPES)})
            if request.url.path.endswith("/channels"):
                return httpx.Response(200, json={"items": [{"id": CHANNEL["id"], "snippet": {"title": CHANNEL["title"]}}]})
            if request.url.path.endswith("/videos"):
                return httpx.Response(200, json={"items": [video()]})
            return httpx.Response(200, json={})

        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_oauth_pkce_cookie_state_replay_and_secret_redaction(self):
        self.assertEqual(self.client.put("/api/youtube/config", json=CONFIG).status_code, 200)
        response = self.client.post("/api/youtube/login", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200, response.text)
        params = parse_qs(urlparse(response.json()["url"]).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["redirect_uri"], ["http://testserver/api/youtube/callback"])
        self.assertEqual(self.client.post("/api/youtube/login").status_code, 409)
        bad = self.client.get("/api/youtube/callback?state=wrong&code=code-secret", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.requests, [])
        # Bad callbacks cannot be used without the original browser's cookie.
        self.client.cookies.set("bosscut_youtube_state", params["state"][0], path="/api/youtube/callback")
        url = "/api/youtube/callback?state=" + params["state"][0] + "&code=code-secret"
        good = self.client.get(url, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(good.status_code, 200, good.text)
        public = self.client.get("/api/youtube").json()
        self.assertTrue(public["connected"])
        self.assertEqual(public["channel"], CHANNEL)
        self.assertNotIn("secret", json.dumps(public))
        self.assertEqual(self.client.get(url).status_code, 400)
        token_request = next(r for r in self.requests if r.url.path == "/token")
        self.assertIn("code_verifier=", token_request.content.decode())
        self.assertEqual(stat.S_IMODE((self.account.files.path / "account.json").stat().st_mode), 0o600)
        self.assertEqual(self.client.get("/runs/web/youtube/account.json").status_code, 404)
        self.assertEqual(self.client.post("/api/youtube/disconnect", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/youtube/disconnect").status_code, 200)
        self.assertFalse((self.account.files.path / "account.json").exists())

    def test_import_deduplicates_while_queued_and_binds_owned_channel(self):
        self.account.files.write("account", account_data())
        body = {"channel_id": CHANNEL["id"], "auto_analyze": False, "model": "", "download_quality": "1440"}
        with patch.object(self.app.state.jobs, "submit", return_value={"id": "prepare-job"}) as submit:
            first = self.client.post(f"/api/youtube/broadcasts/{VIDEO}/import", json=body)
            second = self.client.post(f"/api/youtube/broadcasts/{VIDEO}/import", json=body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()["project_id"], second.json()["project_id"])
            self.assertTrue(second.json()["existing"])
            self.assertEqual(submit.call_count, 1)
        bad = self.client.post(f"/api/youtube/broadcasts/{VIDEO}/import", json=body | {"channel_id": "another-channel"})
        self.assertEqual(bad.status_code, 409)
        project = self.app.state.store.get("projects", first.json()["project_id"])
        self.assertEqual(project["title"], "直播測試")
        self.assertEqual(project["youtube_analysis_state"], "manual")
        self.assertEqual(project["download_quality"], "1440")

    def test_upload_requires_audience_and_rejects_source_jobs(self):
        self.account.files.write("account", account_data())
        metadata = {"channel_id": CHANNEL["id"], "title": "完成的剪輯"}
        self.assertEqual(self.client.post("/api/youtube/uploads/source", json=metadata).status_code, 422)
        self.assertEqual(self.client.post("/api/youtube/uploads/source", json=metadata | {"made_for_kids": False}).status_code, 422)
        self.assertFalse(any("upload" in str(r.url) for r in self.requests))

    def test_cross_origin_requests_cannot_disconnect_or_change_settings(self):
        self.account.files.write("account", account_data())
        for origin in ("http://testserver:3000", "https://testserver", "null", "http://testserver:bad",
                       "http://testserver.attacker.invalid", "http://testserver/path", "http://testserver:0"):
            with self.subTest(origin=origin):
                response = self.client.post("/api/youtube/disconnect", headers={
                    "Origin": origin, "Sec-Fetch-Site": "same-site"})
                self.assertEqual(response.status_code, 403)
                self.assertTrue(self.account.status()["connected"])
        self.assertEqual(self.requests, [])
        response = self.client.post("/api/youtube/disconnect", headers={
            "Origin": "http://testserver:80", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.account.status()["connected"])

    def test_private_unfinished_and_foreign_streams_cannot_start_downloads(self):
        self.account.files.write("account", account_data())
        body = {"channel_id": CHANNEL["id"], "auto_analyze": False}
        items = [video(status={"privacyStatus": "private", "uploadStatus": "processed"}),
                 video(liveStreamingDetails={}), video(snippet={"channelId": "not-my-channel", "title": "foreign"}),
                 video(contentDetails={"duration": "PT7H"})]
        with patch.object(self.app.state.jobs, "submit") as submit:
            for item in items:
                self.account.api = AsyncMock(return_value={"items": [item]})
                response = self.client.post(f"/api/youtube/broadcasts/{VIDEO}/import", json=body)
                self.assertEqual(response.status_code, 422, response.text)
            submit.assert_not_called()

    def test_expired_session_restart_requires_explicit_acknowledgement(self):
        response = self.client.post("/api/youtube/uploads/missing/restart", json={})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/youtube/uploads/missing/restart", json={"confirmed_no_video": False})
        self.assertEqual(response.status_code, 422)

    def test_live_permission_error_preserves_successful_login_and_explains_next_step(self):
        self.account.files.write("account", account_data())
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403,
            json={"error": {"message": "provider-sensitive-data", "errors": [{"reason": "liveStreamingNotEnabled"}]}})))
        response = self.client.get("/api/youtube/broadcasts")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "liveStreamingNotEnabled")
        self.assertIn("尚未啟用直播", response.json()["detail"])
        self.assertNotIn("provider-sensitive-data", response.text)
        status = self.client.get("/api/youtube").json()
        self.assertTrue(status["connected"])
        self.assertFalse(status["reconnect_required"])
        self.assertIsNone(status["error"])


class GoogleErrorTest(unittest.TestCase):
    def test_known_google_reasons_have_actionable_redacted_messages(self):
        cases = [
            ("liveStreamingNotEnabled", "liveStreamingNotEnabled", "尚未啟用直播", 403),
            ("insufficientLivePermissions", "insufficientLivePermissions", "擁有直播存檔的頻道", 403),
            ("insufficientPermissions", "insufficientPermissions", "授權播放清單", 403),
            ("ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions", "授權播放清單", 403),
            ("accessNotConfigured", "accessNotConfigured", "同一個 Google Cloud 專案", 422),
            ("SERVICE_DISABLED", "accessNotConfigured", "同一個 Google Cloud 專案", 422),
            ("youtubeSignupRequired", "youtubeSignupRequired", "尚未建立 YouTube 頻道", 403),
        ]
        for reason, code, message, status in cases:
            for field in ("errors", "details"):
                with self.subTest(reason=reason, field=field):
                    response = httpx.Response(403, json={"error": {"message": "provider-secret", field: [
                        {"reason": reason, "metadata": {"secret": "private-metadata"}}]}})
                    with self.assertRaises(YouTubeError) as error:
                        google_error(response)
                    self.assertEqual(error.exception.status, status)
                    self.assertEqual(error.exception.code, code)
                    self.assertIn(message, str(error.exception))
                    self.assertNotIn("provider-secret", str(error.exception))
                    self.assertNotIn("private-metadata", str(error.exception))

    def test_unknown_and_malformed_errors_do_not_expose_provider_data(self):
        for error_body in (None, [], "provider-secret", {"errors": "provider-secret"},
                           {"errors": [None, {"reason": {"secret": "provider-secret"}}]},
                           {"errors": [{"reason": "provider-secret"}], "message": "private-message"}):
            with self.subTest(error_body=error_body):
                with self.assertRaises(YouTubeError) as error:
                    google_error(httpx.Response(403, json={"error": error_body}))
                self.assertEqual(error.exception.status, 403)
                self.assertIsNone(error.exception.code)
                self.assertNotIn("provider-secret", str(error.exception))
                self.assertNotIn("private-message", str(error.exception))


class AsyncYouTubeTest(unittest.IsolatedAsyncioTestCase):
    def playlist_access(self):
        from game_vod_clipper.youtube_account import PLAYLIST_SCOPE
        self.account.files.write("account", account_data() | {"scopes": list(SCOPES | {PLAYLIST_SCOPE})})

    async def test_playlist_addition_follows_upload_and_preserves_video_privacy(self):
        self.export()
        self.playlist_access()
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path.endswith("/playlists"):
                return httpx.Response(200, json={"items": [{"id": "PLwins", "snippet": {"channelId": CHANNEL["id"], "title": "完整勝利"}}]})
            if request.url.path.endswith("/playlistItems"):
                if request.method == "GET":
                    self.assertEqual(request.url.params["videoId"], "uploaded123")
                    return httpx.Response(200, json={"items": []})
                self.assertEqual(json.loads(request.content), {"snippet": {"playlistId": "PLwins", "resourceId": {
                    "kind": "youtube#video", "videoId": "uploaded123"}}})
                return httpx.Response(200, json={"id": "playlist-item"})
            if request.method == "POST":
                self.assertEqual(json.loads(request.content)["status"]["privacyStatus"], "private")
                return httpx.Response(200, headers={"location": UPLOAD + "?upload_id=clip"})
            if request.method == "PUT":
                return httpx.Response(201, json={"id": "uploaded123"})
            return httpx.Response(200, json={"items": [{"status": {"uploadStatus": "processed", "privacyStatus": "private"}}]})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        metadata = {"title": "Clip", "description": "", "privacy": "private", "made_for_kids": False,
                    "notify_subscribers": False, "playlist_id": "PLwins"}
        record = await self.uploads.start("export", metadata, CHANNEL["id"])
        await asyncio.gather(*list(self.uploads.tasks.values()))
        result = self.uploads.get(record["id"])
        self.assertEqual((result["status"], result["playlist_status"], result["privacy"]), ("succeeded", "added", "private"))
        self.assertEqual(self.uploads.public(result)["playlist_title"], "完整勝利")
        posts = [r for r in requests if r.method == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertTrue(posts[-1].url.path.endswith("/playlistItems"))

    async def test_playlist_failure_retries_without_uploading_or_inserting_a_duplicate(self):
        output = self.export()
        self.playlist_access()
        counts = {"upload": 0, "insert": 0, "lookup": 0}
        remote_added = reachable = False
        def handler(request):
            nonlocal remote_added
            if request.url.path.endswith("/playlists"):
                return httpx.Response(200, json={"items": [{"id": "PLwins", "snippet": {"channelId": CHANNEL["id"], "title": "勝利"}}]})
            if request.url.path.endswith("/playlistItems"):
                if request.method == "GET":
                    counts["lookup"] += 1
                    return httpx.Response(200, json={"items": [{"id": "existing"}] if remote_added else []})
                counts["insert"] += 1
                if not reachable:
                    raise httpx.ReadTimeout("lost-response-secret", request=request)
                remote_added = True
                return httpx.Response(200, json={"id": "playlist-item"})
            if request.method == "POST":
                counts["upload"] += 1
                return httpx.Response(200, headers={"location": UPLOAD + "?upload_id=clip"})
            if request.method == "PUT":
                return httpx.Response(201, json={"id": "uploaded123"})
            return httpx.Response(200, json={"items": [{"status": {"uploadStatus": "processed"}}]})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        metadata = {"title": "Clip", "description": "", "privacy": "private", "made_for_kids": False,
                    "notify_subscribers": False, "playlist_id": "PLwins"}
        record = await self.uploads.start("export", metadata, CHANNEL["id"])
        await asyncio.gather(*list(self.uploads.tasks.values()))
        result = self.uploads.get(record["id"])
        self.assertEqual((result["status"], result["playlist_status"]), ("succeeded", "failed"))
        self.assertNotIn("secret", result["playlist_error"])
        # One attempt right after upload and one after processing; both lost.
        self.assertEqual(counts, {"upload": 1, "insert": 2, "lookup": 2})
        output.unlink()  # Playlist retries need only the already uploaded video.
        reachable = True
        restored = YouTubeUploads(self.store, self.account)
        try:
            await restored.retry_playlist(record["id"])
            await asyncio.gather(*list(restored.tasks.values()))
            self.assertEqual(restored.get(record["id"])["playlist_status"], "added")
            self.assertEqual(counts, {"upload": 1, "insert": 3, "lookup": 3})
        finally:
            await restored.close()

    async def test_playlist_is_added_even_when_processing_outlasts_the_poll(self):
        with patch.object(self.account, "add_to_playlist", AsyncMock()) as add, \
                patch.object(self.account, "api", AsyncMock(return_value={"items": [{
                    "processingDetails": {"processingStatus": "processing"}, "status": {"uploadStatus": "uploaded"}}]})), \
                patch("game_vod_clipper.youtube_uploads.asyncio.sleep", AsyncMock()):
            self.uploads.save({"id": "slow", "channel": CHANNEL, "video_id": "uploaded123", "playlist_id": "PLwins",
                               "playlist_status": "pending", "privacy": "private", "status": "processing"})
            await self.uploads.processing("slow")
            add.assert_awaited_once_with("PLwins", "uploaded123", CHANNEL["id"])
        result = self.uploads.get("slow")
        self.assertEqual((result["status"], result["playlist_status"]), ("paused", "added"))

    async def test_foreign_playlist_or_missing_permission_is_rejected_before_upload(self):
        self.export()
        metadata = {"title": "Clip", "description": "", "privacy": "private", "made_for_kids": False,
                    "notify_subscribers": False, "playlist_id": "PLforeign"}
        with patch.object(self.account, "api", AsyncMock(return_value={"items": [{"id": "PLforeign",
                "snippet": {"channelId": "someone-else", "title": "Foreign"}}]})) as call:
            with self.assertRaisesRegex(YouTubeError, "授權播放清單"):
                await self.uploads.start("export", metadata, CHANNEL["id"])
            call.assert_not_called()
            self.playlist_access()
            with self.assertRaisesRegex(YouTubeError, "目前 YouTube 頻道"):
                await self.uploads.start("export", metadata, CHANNEL["id"])
        self.assertEqual(self.uploads.tasks, {})
        self.assertEqual(self.uploads.all(), {})

    async def test_interrupted_playlist_work_recovers_without_a_new_video_upload(self):
        self.playlist_access()
        self.uploads.save({"id": "pending-list", "channel": CHANNEL, "video_id": "uploaded123", "video_processed": True,
            "playlist_id": "PLwins", "playlist_status": "adding", "status": "adding_to_playlist"})
        self.uploads.recover()
        self.assertEqual(self.uploads.get("pending-list")["status"], "paused")
        with patch.object(self.account, "add_to_playlist", AsyncMock()) as add:
            await self.uploads.resume("pending-list")
            await asyncio.gather(*list(self.uploads.tasks.values()))
            add.assert_awaited_once_with("PLwins", "uploaded123", CHANNEL["id"])
        self.assertEqual(self.uploads.get("pending-list")["playlist_status"], "added")

    async def asyncSetUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="youtube-async-")
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.account = YouTubeAccount(self.root)
        self.account.configure(CONFIG)
        self.account.files.write("account", account_data())
        self.uploads = YouTubeUploads(self.store, self.account)

    async def asyncTearDown(self):
        await self.uploads.close()
        await self.account.close()
        self.tmp.cleanup()

    def export(self):
        draft = {"start": 2, "victory": 12, "postroll": 8, "reviewed": True, "revision": 2, "origin": "manual"}
        self.store.put("projects", {"id": "project", "source": "downloads/source.mp4", "duration": 60})
        output = self.root / "clips/web/project/export.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"synthetic-export-bytes")
        job = {"id": "export", "project_id": "project", "kind": "export", "status": "succeeded", "draft": draft, "output": "clips/web/project/export.mp4"}
        self.store.put("jobs", job)
        output.with_suffix(".json").write_text(json.dumps({"project_id": "project", "draft": draft, "output": job["output"],
            "validation": "human_reviewed; duration_checked; no_automated_visual_validation"}))
        return output

    async def test_upload_uses_export_default_private_and_survives_lost_final_response(self):
        output = self.export()
        requests = []
        session = UPLOAD + "?upload_id=session-secret"

        def handler(request):
            requests.append(request)
            if request.method == "POST":
                self.assertEqual(json.loads(request.content)["status"]["privacyStatus"], "private")
                return httpx.Response(200, headers={"Location": session})
            if request.method == "PUT" and request.content:
                self.assertEqual(request.content, output.read_bytes())
                raise httpx.ReadTimeout("lost response", request=request)
            if request.method == "PUT":
                return httpx.Response(201, json={"id": "uploaded123"})
            return httpx.Response(200, json={"items": [{"id": "uploaded123", "status": {"uploadStatus": "processed", "privacyStatus": "private"}}]})

        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        metadata = {"title": "我的剪輯", "description": "", "privacy": "private", "made_for_kids": False, "notify_subscribers": False}
        first = await self.uploads.start("export", metadata, CHANNEL["id"])
        duplicate = await self.uploads.start("export", metadata | {"title": "另一個標題"}, CHANNEL["id"])
        self.assertEqual(first["id"], duplicate["id"])
        await asyncio.gather(*list(self.uploads.tasks.values()))
        record = self.uploads.get(first["id"])
        self.assertEqual(record["status"], "succeeded", record)
        self.assertEqual(sum(r.method == "POST" for r in requests), 1)
        public = self.uploads.public(record)
        self.assertNotIn("session-secret", json.dumps(public))
        self.assertNotIn("path", public)
        recreated = YouTubeUploads(self.store, self.account)
        again = await recreated.start("export", metadata, CHANNEL["id"])
        self.assertEqual(again["video_id"], "uploaded123")
        self.assertEqual(recreated.tasks, {})

    async def test_source_and_modified_receipt_never_upload(self):
        path = self.export()
        self.store.patch("jobs", "export", output="downloads/source.mp4")
        with self.assertRaises(YouTubeError):
            self.uploads.validate_export("export")
        self.store.patch("jobs", "export", output="clips/web/project/export.mp4")
        receipt = json.loads(path.with_suffix(".json").read_text())
        receipt["draft"]["reviewed"] = False
        path.with_suffix(".json").write_text(json.dumps(receipt))
        with self.assertRaises(YouTubeError):
            self.uploads.validate_export("export")

    async def test_reencoded_entire_source_is_not_a_publishable_clip(self):
        self.export()
        job = self.store.get("jobs", "export")
        self.store.patch("jobs", "export", draft=job["draft"] | {"start": 0, "victory": 52})
        with self.assertRaisesRegex(YouTubeError, "整支原片"):
            self.uploads.validate_export("export")

    async def test_expired_session_does_not_start_a_duplicate_upload(self):
        self.export()
        metadata = {"title": "clip", "description": "", "privacy": "private", "made_for_kids": False, "notify_subscribers": False}
        with patch.object(self.uploads, "launch"):
            item = await self.uploads.start("export", metadata, CHANNEL["id"])
        self.uploads.patch(item["id"], session=UPLOAD + "?upload_id=expired", offset=10)
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
        await self.uploads.run(item["id"])
        self.assertEqual(self.uploads.get(item["id"])["status"], "needs_review")
        await self.uploads.resume(item["id"])
        self.assertEqual(self.uploads.tasks, {})

    async def test_broadcasts_are_completed_owned_paginated_and_private_is_disabled(self):
        def handler(request):
            if request.url.path.endswith("liveBroadcasts"):
                self.assertEqual(request.url.params["broadcastStatus"], "completed")
                self.assertNotIn("mine", request.url.params)
                self.assertEqual(request.url.params["pageToken"], "next")
                return httpx.Response(200, json={"nextPageToken": "last", "items": [{"id": VIDEO, "snippet": video()["snippet"]}]})
            return httpx.Response(200, json={"items": [video(status={"privacyStatus": "private", "uploadStatus": "processed"})]})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await self.account.broadcasts("next")
        self.assertEqual(result["next_page_token"], "last")
        self.assertFalse(result["items"][0]["available"])

    async def test_revoked_refresh_is_actionable_without_leaking_google_payload(self):
        self.account.files.write("account", account_data() | {"expires": 0})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(400,
            json={"error": "invalid_grant", "error_description": "sensitive-provider-data"})))
        with self.assertRaisesRegex(YouTubeError, "重新連接"):
            await self.account.access_token()
        self.assertTrue(self.account.status()["reconnect_required"])

    async def test_login_keeps_polling_during_exchange_and_partial_consent_never_connects(self):
        self.account.files.remove("account")
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            if request.url.path == "/token":
                entered.set()
                await release.wait()
                return httpx.Response(200, json={"access_token": "secret", "refresh_token": "secret", "scope": next(iter(SCOPES))})
            self.fail("Partial consent must never reach channel discovery")
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        state = self.account.begin("http://localhost/api/youtube/callback")["state"]
        task = asyncio.create_task(self.account.complete(state, state, "auth-code"))
        await entered.wait()
        self.assertTrue(self.account.status()["pending"])
        release.set()
        with self.assertRaisesRegex(YouTubeError, "兩項權限"):
            await task
        self.assertFalse(self.account.status()["pending"])
        self.assertFalse(self.account.status()["connected"])

    async def test_background_analysis_is_enqueued_once_and_never_approves_export(self):
        analyze = AsyncMock(return_value={"id": "analysis"})
        workspace = YouTubeWorkspace(self.store, AsyncMock(), analyze, AsyncMock())
        self.store.put("projects", {"id": "p", "ready": True, "duration": 60, "youtube_analysis_state": "waiting", "youtube_model": "vision",
            "draft": {"reviewed": False}})
        await workspace.advance()
        await workspace.advance()
        analyze.assert_awaited_once()
        self.assertFalse(self.store.get("projects", "p")["draft"]["reviewed"])
        await workspace.close()

    async def test_watcher_only_queues_new_available_streams_and_preserves_pagination(self):
        workspace = YouTubeWorkspace(self.store, AsyncMock(), AsyncMock(), AsyncMock())
        workspace.account.files.write("account", account_data())
        settings = await workspace.set_watch(WatchSettings(channel_id=CHANNEL["id"], enabled=True, auto_analyze=False, download_quality="720"))
        self.assertGreater(settings["since"], time.time() - 5)
        new_time = datetime.fromtimestamp(settings["since"] + 1, timezone.utc).isoformat()
        old_time = datetime.fromtimestamp(settings["since"] - 10, timezone.utc).isoformat()
        def row(key, **extra):
            return {"id": key, "ended_at": new_time, "available": True, "project_id": None, **extra}
        workspace.broadcasts = AsyncMock(return_value={"items": [row(VIDEO), row("oldoldold12", ended_at=old_time),
            row("private1234", available=False), row("already1234", project_id="existing")], "next_page_token": "next"})
        async def remember(key, _options, **_kwargs):
            workspace.account.files.write("imports", {f"{CHANNEL['id']}:{key}": "new-project"})
            return {"project_id": "new-project"}
        workspace.import_video = AsyncMock(side_effect=remember)
        await workspace.sync()
        await workspace.sync()
        workspace.import_video.assert_awaited_once()
        self.assertEqual(workspace.import_video.await_args.args[1].download_quality, "720")
        self.assertEqual(workspace.preferences()["download_quality"], "720")
        self.assertEqual(workspace.preferences()["cursor"], "next")
        self.assertEqual(workspace.broadcasts.await_args.args, ("next",))
        await workspace.set_watch(WatchSettings(channel_id=CHANNEL["id"], enabled=False, auto_analyze=False))
        calls = workspace.broadcasts.await_count
        await workspace.sync()
        self.assertEqual(workspace.broadcasts.await_count, calls)
        await workspace.close()

    async def test_broadcasts_match_existing_projects_with_one_table_read(self):
        workspace = YouTubeWorkspace(self.store, AsyncMock(), AsyncMock(), AsyncMock())
        try:
            self.store.put("projects", {"id": "tagged", "youtube_video_id": VIDEO})
            self.store.put("projects", {"id": "newer", "url": f"https://www.youtube.com/watch?v={VIDEO}"})
            self.store.put("projects", {"id": "linked", "url": "https://www.youtube.com/watch?v=lmnopqrstuv"})
            workspace.account.broadcasts = AsyncMock(return_value={"items": [
                {"id": VIDEO}, {"id": "lmnopqrstuv"}, {"id": "noimport123"}], "next_page_token": ""})
            with patch.object(self.store, "all", wraps=self.store.all) as read:
                result = await workspace.broadcasts()
            read.assert_called_once_with("projects")
            self.assertEqual([row["project_id"] for row in result["items"]], ["newer", "linked", None])
        finally:
            await workspace.close()

    async def test_upload_progress_updates_only_its_receipt_and_recovers_after_migration(self):
        self.export()
        metadata = {"title": "clip", "description": "", "privacy": "private", "made_for_kids": False, "notify_subscribers": False}
        with patch.object(self.uploads, "launch"):
            record = await self.uploads.start("export", metadata, CHANNEL["id"])
        key = record["id"]
        self.uploads.patch(key, session=UPLOAD + "?upload_id=persisted", status="uploading")
        latest = self.uploads.get(key)
        # An interrupted migration may leave both files; the per-record one wins.
        self.account.files.write("uploads", {key: latest | {"session": None},
            **{f"history-{n}": {"id": f"history-{n}", "status": "succeeded", "description": "x" * 2000} for n in range(1000)}})
        migrated = YouTubeUploads(self.store, self.account)
        self.assertEqual(len(migrated.all()), 1001)
        self.assertFalse((self.account.files.path / "uploads.json").exists())
        self.assertEqual(migrated.get(key)["session"], latest["session"])
        with patch.object(self.account.files, "read", wraps=self.account.files.read) as read, \
                patch.object(self.account.files, "write", wraps=self.account.files.write) as write:
            migrated.accept_response(key, httpx.Response(308, headers={"Range": "bytes=0-3"}))
            read.assert_not_called()
            write.assert_called_once()
            self.assertEqual(write.call_args.args[0], "upload-" + key)
            self.assertEqual(write.call_args.args[1]["offset"], 4)
        recovered = YouTubeUploads(self.store, self.account)
        recovered.recover()
        self.assertEqual(recovered.get(key)["offset"], 4)
        self.assertEqual(recovered.get(key)["status"], "paused")
        self.assertEqual(recovered.get(key)["session"], latest["session"])
        self.assertEqual(stat.S_IMODE((self.account.files.path / f"upload-{key}.json").stat().st_mode), 0o600)

    async def test_resume_and_restart_respect_the_upload_queue_limit(self):
        self.export()
        metadata = {"title": "clip", "description": "", "privacy": "private", "made_for_kids": False, "notify_subscribers": False}
        with patch.object(self.uploads, "launch"):
            record = await self.uploads.start("export", metadata, CHANNEL["id"])
        key = record["id"]
        with patch.dict(self.uploads.tasks, {f"busy-{n}": object() for n in range(8)}):
            for status, action in (("paused", self.uploads.resume), ("needs_review", self.uploads.restart)):
                self.uploads.patch(key, status=status)
                with self.assertRaises(YouTubeError) as error:
                    await action(key)
                self.assertEqual(error.exception.status, 429)
                self.assertEqual(self.uploads.get(key)["status"], status)

    async def test_upload_history_uses_creation_time_after_restart(self):
        for key, created in (("middle", 2), ("newest", 3), ("oldest", 1)):
            self.uploads.save({"id": key, "created": created, "status": "succeeded"})
        reloaded = YouTubeUploads(self.store, self.account)
        self.assertEqual([item["id"] for item in reloaded.public_records()], ["newest", "middle", "oldest"])

    async def test_server_range_controls_chunk_resume_after_restart(self):
        path = self.export()
        content = b"0123456789ABCDEF"
        path.write_bytes(content)
        metadata = {"title": "clip", "description": "", "privacy": "private", "made_for_kids": False, "notify_subscribers": False}
        with patch.object(self.uploads, "launch"):
            record = await self.uploads.start("export", metadata, CHANNEL["id"])
        self.uploads.patch(record["id"], session=UPLOAD + "?upload_id=resume", offset=0, status="uploading")
        self.uploads.recover()
        self.assertEqual(self.uploads.get(record["id"])["status"], "paused")
        received = []
        def handler(request):
            if request.method == "PUT" and not request.content:
                return httpx.Response(308, headers={"Range": "bytes=0-3"})
            if request.method == "PUT":
                received.append(request.content)
                if len(received) == 1:
                    self.assertEqual(request.headers["content-range"], "bytes 4-7/16")
                    return httpx.Response(308, headers={"Range": "bytes=0-7"})
                if len(received) == 2:
                    return httpx.Response(308, headers={"Range": "bytes=0-11"})
                return httpx.Response(201, json={"id": "uploaded123"})
            return httpx.Response(200, json={"items": [{"status": {"uploadStatus": "processed"}}]})
        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("game_vod_clipper.youtube_uploads.CHUNK", 4):
            await self.uploads.resume(record["id"])
            await asyncio.gather(*list(self.uploads.tasks.values()))
        self.assertEqual(b"".join(received), content[4:])
        self.assertEqual(self.uploads.get(record["id"])["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
