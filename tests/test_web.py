"""POC integration checks with synthetic media; no network or user video required."""

import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    from game_vod_clipper.web import create_app
    from game_vod_clipper.api.sources import youtube_url

    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False


@unittest.skipUnless(
    WEB_AVAILABLE and shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "Install web/test extras and FFmpeg",
)
class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="web-test-", dir=runs)
        cls.root = Path(cls.temp.name)
        (cls.root / "downloads").mkdir()
        cls.source = cls.root / "downloads" / "synthetic.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000",
                "-t",
                "16",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(cls.source),
            ],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def wait_job(self, client, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = next(
                j for j in client.get("/api/state").json()["jobs"] if j["id"] == job_id
            )
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.05)
        self.fail("Media worker did not complete within 30s")

    def test_real_import_direct_playback_export_and_persistence(self):
        app = create_app(self.root)
        with TestClient(app) as client:
            imported = client.post(
                "/api/projects",
                json={"kind": "local", "source": "downloads/synthetic.mp4"},
            )
            self.assertEqual(imported.status_code, 202, imported.text)
            data = imported.json()
            project_id = data["project"]["id"]
            job = self.wait_job(client, data["job"]["id"])
            self.assertEqual(job["status"], "succeeded", job)
            project = next(
                p
                for p in client.get("/api/state").json()["projects"]
                if p["id"] == project_id
            )
            self.assertTrue(project["ready"])
            self.assertEqual(project["playback"], "source")
            self.assertEqual(project["frame_rate"], 30)
            self.assertEqual(project["video_codec"], "h264")
            self.assertNotIn("source", project)
            self.assertFalse((self.root / "runs" / "web" / project_id / "preview.mp4").exists())
            self.assertGreaterEqual(len(project["thumbnails"]), 23)
            preview = client.get(
                f"/api/projects/{project_id}/media/source",
                headers={"Range": "bytes=0-99"},
            )
            self.assertEqual(preview.status_code, 206)
            self.assertEqual(len(preview.content), 100)
            self.assertEqual(preview.content, self.source.read_bytes()[:100])
            self.assertEqual(preview.headers["content-type"], "video/mp4")
            self.assertEqual(client.get(f"/api/projects/{project_id}/media/preview.mp4").status_code, 404)
            self.assertEqual(
                client.get(f"/api/projects/{project_id}/media/source.mp4").status_code,
                404,
            )
            draft_url = f"/api/projects/{project_id}/draft"
            export_url = f"/api/projects/{project_id}/exports"
            draft = {
                "start": 1.25,
                "victory": 8.0,
                "postroll": 5,
                "reviewed": False,
                "revision": 0,
            }
            for invalid in (
                {"start": 9},
                {"victory": 15},
                {"postroll": 4},
                {"start": "Infinity"},
            ):
                self.assertEqual(
                    client.put(draft_url, json=draft | invalid).status_code, 422
                )
            saved = client.put(draft_url, json=draft).json()
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(client.put(draft_url, json=draft).status_code, 409)
            exported = client.post(
                export_url, json={"revision": saved["revision"]}
            ).json()
            duplicate = client.post(
                export_url, json={"revision": saved["revision"]}
            ).json()
            self.assertEqual(exported["id"], duplicate["id"])
            self.assertFalse(exported["draft"]["reviewed"])
            # A new draft must not mutate the already queued export snapshot.
            client.put(draft_url, json=saved | {"start": 2, "reviewed": False})
            job = self.wait_job(client, exported["id"])
            self.assertEqual(job["status"], "succeeded", job)
            self.assertEqual(job["draft"]["start"], 1.25)
            result = client.get(f"/api/jobs/{job['id']}/download")
            self.assertEqual(result.status_code, 200)
            self.assertIn("attachment", result.headers["content-disposition"])
            output = self.root / "clips" / "web" / project_id / f"{job['id']}.mp4"
            metadata = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_format",
                        "-of",
                        "json",
                        str(output),
                    ]
                )
            )
            self.assertAlmostEqual(
                float(metadata["format"]["duration"]), 11.75, delta=0.1
            )
            self.assertTrue(output.with_suffix(".json").is_file())
            # The publishing boundary accepts the actual worker's validated export receipt.
            _, publishable = app.state.youtube.uploads.validate_export(job["id"])
            self.assertEqual(publishable, output)
            original_bytes = output.read_bytes()
            clip_url = f"/api/projects/{project_id}/clips/{job['id']}/draft"
            edited = client.put(clip_url, json=job["draft"] | {"start": 2, "revision": 0, "reviewed": True}).json()
            second = client.post(export_url, json={"revision": edited["revision"], "source_job_id": job["id"]}).json()
            second = self.wait_job(client, second["id"])
            self.assertEqual(second["status"], "succeeded", second)
            second_path = self.root / "clips" / "web" / project_id / f"{second['id']}.mp4"
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(second_path)]))
            self.assertAlmostEqual(float(info["format"]["duration"]), 11, delta=0.1)
            self.assertEqual(output.read_bytes(), original_bytes)
            self.assertEqual(second["source_job_id"], job["id"])
        with TestClient(create_app(self.root)) as client:
            project = next(
                p
                for p in client.get("/api/state").json()["projects"]
                if p["id"] == project_id
            )
            self.assertEqual(project["draft"]["start"], 2)
            self.assertFalse(project["draft"]["reviewed"])

    def test_paths_hosts_and_origins(self):
        with TestClient(create_app(self.root)) as client:
            for source in ("../../etc/passwd", "/etc/passwd", "downloads/missing.mp4"):
                self.assertEqual(
                    client.post(
                        "/api/projects", json={"kind": "local", "source": source}
                    ).status_code,
                    422,
                )
            self.assertEqual(
                client.get("/api/state", headers={"Host": "evil.example"}).status_code,
                400,
            )
            self.assertEqual(
                client.post(
                    "/api/projects",
                    headers={"Origin": "https://evil.example"},
                    json={"kind": "local", "source": "downloads/synthetic.mp4"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/state", headers={"Sec-Fetch-Site": "cross-site"}
                ).status_code,
                403,
            )
            self.assertEqual(client.get("/api/jobs/missing/download").status_code, 404)

    def test_youtube_canonicalization(self):
        self.assertEqual(
            youtube_url("https://youtu.be/abcdefghijk?t=8"),
            "https://www.youtube.com/watch?v=abcdefghijk",
        )
        for value in (
            "http://youtu.be/abcdefghijk",
            "https://youtube.com.evil.test/watch?v=abcdefghijk",
            "https://127.0.0.1/watch?v=abcdefghijk",
            "https://youtube.com/playlist?list=abc",
            "https://user:pass@youtube.com/watch?v=abcdefghijk",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                youtube_url(value)

    def test_cancel_and_recover_interrupted_job(self):
        app = create_app(self.root)
        with TestClient(app) as client:
            data = client.post(
                "/api/projects",
                json={"kind": "local", "source": "downloads/synthetic.mp4"},
            ).json()
            job_id = data["job"]["id"]
            self.assertEqual(
                client.post(f"/api/jobs/{job_id}/cancel").json()["status"], "cancelled"
            )
            app.state.store.patch("jobs", job_id, status="running")
        with TestClient(create_app(self.root)) as client:
            job = next(
                j for j in client.get("/api/state").json()["jobs"] if j["id"] == job_id
            )
            self.assertEqual(job["status"], "interrupted")
            retried = client.post(f"/api/jobs/{job_id}/retry")
            self.assertEqual(retried.status_code, 202)
            client.post(f"/api/jobs/{retried.json()['id']}/cancel")


@unittest.skipUnless(WEB_AVAILABLE, "Install web/test extras")
class RangeLimitTest(unittest.TestCase):
    def test_open_ended_ranges_are_capped(self):
        from fastapi import FastAPI

        from game_vod_clipper.api.server import LocalFileResponse

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "preview.mp4"
            data = bytes(range(256)) * 4
            path.write_bytes(data)
            app = FastAPI()
            app.get("/capped")(lambda: LocalFileResponse(path, range_limit=100))
            app.get("/full")(lambda: LocalFileResponse(path))
            client = TestClient(app)
            cases = [
                ("/capped", "bytes=0-", "bytes 0-99/1024", data[:100]),
                ("/capped", "bytes=1000-", "bytes 1000-1023/1024", data[1000:]),
                ("/capped", "bytes=10-509", "bytes 10-509/1024", data[10:510]),
                ("/full", "bytes=0-", "bytes 0-1023/1024", data),
            ]
            for url, requested, content_range, body in cases:
                with self.subTest(url=url, range=requested):
                    response = client.get(url, headers={"Range": requested})
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response.headers["content-range"], content_range)
                    self.assertEqual(response.content, body)
            self.assertEqual(client.get("/capped").content, data)


if __name__ == "__main__":
    unittest.main()
