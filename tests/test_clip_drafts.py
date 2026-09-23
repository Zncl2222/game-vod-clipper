"""Finished-clip editing is isolated from source drafts and immutable exports."""

import tempfile
import unittest
from urllib.parse import unquote
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.web import Jobs, create_app
from game_vod_clipper.web_store import Store


async def no_media_worker(_self, _job_id):
    pass


class ClipDraftTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="clip-drafts-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.original = dict(start=10, victory=20, postroll=8, reviewed=True, revision=4, origin="manual")
        for pid in ["one", "two"]:
            self.store.put("projects", dict(id=pid, title=pid, ready=True, duration=90, thumbnails=[], draft=self.original))
        self.store.put("jobs", dict(id="clip", project_id="one", kind="export", status="succeeded", draft=self.original, progress=100))
        self.worker = patch.object(Jobs, "execute", new=no_media_worker)
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.client = self.enterContext(TestClient(create_app(self.root)))
        self.url = "/api/projects/one/clips/clip/draft"
        self.draft = self.original | dict(start=9, revision=0, reviewed=False)

    def test_save_does_not_mutate_source_or_existing_export_and_persists(self):
        result = self.client.put(self.url, json=self.draft)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["revision"], 1)
        self.assertEqual(self.store.get("projects", "one")["draft"], self.original)
        clip = Store(self.root).get("jobs", "clip")
        self.assertEqual(clip["draft"], self.original)
        self.assertEqual(clip["edit_draft"], result.json())
        state = self.client.get("/api/state").json()
        self.assertEqual(state["jobs"][0]["edit_draft"], result.json())

    def test_stale_revision_and_invalid_ranges_are_rejected(self):
        self.assertEqual(self.client.put(self.url, json=self.draft).status_code, 200)
        self.assertEqual(self.client.put(self.url, json=self.draft).status_code, 409)
        for invalid in [dict(start=20), dict(start=-1), dict(victory=88), dict(postroll=4), dict(postroll=11), dict(start="NaN")]:
            with self.subTest(invalid=invalid):
                result = self.client.put(self.url, json=self.draft | dict(revision=1) | invalid)
                self.assertEqual(result.status_code, 422, result.text)

    def test_only_completed_exports_owned_by_project_can_be_edited(self):
        self.assertEqual(self.client.put("/api/projects/two/clips/clip/draft", json=self.draft).status_code, 404)
        self.assertEqual(self.client.put("/api/projects/missing/clips/clip/draft", json=self.draft).status_code, 404)
        for change in [dict(status="failed"), dict(status="running"), dict(kind="analyze"), dict(draft=None)]:
            with self.subTest(change=change):
                self.store.patch("jobs", "clip", kind="export", status="succeeded", draft=self.original)
                self.store.patch("jobs", "clip", **change)
                self.assertEqual(self.client.put(self.url, json=self.draft).status_code, 404)
                self.assertEqual(self.client.post("/api/projects/one/exports", json=dict(revision=0, source_job_id="clip")).status_code, 404)

    def test_export_accepts_unchecked_draft_and_keeps_an_independent_snapshot(self):
        saved = self.client.put(self.url, json=self.draft).json()
        export = "/api/projects/one/exports"
        body = dict(revision=saved["revision"], source_job_id="clip")
        created = self.client.post(export, json=body)
        self.assertEqual(created.status_code, 202, created.text)
        result = created.json()
        self.assertNotEqual(result["id"], "clip")
        self.assertEqual(result["source_job_id"], "clip")
        self.assertEqual(result["draft"], saved)
        self.assertFalse(result["draft"]["reviewed"])
        self.assertEqual(self.client.post(export, json=body).json()["id"], result["id"])
        self.client.put(self.url, json=saved | dict(start=8, reviewed=False))
        self.assertEqual(self.store.get("jobs", result["id"])["draft"], saved)
        self.assertEqual(self.store.get("projects", "one")["draft"], self.original)
        self.assertEqual(self.store.get("jobs", "clip")["draft"], self.original)
        self.assertEqual(self.client.post(export, json=body).status_code, 409)

    def test_export_still_rejects_invalid_stored_ranges_without_a_review_gate(self):
        for change in (dict(start=20), dict(victory=85), dict(postroll=4), dict(postroll=11)):
            with self.subTest(change=change):
                self.store.patch("jobs", "clip", edit_draft=self.draft | change)
                response = self.client.post("/api/projects/one/exports", json=dict(revision=0, source_job_id="clip"))
                self.assertEqual(response.status_code, 422, response.text)

    def test_export_deduplication_is_scoped_to_the_editing_target(self):
        self.store.put("jobs", dict(id="other", project_id="one", kind="export", status="succeeded", draft=self.original, progress=100))
        bodies = []
        for cid in ["clip", "other"]:
            saved = self.client.put(f"/api/projects/one/clips/{cid}/draft", json=self.draft | dict(reviewed=True)).json()
            bodies.append(dict(revision=saved["revision"], source_job_id=cid))
        jobs = [self.client.post("/api/projects/one/exports", json=body).json() for body in bodies]
        self.assertNotEqual(jobs[0]["id"], jobs[1]["id"])
        for body, job in zip(bodies, jobs):
            self.assertEqual(self.client.post("/api/projects/one/exports", json=body).json()["id"], job["id"])

    def test_retry_retains_source_clip_identity(self):
        self.store.put("jobs", dict(id="failed", project_id="one", kind="export", status="failed", draft=self.original, source_job_id="clip"))
        retry = self.client.post("/api/jobs/failed/retry")
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(retry.json()["source_job_id"], "clip")

    def test_source_and_clip_exports_with_same_revision_are_distinct(self):
        saved = self.client.put(self.url, json=self.draft | dict(reviewed=True)).json()
        self.store.patch("projects", "one", draft=saved)
        original = self.client.post("/api/projects/one/exports", json=dict(revision=1)).json()
        edited = self.client.post("/api/projects/one/exports", json=dict(revision=1, source_job_id="clip")).json()
        self.assertNotEqual(original["id"], edited["id"])
        self.assertIsNone(original["source_job_id"])
        self.assertEqual(edited["source_job_id"], "clip")

    def test_names_persist_in_source_clip_and_export_snapshots(self):
        title = "瑪蓮妮亞・無傷通關"
        saved = self.client.put(self.url, json=self.draft | {"title": title}).json()
        exported = self.client.post("/api/projects/one/exports", json={"revision": saved["revision"], "source_job_id": "clip"}).json()
        self.assertEqual(exported["draft"]["title"], title)
        self.assertNotIn("title", self.store.get("jobs", "clip")["draft"])
        self.assertEqual(Store(self.root).get("jobs", "clip")["edit_draft"]["title"], title)
        response = self.client.put("/api/projects/one/draft", json=self.original | {"title": "原片草稿"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Store(self.root).get("projects", "one")["draft"]["title"], "原片草稿")
        for invalid in ["x" * 101, "名稱\n換行", "名稱\x00", 123]:
            with self.subTest(title=invalid):
                self.assertEqual(self.client.put(self.url, json=saved | {"title": invalid}).status_code, 422)

    def test_named_download_uses_safe_filename_without_renaming_stored_media(self):
        output = self.root / "clips/web/one/clip.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"fixture")
        self.store.patch("jobs", "clip", output="clips/web/one/clip.mp4",
                         draft=self.original | {"title": "Boss / 瑪蓮妮亞"})
        response = self.client.get("/api/jobs/clip/download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boss _ 瑪蓮妮亞.mp4", unquote(response.headers["content-disposition"]))
        self.assertEqual(output.read_bytes(), b"fixture")


if __name__ == "__main__":
    unittest.main()
