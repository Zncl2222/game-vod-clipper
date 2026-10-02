"""Cleanup uses disposable files, never the developer's source videos."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.storage.locations import Locations
from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store
from game_vod_clipper.youtube.account import PrivateFiles
from game_vod_clipper.youtube.history import backfill_legacy, public_history


class CleanupTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        self.temp = tempfile.TemporaryDirectory(prefix="cleanup-test-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.enterContext(TestClient(self.app))
        self.source = self.file("downloads/original.webm", b"source")
        self.clip = self.file("clips/web/p/clip.mp4", b"clip")
        self.preview = self.file("runs/web/p/preview.mp4", b"preview")
        self.project = dict(id="p", title="測試直播", url="https://www.youtube.com/watch?v=abcdefghijk",
                            created=123, source="downloads/original.webm", ready=True, duration=100, thumbnails=[])
        self.store.put("projects", self.project)
        self.store.put("jobs", dict(id="clip", project_id="p", kind="export", status="succeeded",
                                   output="clips/web/p/clip.mp4"))

    def file(self, path, data=b"fixture"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def item(self, name):
        return next(row for row in self.client.get("/api/storage/files").json()["items"] if row["name"] == name)

    def remove(self, item):
        return self.client.post("/api/storage/delete", json={"id": item["id"]})

    def remove_batch(self, *items):
        return self.client.post("/api/storage/delete-batch", json={"ids": [item["id"] for item in items]})

    def test_batch_deletes_only_selected_files_and_keeps_history(self):
        self.client.delete("/api/projects/p")
        source, clip = self.item("original.webm"), self.item("clip.mp4")
        result = self.remove_batch(source, clip).json()
        self.assertEqual({item["id"] for item in result["deleted"]}, {source["id"], clip["id"]})
        self.assertEqual(result["bytes"], 10)
        self.assertEqual(result["failed"], [])
        self.assertFalse(self.source.exists())
        self.assertFalse(self.clip.exists())
        self.assertTrue(self.preview.exists())
        self.assertEqual(self.client.get("/api/youtube/history").json()[0]["title"], "測試直播")

    def test_batch_reports_blocked_and_stale_files_without_touching_them(self):
        orphan = self.file("downloads/orphan.mp4")
        source, clip, stale = self.item("original.webm"), self.item("clip.mp4"), self.item(orphan.name)
        orphan.write_bytes(b"new version")
        result = self.remove_batch(source, stale, clip).json()
        self.assertEqual([item["id"] for item in result["deleted"]], [clip["id"]])
        self.assertEqual({item["id"] for item in result["failed"]}, {source["id"], stale["id"]})
        self.assertTrue(self.source.exists())
        self.assertEqual(orphan.read_bytes(), b"new version")
        self.assertIsNone(self.store.get("jobs", "clip"))

    def test_batch_deduplicates_ids_and_scans_once(self):
        from game_vod_clipper.storage.inventory import video_inventory
        item = self.item("clip.mp4")
        with patch("game_vod_clipper.api.storage.video_inventory", wraps=video_inventory) as scan:
            result = self.remove_batch(item, item).json()
        scan.assert_called_once()
        self.assertEqual(len(result["deleted"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["bytes"], 4)

    def test_batch_rejects_empty_oversized_invalid_and_arbitrary_path_requests(self):
        for body in ({"ids": []}, {"ids": ["a" * 64] * 501}, {"ids": ["../source.mp4"]},
                     {"ids": ["a" * 64], "path": "downloads/original.webm"}, {"ids": [12]}):
            with self.subTest(body=str(body)[:100]):
                self.assertEqual(self.client.post("/api/storage/delete-batch", json=body).status_code, 422)
        self.assertTrue(self.source.exists())

    def test_batch_reports_permission_failure_and_preserves_successful_outcomes(self):
        first = self.file("downloads/first.mp4")
        second = self.file("downloads/second.mp4")
        one, two = self.item(first.name), self.item(second.name)
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == second:
                raise PermissionError("denied")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink):
            result = self.remove_batch(one, two).json()
        self.assertEqual([item["id"] for item in result["deleted"]], [one["id"]])
        self.assertEqual([item["id"] for item in result["failed"]], [two["id"]])
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())

    def test_batch_rechecks_upload_protection_at_confirmation(self):
        item = self.item("clip.mp4")
        self.app.state.youtube.uploads.records["u"] = dict(id="u", export_id="clip", project_id="p", status="uploading")
        result = self.remove_batch(item).json()
        self.assertEqual(result["deleted"], [])
        self.assertIn("上傳", result["failed"][0]["detail"])
        self.assertTrue(self.clip.exists())

    def test_clip_can_be_removed_independently_with_its_receipt(self):
        receipt = self.file("clips/web/p/clip.json")
        self.assertEqual(self.remove(self.item("clip.mp4")).status_code, 200)
        self.assertFalse(self.clip.exists())
        self.assertFalse(receipt.exists())
        self.assertIsNone(self.store.get("jobs", "clip"))
        self.assertTrue(self.source.exists())
        self.assertTrue(self.preview.exists())
        self.assertIsNotNone(self.store.get("projects", "p"))

    def test_source_and_preview_protected_until_project_deleted_then_history_survives_cleanup(self):
        for name in ("original.webm", "preview.mp4"):
            item = self.item(name)
            self.assertTrue(item["blocked"])
            self.assertEqual(self.remove(item).status_code, 409)
        self.assertEqual(self.client.delete("/api/projects/p").status_code, 200)
        for name in ("original.webm", "clip.mp4", "preview.mp4"):
            self.assertEqual(self.remove(self.item(name)).status_code, 200)
        self.assertEqual(self.client.get("/api/storage").json()["bytes"], 0)
        history = self.client.get("/api/youtube/history").json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["title"], "測試直播")
        self.assertIsNone(history[0]["project_id"])
        self.assertTrue(history[0]["completed"])
        self.assertEqual(public_history(Store(self.root)), history)

    def test_shared_source_stays_protected_after_one_project_is_deleted(self):
        self.store.put("projects", {**self.project, "id": "other"})
        self.client.delete("/api/projects/p")
        self.assertEqual(self.remove(self.item("original.webm")).status_code, 409)
        self.assertTrue(self.source.exists())

    def test_stale_confirmation_cannot_delete_replaced_file_or_new_dependency(self):
        item = self.item("clip.mp4")
        self.clip.write_bytes(b"new clip data")
        self.assertEqual(self.remove(item).status_code, 409)
        item = self.item("clip.mp4")
        self.store.put("projects", {**self.project, "id": "other", "source": "clips/web/p/clip.mp4"})
        self.assertEqual(self.remove(item).status_code, 409)
        self.assertTrue(self.clip.exists())

    def test_active_workers_and_uploads_protect_files_including_orphans(self):
        orphan = self.file("downloads/orphan.mp4")
        item = self.item(orphan.name)
        self.store.put("jobs", dict(id="work", project_id="p", kind="prepare", status="running"))
        self.assertEqual(self.remove(item).status_code, 409)
        self.store.patch("jobs", "work", status="cancelled")
        upload = dict(id="u", export_id="clip", project_id="p", status="uploading")
        self.app.state.youtube.uploads.records["u"] = upload
        self.assertEqual(self.remove(self.item("clip.mp4")).status_code, 409)
        upload["status"] = "succeeded"
        self.assertEqual(self.remove(self.item("clip.mp4")).status_code, 200)
        self.assertEqual(upload["status"], "succeeded")

    def test_symlinks_arbitrary_paths_and_sidecar_tampering_are_rejected(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"private")
        self.source.parent.joinpath("linked.mp4").symlink_to(outside)
        names = [row["name"] for row in self.client.get("/api/storage/files").json()["items"]]
        self.assertNotIn("linked.mp4", names)
        self.assertEqual(self.client.post("/api/storage/delete", json={"id": "../outside.mp4"}).status_code, 422)
        self.assertEqual(self.client.post("/api/storage/delete", json={"id": "a" * 64, "path": str(outside)}).status_code, 422)
        self.clip.with_suffix(".json").symlink_to(outside)
        self.assertEqual(self.remove(self.item("clip.mp4")).status_code, 409)
        self.assertEqual(outside.read_bytes(), b"private")

    def test_registered_previous_custom_location_stays_manageable_after_deletion(self):
        previous = Path(self.temp.name) / "old-sources"
        previous.mkdir()
        source = previous / "past.mp4"
        source.write_bytes(b"previous")
        self.store.patch("projects", "p", source=str(source))
        self.client.delete("/api/projects/p")
        Locations(self.root).update({"sources": str(Path(self.temp.name) / "new-sources")})
        self.assertEqual(self.client.get("/api/storage").json()["bytes"], len(b"previous") + 6 + 4 + 7)
        self.assertEqual(self.remove(self.item("past.mp4")).status_code, 200)
        self.assertFalse(source.exists())

    def test_file_error_does_not_drop_export_record(self):
        item = self.item("clip.mp4")
        with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            self.assertEqual(self.remove(item).status_code, 500)
        self.assertIsNotNone(self.store.get("jobs", "clip"))
        self.assertTrue(self.clip.exists())

    def test_reimports_update_count_without_losing_dates_and_failed_imports_are_not_completed(self):
        self.store.patch("projects", "p", ready=True, title="新標題")
        self.store.delete_project("p")
        self.store.put("projects", {**self.project, "id": "second", "ready": False, "created": 456})
        self.store.patch("projects", "second", width=1920)
        item = public_history(Store(self.root))[0]
        self.assertEqual(item["import_count"], 2)
        self.assertEqual(item["first_imported_at"], 123)
        self.assertEqual(item["last_imported_at"], 456)
        self.assertEqual(item["project_id"], "second")
        self.store.put("projects", {**self.project, "id": "failed", "url": "https://www.youtube.com/watch?v=01234567890", "ready": False})
        self.store.delete_project("failed")
        self.assertFalse(next(i for i in public_history(self.store) if i["id"] == "01234567890")["completed"])

    def test_legacy_channel_receipts_recover_deleted_projects_idempotently(self):
        files = PrivateFiles(self.root)
        files.write("imports", {"channel:01234567890": "old"})
        tasks = [dict(video_id="01234567890", project_id="old", title="舊直播", created=100, channel={"id": "channel"})]
        for _ in range(2):
            backfill_legacy(self.store, files, tasks)
        item = next(i for i in public_history(self.store) if i["id"] == "01234567890")
        self.assertEqual(item["title"], "舊直播")
        self.assertEqual(item["import_count"], 1)
        self.assertEqual(item["first_imported_at"], 100)
        self.assertIsNone(item["project_id"])
