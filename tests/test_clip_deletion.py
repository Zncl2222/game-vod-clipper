"""Deleting a finished clip must not remove source media or other exports."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store


class ClipDeletionTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="clip-delete-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.draft = dict(start=10, victory=20, postroll=8, reviewed=False, revision=1, origin="manual")
        for pid in ("one", "two"):
            self.store.put("projects", dict(id=pid, ready=True, title=pid, duration=60, thumbnails=[],
                                           source="downloads/source.mp4", draft=self.draft))
        for jid in ("clip", "other"):
            self.store.put("jobs", dict(id=jid, project_id="one", kind="export", status="succeeded",
                                       output=f"clips/web/one/{jid}.mp4", draft=self.draft, edit_draft=self.draft))
        self.paths = [self.root / name for name in ("downloads/source.mp4", "clips/web/one/clip.mp4",
                      "clips/web/one/clip.json", "clips/web/one/other.mp4", "runs/web/one/preview.mp4")]
        for path in self.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        self.client = self.enterContext(TestClient(self.app))
        self.url = "/api/projects/one/clips/clip"

    def test_delete_removes_only_its_files_and_record_and_persists(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["deleted"])
        self.assertIsNone(Store(self.root).get("jobs", "clip"))
        self.assertFalse(self.paths[1].exists())
        self.assertFalse(self.paths[2].exists())
        for path in (self.paths[0], self.paths[3], self.paths[4]):
            self.assertEqual(path.read_bytes(), b"fixture")
        self.assertEqual(self.store.get("projects", "one")["draft"], self.draft)
        self.assertEqual([job["id"] for job in self.client.get("/api/state").json()["jobs"]], ["other"])
        self.assertEqual(self.client.get("/api/jobs/clip/download").status_code, 404)
        self.assertEqual(self.client.put(self.url + "/draft", json=self.draft).status_code, 404)
        self.assertEqual(self.client.delete(self.url).status_code, 404)

    def test_wrong_project_unfinished_and_non_export_jobs_are_rejected(self):
        for pid in ("two", "missing"):
            self.assertEqual(self.client.delete(f"/api/projects/{pid}/clips/clip").status_code, 404)
        for changes in ({"status": "running"}, {"status": "failed"}, {"kind": "analyze"}):
            self.store.patch("jobs", "clip", **({"status": "succeeded", "kind": "export"} | changes))
            self.assertEqual(self.client.delete(self.url).status_code, 404)
            self.assertEqual(self.paths[1].read_bytes(), b"fixture")

    def test_missing_files_do_not_leave_an_undeletable_record(self):
        self.paths[1].unlink()
        self.paths[2].unlink()
        self.assertEqual(self.client.delete(self.url).status_code, 200)
        self.assertIsNone(self.store.get("jobs", "clip"))

    def test_path_tampering_and_symlinks_cannot_delete_source(self):
        self.store.patch("jobs", "clip", output="downloads/source.mp4")
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.store.patch("jobs", "clip", output="clips/web/one/clip.mp4")
        self.paths[2].unlink()
        self.paths[2].symlink_to(self.paths[0])
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.assertEqual(self.paths[1].read_bytes(), b"fixture")
        self.assertEqual(self.paths[0].read_bytes(), b"fixture")
        self.assertIsNotNone(self.store.get("jobs", "clip"))

    def test_clip_imported_as_another_projects_source_is_protected(self):
        self.store.patch("projects", "two", source="clips/web/one/clip.mp4")
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.assertTrue(self.paths[1].exists())

    def test_active_upload_blocks_deletion_but_completed_upload_is_retained(self):
        uploads = self.app.state.youtube.uploads
        uploads.records["upload"] = dict(id="upload", export_id="clip", status="uploading")
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.assertTrue(self.paths[1].exists())
        uploads.records["upload"]["status"] = "succeeded"
        self.assertEqual(self.client.delete(self.url).status_code, 200)
        self.assertEqual(uploads.records["upload"]["status"], "succeeded")

    def test_file_error_preserves_record_for_retry(self):
        with patch.object(Path, "unlink", side_effect=PermissionError("busy")):
            self.assertEqual(self.client.delete(self.url).status_code, 500)
        self.assertIsNotNone(self.store.get("jobs", "clip"))
        self.assertEqual(self.client.delete(self.url).status_code, 200)

    def test_derived_exports_keep_their_own_draft_after_parent_is_deleted(self):
        self.store.patch("jobs", "other", source_job_id="clip")
        self.assertEqual(self.client.delete(self.url).status_code, 200)
        self.assertEqual(self.store.get("jobs", "other")["draft"], self.draft)
        response = self.client.put("/api/projects/one/clips/other/draft", json=self.draft)
        self.assertEqual(response.status_code, 200, response.text)

    def test_published_uploads_are_flagged_and_bulk_removed(self):
        uploads = self.app.state.youtube.uploads
        uploads.records["done"] = dict(id="done", export_id="clip", status="succeeded", video_id="abcdefghijk",
                                       playlist_id="PLwins", playlist_title="勝利", playlist_status="added")
        uploads.records["waiting"] = dict(id="waiting", export_id="other", status="paused", video_id="bcdefghijkl",
                                          playlist_id="PLwins", playlist_status="pending")
        jobs = {job["id"]: job for job in self.client.get("/api/state").json()["jobs"]}
        self.assertTrue(jobs["clip"]["youtube_upload"]["published"])
        self.assertFalse(jobs["other"]["youtube_upload"]["published"])
        response = self.client.post("/api/projects/one/clips/remove-published")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"deleted": ["clip"], "bytes": len(b"fixture")})
        self.assertFalse(self.paths[1].exists())
        for path in (self.paths[0], self.paths[3]):
            self.assertTrue(path.exists())
        self.assertIsNotNone(self.store.get("jobs", "other"))
        self.assertIn("done", uploads.records)

    def test_failed_playlist_placement_is_not_treated_as_published(self):
        uploads = self.app.state.youtube.uploads
        uploads.records["done"] = dict(id="done", export_id="clip", status="succeeded", video_id="abcdefghijk",
                                       playlist_id="PLwins", playlist_status="failed")
        response = self.client.post("/api/projects/one/clips/remove-published")
        self.assertEqual(response.json(), {"deleted": [], "bytes": 0})
        self.assertTrue(self.paths[1].exists())
