"""Offline playlist creation checks; never write to a real YouTube channel."""

import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app
from game_vod_clipper.youtube.account import API, PLAYLIST_SCOPE, SCOPES

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = {"id": "channel-a", "title": "我的頻道"}


class PlaylistCreationTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="playlist-test-")
        self.app = create_app(Path(self.tmp.name))
        self.account = self.app.state.youtube.account
        self.account.configure({"web": {"client_id": "test.apps.googleusercontent.com", "client_secret": "secret"}})
        self.account.files.write("account", {"access_token": "access-secret", "refresh_token": "refresh-secret",
            "expires": time.time() + 3600, "channel": CHANNEL, "scopes": list(SCOPES | {PLAYLIST_SCOPE})})
        self.requests = []

        def handler(request):
            self.requests.append(request)
            metadata = json.loads(request.content)
            return httpx.Response(201, json={"id": "PLcreated", "snippet": {
                "channelId": CHANNEL["id"], "title": metadata["snippet"]["title"]},
                "status": metadata["status"], "contentDetails": {"itemCount": 0}})

        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def create(self, **changes):
        return self.client.post("/api/youtube/playlists", json={"channel_id": CHANNEL["id"], "title": "Boss 勝利", **changes})

    def test_create_uses_current_channel_and_explicit_privacy_without_uploading(self):
        for privacy in (None, "private", "unlisted", "public"):
            with self.subTest(privacy=privacy):
                response = self.create(title="  女武神・完整勝利  ", **({"privacy": privacy} if privacy else {}))
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json(), {"id": "PLcreated", "title": "女武神・完整勝利",
                    "privacy": privacy or "private", "count": 0})
                request = self.requests[-1]
                self.assertEqual((request.method, str(request.url).split("?")[0]), ("POST", API + "playlists"))
                self.assertEqual(request.url.params["part"], "snippet,status,contentDetails")
                self.assertEqual(json.loads(request.content), {"snippet": {"title": "女武神・完整勝利"},
                    "status": {"privacyStatus": privacy or "private"}})
                self.assertEqual(request.headers["authorization"], "Bearer access-secret")
                self.assertNotIn("secret", response.text)
        self.assertEqual(len(self.requests), 4)

    def test_creation_rejects_wrong_channel_pending_login_and_missing_permission_before_google(self):
        self.assertEqual(self.create(channel_id="another-channel").status_code, 409)
        self.account.pending = {"expires": time.time() + 600}
        self.assertEqual(self.create().status_code, 409)
        self.account.pending = None
        data = self.account.files.read("account")
        self.account.files.write("account", data | {"scopes": list(SCOPES)})
        response = self.create()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "playlistPermissionRequired")
        self.assertIn("授權播放清單", response.json()["detail"])
        self.account.files.remove("account")
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.requests, [])

    def test_invalid_metadata_never_reaches_google(self):
        for changes in ({"title": ""}, {"title": "   "}, {"title": "a" * 151}, {"title": "Boss\x00勝利"},
                        {"title": "Boss\n勝利"}, {"privacy": "invalid"}, {"channel_id": ""}, {"video_id": "source"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 422)
        self.assertEqual(self.requests, [])

    def test_google_errors_are_actionable_and_redacted(self):
        for reason, status, message in (("maxPlaylistExceeded", 422, "已達上限"),
                                       ("playlistTitleRequired", 422, "名稱無效"),
                                       ("invalidPlaylistSnippet", 422, "名稱無效"),
                                       ("insufficientPermissions", 403, "授權播放清單"),
                                       ("quotaExceeded", 429, "額度暫時用完")):
            with self.subTest(reason=reason):
                self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403,
                    json={"error": {"message": "provider-secret", "errors": [{"reason": reason}]}})))
                response = self.create()
                self.assertEqual(response.status_code, status)
                self.assertIn(message, response.json()["detail"])
                self.assertNotIn("provider-secret", response.text)

    def test_missing_or_foreign_creation_receipt_is_not_selected_or_retried(self):
        for item in ({}, {"id": "../bad", "snippet": {"channelId": CHANNEL["id"], "title": "Boss"}},
                     {"id": "PLforeign", "snippet": {"channelId": "another-channel", "title": "Boss"}},
                     {"id": "PLmissingTitle", "snippet": {"channelId": CHANNEL["id"]}}, None):
            with self.subTest(item=item):
                calls = []

                def handler(request):
                    calls.append(request)
                    return httpx.Response(201, json=item)

                self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                response = self.create()
                self.assertEqual(response.status_code, 502)
                self.assertIn("先重新整理", response.json()["detail"])
                self.assertEqual(len(calls), 1)

    def test_network_failure_does_not_automatically_create_a_duplicate(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ReadError("provider-secret", request=request)

        self.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = self.create()
        self.assertEqual(response.status_code, 502)
        self.assertIn("先重新整理", response.json()["detail"])
        self.assertNotIn("provider-secret", response.text)
        self.assertEqual(len(calls), 1)
