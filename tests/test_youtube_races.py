"""Offline regression tests for watcher cancellation and deletion/upload races."""

import asyncio
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from game_vod_clipper.web import create_app
from game_vod_clipper.web_store import Store
from game_vod_clipper.youtube_routes import WatchSettings, YouTubeWorkspace
from game_vod_clipper.youtube_uploads import UPLOAD


ROOT = Path(__file__).resolve().parents[1]


class Races(unittest.IsolatedAsyncioTestCase):
    async def test_watch_disable_blocks_import_waiting_for_lock(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="logic-watch-") as directory:
            store = Store(Path(directory))
            source = AsyncMock()
            workspace = YouTubeWorkspace(store, source, AsyncMock(), AsyncMock())
            workspace.account.files.write("account", {"channel": {"id": "ch", "title": "demo"}})
            settings = await workspace.set_watch(WatchSettings(channel_id="ch", enabled=True, auto_analyze=False))
            entered, release = asyncio.Event(), asyncio.Event()

            async def broadcasts(_token):
                entered.set()
                await release.wait()
                return {"items": [{"id": "abcdefghijk", "ended_at": datetime.fromtimestamp(settings["since"] + 1, timezone.utc).isoformat(),
                                   "available": True, "project_id": None}], "next_page_token": ""}

            workspace.broadcasts = broadcasts
            workspace.account.api = AsyncMock(return_value={"items": [{"snippet": {"channelId": "ch"},
                "status": {"privacyStatus": "unlisted", "uploadStatus": "processed"},
                "liveStreamingDetails": {"actualEndTime": "2026-09-20T00:00:00Z"}, "contentDetails": {"duration": "PT1M"}}]})

            async def source_import(_video_id):
                store.put("projects", {"id": "p"})
                return {"project": {"id": "p"}}

            source.side_effect = source_import
            try:
                sync = asyncio.create_task(workspace.sync())
                await entered.wait()
                disable = asyncio.create_task(workspace.set_watch(WatchSettings(channel_id="ch", enabled=False, auto_analyze=False)))
                await asyncio.sleep(0)  # Queue disabling behind the list request's lock.
                release.set()
                await disable
                await sync
                self.assertFalse(workspace.preferences()["enabled"])
                source.assert_not_awaited()
            finally:
                await workspace.close()

    async def test_project_delete_serializes_new_upload(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="logic-delete-") as directory:
            app = create_app(Path(directory))
            store, youtube = app.state.store, app.state.youtube
            await youtube.account.client.aclose()
            youtube.account.files.write("account", {"channel": {"id": "ch", "title": "demo"},
                "refresh_token": "fake", "access_token": "fake", "expires": time.time() + 3600})
            draft = {"start": 2, "victory": 12, "postroll": 8, "reviewed": True, "revision": 0, "origin": "manual"}
            store.put("projects", {"id": "p", "duration": 60, "source": "downloads/source.mp4"})
            path = store.root / "clips/web/p/export-b.mp4"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic-export")
            store.put("jobs", {"id": "export-b", "project_id": "p", "kind": "export", "status": "succeeded",
                "draft": draft, "output": str(path.relative_to(store.root))})
            path.with_suffix(".json").write_text(json.dumps({"project_id": "p", "draft": draft,
                "output": str(path.relative_to(store.root)), "validation": "human_reviewed; duration_checked; no_automated_visual_validation"}))
            cancel_entered, cancel_release, upload_release = [asyncio.Event() for _ in range(3)]
            put_after_delete = []

            async def old_upload():
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancel_entered.set()
                    await cancel_release.wait()

            youtube.uploads.save({"id": "old", "project_id": "p", "status": "uploading"})
            old = asyncio.create_task(old_upload())
            youtube.uploads.tasks["old"] = old
            old.add_done_callback(lambda _: youtube.uploads.tasks.pop("old", None))
            await asyncio.sleep(0)

            async def handler(request):
                if request.method == "POST":
                    await upload_release.wait()
                    return httpx.Response(200, headers={"location": UPLOAD + "?upload_id=fake"})
                if request.method == "PUT":
                    put_after_delete.append(store.get("projects", "p") is None)
                    return httpx.Response(201, json={"id": "uploaded123"})
                return httpx.Response(200, json={"items": [{"status": {"uploadStatus": "processed"}}]})

            youtube.account.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                    delete = asyncio.create_task(client.delete("/api/projects/p"))
                    await cancel_entered.wait()
                    start = asyncio.create_task(client.post("/api/youtube/uploads/export-b", json={
                        "channel_id": "ch", "title": "clip", "made_for_kids": False}))
                    # Give the unguarded start time to create B while delete awaits A.
                    # A fixed implementation can instead leave start waiting on its lock.
                    await asyncio.sleep(0.1)
                    cancel_release.set()
                    deleted = await delete
                    self.assertEqual(deleted.status_code, 200)
                    started = await start
                    upload_release.set()
                    await asyncio.gather(*list(youtube.uploads.tasks.values()))
                    self.assertIn(started.status_code, (404, 409, 422), started.text)
                    self.assertFalse(any(put_after_delete))
            finally:
                cancel_release.set()
                upload_release.set()
                await youtube.close()
                await app.state.codex.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
