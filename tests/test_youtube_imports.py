"""Offline batch import tests: durable waiting, bounded work and channel ownership."""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from game_vod_clipper.web import create_app
from game_vod_clipper.web_store import Store
from game_vod_clipper.youtube_account import YouTubeError
from game_vod_clipper.youtube_imports import YouTubeImports
from game_vod_clipper.youtube_routes import ImportBroadcast, YouTubeWorkspace

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = {"id": "channel-a", "title": "測試頻道"}
OPTIONS = {"channel_id": CHANNEL["id"], "auto_analyze": True, "model": "vision"}


def choices(count):
    return [{"id": f"video{number:06d}", "title": f"直播 {number}"} for number in range(count)]


class BatchImportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="batch-import-")
        self.store = Store(Path(self.tmp.name))
        self.source = AsyncMock(side_effect=self.prepare)
        self.workspace = YouTubeWorkspace(self.store, self.source, AsyncMock(), AsyncMock())
        self.account = self.workspace.account
        self.account.files.write("account", {"channel": CHANNEL, "refresh_token": "fake", "access_token": "fake", "expires": time.time() + 3600})
        self.account.api = AsyncMock(side_effect=self.metadata)
        self.queue = self.workspace.imports

    async def asyncTearDown(self):
        await self.workspace.close()
        self.tmp.cleanup()

    async def metadata(self, resource, **params):
        key = params["id"]
        return {"items": [{"id": key, "snippet": {"channelId": CHANNEL["id"], "title": key},
            "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"},
            "contentDetails": {"duration": "PT1H"}, "liveStreamingDetails": {"actualEndTime": "2026-09-20T00:00:00Z"}}]}

    async def prepare(self, key):
        project = {"id": key, "ready": False, "url": f"https://www.youtube.com/watch?v={key}", "title": key}
        self.store.put("projects", project)
        self.store.put("jobs", {"id": "prepare-" + key, "project_id": key, "kind": "prepare", "status": "queued", "progress": 0})
        return {"project": project}

    def finish(self, key):
        self.store.patch("jobs", "prepare-" + key, status="succeeded", progress=100)
        self.store.patch("projects", key, ready=True)

    async def test_large_selection_waits_one_prepare_at_a_time_and_keeps_ai_options(self):
        videos = choices(12)
        result = self.queue.add(videos, OPTIONS, CHANNEL)
        self.assertEqual(result, {"added": 12, "existing": 0})
        self.source.assert_not_awaited()
        for index, video in enumerate(videos):
            await self.queue.advance()
            self.assertEqual(self.source.await_count, index + 1)
            self.assertEqual(self.queue.public_records()[0]["video_id"], video["id"])
            self.assertEqual(self.queue.public_records()[0]["status"], "preparing")
            await self.queue.advance()
            self.assertEqual(self.source.await_count, index + 1)
            self.assertEqual(sum(job["status"] == "queued" for job in self.store.all("jobs")), 1)
            project = self.store.get("projects", video["id"])
            self.assertEqual(project["youtube_model"], "vision")
            self.assertEqual(project["youtube_analysis_state"], "waiting")
            self.finish(video["id"])
        self.assertTrue(all(item["status"] == "ready" for item in self.queue.public_records()))

    async def test_duplicates_cancel_and_manual_import_never_repeat_a_download(self):
        video = choices(1)[0]
        self.queue.add([video, video], OPTIONS, CHANNEL)
        duplicate = self.queue.add([video], OPTIONS | {"model": "changed"}, CHANNEL)
        self.assertEqual(duplicate, {"added": 0, "existing": 1})
        key = next(iter(self.queue.records))
        self.assertEqual(self.queue.get(key)["options"]["model"], "vision")
        self.queue.cancel(key)
        await self.queue.advance()
        self.source.assert_not_awaited()
        self.queue.retry(key)
        await self.workspace.import_video(video["id"], ImportBroadcast(**OPTIONS))
        self.finish(video["id"])
        await self.queue.advance()
        self.source.assert_awaited_once()
        self.assertEqual(self.queue.public_records()[0]["status"], "ready")

    async def test_full_media_queue_waits_without_losing_the_selection(self):
        self.queue.add(choices(1), OPTIONS, CHANNEL)
        for number in range(8):
            self.store.put("jobs", {"id": str(number), "project_id": "other", "kind": "analyze", "status": "running"})
        await self.queue.advance()
        self.source.assert_not_awaited()
        self.assertEqual(self.queue.public_records()[0]["status"], "queued")
        self.store.patch("jobs", "0", status="succeeded")
        await self.queue.advance()
        self.source.assert_awaited_once()

    async def test_bad_video_fails_individually_and_transient_errors_back_off(self):
        videos = choices(3)
        self.queue.add(videos, OPTIONS, CHANNEL)
        original = self.account.api.side_effect
        async def metadata(resource, **params):
            result = await original(resource, **params)
            if params["id"] == videos[0]["id"]:
                result["items"][0]["snippet"]["channelId"] = "foreign"
            return result
        self.account.api.side_effect = metadata
        await self.queue.advance()
        self.source.assert_not_awaited()
        self.assertEqual(next(item for item in self.queue.public_records() if item["video_id"] == videos[0]["id"])["status"], "failed")
        self.account.api.side_effect = YouTubeError("暫時無法連線", 502)
        await self.queue.advance()
        calls = self.account.api.await_count
        await self.queue.advance()
        self.assertEqual(self.account.api.await_count, calls)
        retrying = next(item for item in self.queue.records.values() if item["video_id"] == videos[1]["id"])
        self.assertGreater(retrying["retry_at"], time.time())
        self.queue.save(retrying | {"retry_at": 0})
        self.account.api.side_effect = original
        await self.queue.advance()
        self.source.assert_awaited_once_with(videos[1]["id"])

    async def test_reboot_and_account_changes_preserve_waiting_and_project_deduplication(self):
        videos = choices(2)
        self.queue.add(videos, OPTIONS, CHANNEL)
        first = next(iter(self.queue.records.values()))
        self.queue.save(first | {"status": "importing"})
        await self.workspace.import_video(videos[0]["id"], ImportBroadcast(**OPTIONS))
        self.store.patch("jobs", "prepare-" + videos[0]["id"], status="interrupted")
        recovered = YouTubeImports(self.store, self.account, self.workspace.lock, self.queue.import_video)
        recovered.recover()
        self.account.files.write("account", {"channel": {"id": "another", "title": "另一頻道"}})
        await recovered.advance()
        self.assertTrue(all(item["status"] == "waiting_account" for item in recovered.public_records()))
        self.account.files.write("account", {"channel": CHANNEL})
        await recovered.advance()
        self.source.assert_awaited_once()
        self.assertEqual(next(item for item in recovered.public_records() if item["video_id"] == videos[0]["id"])["status"], "needs_attention")
        await recovered.advance()
        self.assertEqual(self.source.await_count, 2)

    async def test_cancel_waiting_for_lock_wins_before_dispatch(self):
        self.queue.add(choices(1), OPTIONS, CHANNEL)
        key = next(iter(self.queue.records))
        async def cancel():
            async with self.workspace.lock:
                self.queue.cancel(key)
        async with self.workspace.lock:
            cancelled = asyncio.create_task(cancel())
            await asyncio.sleep(0)
            advancing = asyncio.create_task(self.queue.advance())
            await asyncio.sleep(0)
        await asyncio.gather(cancelled, advancing)
        self.source.assert_not_awaited()
        self.assertEqual(self.queue.get(key)["status"], "cancelled")

    async def test_capacity_is_atomic_and_route_validates_bulk_input(self):
        with patch("game_vod_clipper.youtube_imports.MAX_WAITING", 2):
            with self.assertRaises(YouTubeError):
                self.queue.add(choices(3), OPTIONS, CHANNEL)
            self.assertFalse(self.queue.records)
        app = create_app(self.store.root)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                body = OPTIONS | {"auto_analyze": False, "videos": choices(2)}
                for videos in ([], choices(101), [{"id": "../invalid", "title": "bad"}]):
                    self.assertEqual((await client.post("/api/youtube/imports", json=body | {"videos": videos})).status_code, 422)
                self.assertEqual((await client.post("/api/youtube/imports", json=body | {"channel_id": "wrong"})).status_code, 409)
                first = await client.post("/api/youtube/imports", json=body)
                self.assertEqual(first.status_code, 202)
                self.assertEqual(first.json()["added"], 2)
                repeated = await client.post("/api/youtube/imports", json=body)
                self.assertEqual(repeated.json()["existing"], 2)
                key = first.json()["items"][0]["id"]
                cancelled = await client.post(f"/api/youtube/imports/{key}/cancel")
                self.assertEqual(cancelled.status_code, 200)
                self.assertTrue(any(item["status"] == "cancelled" for item in cancelled.json()["imports"]))
                self.assertEqual((await client.post(f"/api/youtube/imports/{key}/retry")).status_code, 200)
        finally:
            await app.state.youtube.close()
            await app.state.codex.close()


if __name__ == "__main__":
    unittest.main()
