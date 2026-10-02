"""Project management uses isolated metadata; no user media or AI calls."""

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store


class ProjectManagementTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="project-test-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.project = {"id": "p", "title": "Original", "ready": True, "duration": 100,
                        "source": "downloads/source.mp4", "url": None, "thumbnails": [],
                        "draft": {"start": 1, "victory": 50, "postroll": 8, "revision": 2, "reviewed": True}}
        self.store.put("projects", self.project)
        self.store.put("projects", {**self.project, "id": "other"})
        self.store.put("jobs", {"id": "export", "project_id": "p", "kind": "export", "status": "succeeded"})
        self.store.put("jobs", {"id": "other-job", "project_id": "other", "kind": "analyze", "status": "failed"})
        self.client = self.enterContext(TestClient(self.app))

    def test_rename_persists_and_preserves_edits_source_and_job_history(self):
        response = self.client.patch("/api/projects/p", json={"title": "  Boss victory 新名稱  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Boss victory 新名稱")
        self.assertNotIn("source", response.json())
        # Worker updates made after a rename cannot put the old title back.
        self.store.patch("projects", "p", ready=True, width=1920)
        saved = Store(self.root).get("projects", "p")
        self.assertEqual(saved["title"], "Boss victory 新名稱")
        self.assertEqual(saved["draft"], self.project["draft"])
        self.assertEqual(saved["source"], self.project["source"])
        self.assertIsNotNone(self.store.get("jobs", "export"))
        self.assertEqual(self.store.get("projects", "other")["title"], "Original")

    def test_invalid_names_and_unknown_projects_are_rejected(self):
        for body in ({"title": "  "}, {"title": "x" * 121}, {"title": "one\ntwo"},
                     {"title": 5}, {"title": "valid", "source": "elsewhere"}):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch("/api/projects/p", json=body).status_code, 422)
        self.assertEqual(self.store.get("projects", "p")["title"], "Original")
        for method in ("get", "patch", "delete"):
            options = {"json": {"title": "new"}} if method == "patch" else {}
            self.assertEqual(getattr(self.client, method)("/api/projects/missing", **options).status_code, 404)

    def test_details_expose_source_only_on_explicit_request(self):
        response = self.client.get("/api/projects/p")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "downloads/source.mp4")
        self.assertTrue(all("source" not in p for p in self.client.get("/api/state").json()["projects"]))

    def test_delete_removes_only_its_records_and_keeps_files(self):
        files = ["downloads/source.mp4", "clips/web/p/export.mp4", "runs/web/p/preview.mp4"]
        for relative in files:
            file = self.root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"fixture")
        response = self.client.delete("/api/projects/p")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertIsNone(self.store.get("projects", "p"))
        self.assertIsNone(self.store.get("jobs", "export"))
        self.assertIsNotNone(self.store.get("projects", "other"))
        self.assertIsNotNone(self.store.get("jobs", "other-job"))
        for relative in files:
            self.assertEqual((self.root / relative).read_bytes(), b"fixture")
        self.assertEqual(self.client.delete("/api/projects/p").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/export/download").status_code, 404)

    def test_delete_waits_for_worker_cleanup_and_blocks_new_mutations(self):
        source = self.root / "downloads" / "new.mp4"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b"fixture")
        started = threading.Event()
        cleaning = threading.Event()
        release = threading.Event()
        cleanup_has_project = []

        async def worker(manager, job_id):
            job = manager.store.patch("jobs", job_id, status="running")
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaning.set()
                await asyncio.to_thread(release.wait, 5)
                cleanup_has_project.append(manager.store.get("projects", job["project_id"]) is not None)
                manager.store.patch("jobs", job_id, status="cancelled")

        with patch("game_vod_clipper.jobs.scheduler.Jobs.execute", new=worker):
            result = self.client.post("/api/projects", json={"kind": "local", "source": "downloads/new.mp4"}).json()
            project_id, job_id = result["project"]["id"], result["job"]["id"]
            self.assertTrue(started.wait(2))
            with ThreadPoolExecutor(max_workers=1) as executor:
                deleted = executor.submit(self.client.delete, f"/api/projects/{project_id}")
                try:
                    self.assertTrue(cleaning.wait(2))
                    self.assertFalse(deleted.done())
                    self.assertEqual(self.client.patch(f"/api/projects/{project_id}", json={"title": "late"}).status_code, 409)
                    self.assertEqual(self.client.post(f"/api/jobs/{job_id}/retry").status_code, 409)
                    self.assertEqual(self.client.post(f"/api/projects/{project_id}/exports", json={"revision": 0}).status_code, 409)
                finally:
                    release.set()
                self.assertEqual(deleted.result(timeout=5).status_code, 200)
            self.assertEqual(cleanup_has_project, [True])
            self.assertIsNone(self.store.get("jobs", job_id))
            self.assertIsNone(self.store.get("projects", project_id))


if __name__ == "__main__":
    unittest.main()
