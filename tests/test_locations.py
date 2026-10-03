"""User-chosen folders for source videos, finished clips and previews."""

import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.storage.locations import LocationError, Locations, export_path, project_work
from game_vod_clipper.storage.inventory import video_storage
from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store
from game_vod_clipper.web_worker import SOURCE_PREFIX, run


class LocationTestCase(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="locations-test-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.outside = Path(self.temp.name) / "external"


class LocationsTest(LocationTestCase):
    def test_defaults_are_workspace_folders(self):
        status = Locations(self.root).status()
        self.assertEqual(status["sources"], {"path": str(self.root / "downloads"),
                                             "default": str(self.root / "downloads"), "custom": False})
        self.assertEqual(status["exports"]["path"], str(self.root / "clips"))
        self.assertEqual(status["cache"]["path"], str(self.root / "runs"))

    def test_custom_folder_is_created_saved_and_restored(self):
        target = self.outside / "新資料夾" / "clips"
        Locations(self.root).update({"exports": str(target)})
        self.assertTrue(target.is_dir())
        # A fresh reader, like the media worker process, sees the same choice.
        status = Locations(self.root).status()
        self.assertEqual(status["exports"], {"path": str(target.resolve()),
                                             "default": str(self.root / "clips"), "custom": True})
        self.assertFalse(status["sources"]["custom"])
        Locations(self.root).update({"exports": None})
        self.assertEqual(Locations(self.root).folder("exports"), self.root / "clips")
        Locations(self.root).update({"sources": str(target)})
        Locations(self.root).update({"sources": ""})
        self.assertFalse(Locations(self.root).status()["sources"]["custom"])

    def test_invalid_folders_are_rejected_without_changing_settings(self):
        existing_file = self.outside / "video.mp4"
        existing_file.parent.mkdir(parents=True)
        existing_file.write_bytes(b"x")
        for value in ("relative/folder", str(existing_file), str(self.root / "runs" / "web" / "youtube"),
                      Path(self.root.anchor).as_posix()):
            with self.subTest(value=value), self.assertRaises(LocationError):
                Locations(self.root).update({"sources": value})
        self.assertEqual(Locations(self.root).custom(), {})

    def test_unwritable_folder_is_rejected(self):
        target = self.outside / "locked"
        with patch("game_vod_clipper.storage.locations.tempfile.TemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(LocationError, "無法寫入"):
                Locations(self.root).update({"cache": str(target)})

    def test_corrupt_settings_fall_back_to_defaults(self):
        path = self.root / "runs" / "web" / "locations.json"
        path.parent.mkdir(parents=True)
        for content in ("{not json", "[]", json.dumps({"sources": "relative", "unknown": "/tmp"})):
            path.write_text(content, encoding="utf-8")
            self.assertEqual(Locations(self.root).folder("sources"), self.root / "downloads")

    def test_export_path_accepts_only_the_worker_layout(self):
        job = {"id": "job", "project_id": "project"}
        self.assertEqual(export_path(self.root, job), self.root / "clips" / "web" / "project" / "job.mp4")
        outside = self.outside / "web" / "project" / "job.mp4"
        self.assertEqual(export_path(self.root, job | {"output": str(outside)}), outside)
        for output in ("downloads/web/project/source.mkv", str(self.outside / "web" / "other" / "job.mp4"),
                       str(self.outside / "project" / "job.mp4")):
            with self.subTest(output=output), self.assertRaises(LocationError):
                export_path(self.root, job | {"output": output})

    def test_projects_keep_their_preview_folder(self):
        self.assertEqual(project_work(self.root, {"id": "old"}), self.root / "runs" / "web" / "old")
        work = self.outside / "cache" / "web" / "new"
        self.assertEqual(project_work(self.root, {"id": "new", "work": str(work)}), work)


class LocationApiTest(LocationTestCase):
    def test_read_update_and_reset(self):
        with TestClient(create_app(self.root)) as client:
            self.assertFalse(client.get("/api/locations").json()["exports"]["custom"])
            target = self.outside / "clips"
            updated = client.put("/api/locations", json={"exports": str(target)})
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(updated.json()["exports"]["path"], str(target.resolve()))
            # Fields not sent are left alone.
            client.put("/api/locations", json={"sources": str(self.outside / "sources")})
            self.assertTrue(client.get("/api/locations").json()["exports"]["custom"])
            self.assertFalse(client.put("/api/locations", json={"exports": None}).json()["exports"]["custom"])

    def test_invalid_requests(self):
        with TestClient(create_app(self.root)) as client:
            for body in ({"sources": "relative"}, {"sources": "/tmp/a\x00b"}, {"unknown": "/tmp"},
                         {"sources": "/" + "a" * 1000}):
                with self.subTest(body=body):
                    response = client.put("/api/locations", json=body)
                    self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(Locations(self.root).custom(), {})


class LocationStorageTest(LocationTestCase):
    def test_usage_counts_chosen_folders_and_files_left_in_defaults(self):
        (self.root / "clips" / "web" / "old").mkdir(parents=True)
        (self.root / "clips" / "web" / "old" / "clip.mp4").write_bytes(b"x" * 100)
        exports = self.outside / "clips"
        Locations(self.root).update({"exports": str(exports)})
        (exports / "web" / "new").mkdir(parents=True)
        (exports / "web" / "new" / "clip.mp4").write_bytes(b"x" * 20)
        (exports / "outside.mp4").symlink_to(self.root / "clips" / "web" / "old" / "clip.mp4")
        usage = video_storage(self.root)
        self.assertEqual(usage["categories"]["exports"], {"bytes": 120, "files": 2})


class LocationWorkerTest(LocationTestCase):
    @patch("game_vod_clipper.youtube.downloader.javascript_runtime", return_value="node:/tools/node")
    def test_youtube_download_goes_to_chosen_source_folder(self, runtime):
        sources = self.outside / "sources"
        Locations(self.root).update({"sources": str(sources)})
        store = Store(self.root)
        store.put("projects", {"id": "video", "url": "https://youtu.be/abcdefghijk"})
        store.put("jobs", {"id": "prepare", "project_id": "video", "kind": "prepare"})
        source = sources.resolve() / "web" / "video" / "source.mkv"
        source.parent.mkdir(parents=True)
        source.touch()
        with patch("game_vod_clipper.web_worker.command", return_value=SOURCE_PREFIX + str(source) + "\n") as command, patch(
            "game_vod_clipper.web_worker.probe", return_value={"duration": 16, "width": 320, "height": 180}
        ):
            run(self.root, "prepare")
        args = command.call_args_list[0].args[0]
        self.assertEqual(args[args.index("-o") + 1], str(source.parent / "source.%(ext)s"))
        self.assertEqual(store.get("projects", "video")["source"], str(source))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Install FFmpeg")
class LocationMediaTest(LocationTestCase):
    def wait_job(self, client, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = next(j for j in client.get("/api/state").json()["jobs"] if j["id"] == job_id)
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.05)
        self.fail("Media worker did not complete within 30s")

    def test_import_preview_and_export_use_chosen_folders_and_survive_a_later_change(self):
        sources, exports, cache = (self.outside / name for name in ("sources", "exports", "cache"))
        sources.mkdir(parents=True)
        video = sources / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
                        "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)],
                       check=True, capture_output=True)
        (self.root / "downloads").mkdir()
        shutil.copy(video, self.root / "downloads" / "workspace.mp4")
        with TestClient(create_app(self.root)) as client:
            chosen = client.put("/api/locations", json={"sources": str(sources), "exports": str(exports), "cache": str(cache)})
            self.assertEqual(chosen.status_code, 200, chosen.text)
            listed = client.get("/api/sources").json()
            self.assertEqual([item["path"] for item in listed], [str(video.resolve())])
            # Files in the previous default folder are no longer importable.
            self.assertEqual(client.post("/api/projects", json={"kind": "local", "source": "downloads/workspace.mp4"}).status_code, 422)

            imported = client.post("/api/projects", json={"kind": "local", "source": listed[0]["path"]}).json()
            project_id = imported["project"]["id"]
            self.assertNotIn("work", imported["project"])
            self.assertEqual(self.wait_job(client, imported["job"]["id"])["status"], "succeeded")
            self.assertFalse((cache / "web" / project_id / "preview.mp4").exists())
            self.assertTrue((cache / "web" / project_id / "thumb-001.jpg").is_file())
            self.assertFalse((self.root / "runs" / "web" / project_id).exists())

            draft = client.put(f"/api/projects/{project_id}/draft", json={
                "start": 1, "victory": 5, "postroll": 5, "reviewed": True, "revision": 0}).json()
            export = client.post(f"/api/projects/{project_id}/exports", json={"revision": draft["revision"]}).json()
            export = self.wait_job(client, export["id"])
            self.assertEqual(export["status"], "succeeded", export)
            output = exports.resolve() / "web" / project_id / f"{export['id']}.mp4"
            self.assertEqual(export["output_path"], str(output))
            self.assertTrue(output.is_file())
            receipt = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["source"], str(video.resolve()))
            self.assertEqual(client.get(f"/api/jobs/{export['id']}/download").status_code, 200)
            self.assertEqual(client.app.state.youtube.uploads.validate_export(export["id"])[1], output)

            # Changing a location only affects new files; this project keeps working.
            client.put("/api/locations", json={"sources": None, "exports": None, "cache": None})
            preview = client.get(f"/api/projects/{project_id}/media/source", headers={"Range": "bytes=0-9"})
            self.assertEqual(preview.status_code, 206)
            self.assertEqual(client.post(f"/api/projects/{project_id}/reset-analysis").status_code, 200)
            deleted = client.delete(f"/api/projects/{project_id}/clips/{export['id']}")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertFalse(output.exists() or output.with_suffix(".json").exists())
            self.assertTrue(video.is_file())


if __name__ == "__main__":
    unittest.main()
