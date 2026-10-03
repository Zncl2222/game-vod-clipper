"""Direct-source serving and early readiness; never touch an existing workspace."""

import copy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from yt_dlp import YoutubeDL

from game_vod_clipper.api.server import PREVIEW_RANGE_LIMIT
from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store
from game_vod_clipper import web_worker
from game_vod_clipper.youtube.downloader import BROWSER_MERGE_FORMATS, quality_format

ROOT = Path(__file__).resolve().parents[1]


class BrowserContainerTest(unittest.TestCase):
    def test_container_selection_preserves_highest_video_and_audio_streams(self):
        for video, audio, expected in (
            (("vp9", "webm"), ("opus", "webm"), "webm"),
            (("av01.0.12M.08", "mp4"), ("opus", "webm"), "webm"),
            (("av01.0.12M.08", "mp4"), ("mp4a.40.2", "m4a"), "mp4"),
            (("avc1.640033", "mp4"), ("mp4a.40.2", "m4a"), "mp4"),
            (("vp9", "webm"), ("mp4a.40.2", "m4a"), "mkv"),
        ):
            with self.subTest(video=video, audio=audio):
                formats = [
                    {"format_id": "best-video", "url": "https://example.invalid/v", "ext": video[1],
                     "vcodec": video[0], "acodec": "none", "width": 3840, "height": 2160, "fps": 60},
                    {"format_id": "best-audio", "url": "https://example.invalid/a", "ext": audio[1],
                     "vcodec": "none", "acodec": audio[0], "abr": 160},
                    {"format_id": "lower-h264", "url": "https://example.invalid/lower.mp4", "ext": "mp4",
                     "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "height": 1080, "fps": 30},
                ]
                with YoutubeDL({"quiet": True, "no_warnings": True, "format": quality_format(),
                                "format_sort": ["res", "fps"], "merge_output_format": BROWSER_MERGE_FORMATS}) as ydl:
                    result = ydl.process_ie_result({"id": "fixture", "title": "fixture", "formats": copy.deepcopy(formats)}, download=False)
                self.assertEqual(result["ext"], expected)
                self.assertEqual((result["height"], result["fps"]), (2160, 60))
                self.assertEqual([f["format_id"] for f in result["requested_formats"]], ["best-video", "best-audio"])


class DirectSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="direct-source-", dir=ROOT / "runs")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.source = self.root / "downloads" / "source.webm"
        self.source.parent.mkdir()
        self.source.write_bytes(bytes(range(256)) * 4)
        self.project = {"id": "direct", "ready": True, "playback": "source", "source": "downloads/source.webm", "thumbnails": []}
        self.store.put("projects", self.project)

    def test_range_mime_access_checks_and_legacy_preview(self):
        with TestClient(create_app(self.root)) as client:
            url = "/api/projects/direct/media/source"
            response = client.get(url, headers={"Range": "bytes=100-199"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, self.source.read_bytes()[100:200])
            self.assertEqual(response.headers["content-type"], "video/webm")
            self.assertEqual(response.headers["content-range"], "bytes 100-199/1024")
            self.assertEqual(client.get(url, headers={"Range": "bytes=-10"}).content, self.source.read_bytes()[-10:])
            self.assertEqual(client.get(url, headers={"Range": "bytes=2048-"}).status_code, 416)
            for name in ("source.webm", "state.sqlite3", "preview.mp4", "missing"):
                self.assertEqual(client.get(f"/api/projects/direct/media/{name}").status_code, 404)
            self.assertEqual(client.get(url, headers={"Origin": "https://example.invalid"}).status_code, 403)
            self.store.patch("projects", "direct", ready=False)
            self.assertEqual(client.get(url).status_code, 404)
            self.store.patch("projects", "direct", ready=True)
            self.source.unlink()
            self.assertEqual(client.get(url).status_code, 404)
            other = self.source.with_name("other.webm")
            other.write_bytes(b"unregistered data")
            self.source.symlink_to(other)
            self.assertEqual(client.get(url).status_code, 404)

            legacy = self.root / "runs" / "web" / "old" / "preview.mp4"
            legacy.parent.mkdir()
            legacy.write_bytes(b"old-preview")
            self.store.put("projects", {"id": "old", "ready": True, "thumbnails": []})
            self.assertEqual(client.get("/api/projects/old/media/preview.mp4").content, b"old-preview")

    def test_open_range_is_bounded_for_large_original(self):
        with self.source.open("r+b") as stream:
            stream.truncate(PREVIEW_RANGE_LIMIT * 2)
        with TestClient(create_app(self.root)) as client:
            response = client.get("/api/projects/direct/media/source", headers={"Range": "bytes=0-"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(len(response.content), PREVIEW_RANGE_LIMIT)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Install trusted FFmpeg")
    def test_ready_before_thumbnails_and_thumbnail_failure_preserves_edits(self):
        source = self.source.with_suffix(".mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=60",
                        "-t", "12", "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", str(source)], check=True)
        self.store.patch("projects", "direct", ready=False, source="downloads/source.mp4")
        self.store.put("jobs", {"id": "prepare", "project_id": "direct", "kind": "prepare"})
        original_command = web_worker.command
        seeks = []

        def command(args, **kwargs):
            if "-frames:v" in args:
                project = self.store.get("projects", "direct")
                self.assertTrue(project["ready"])
                self.assertEqual(project["frame_rate"], 60)
                self.assertLess(args.index("-ss"), args.index("-i"))
                seeks.append(float(args[args.index("-ss") + 1]))
                # A user can edit while thumbnails are being prepared.
                self.store.patch("projects", "direct", draft=project["draft"] | {"start": 1, "revision": 1})
                if len(seeks) == 3:
                    raise RuntimeError("unreadable frame")
            return original_command(args, **kwargs)

        with patch.object(web_worker, "command", side_effect=command):
            web_worker.run(self.root, "prepare")
        project = self.store.get("projects", "direct")
        self.assertEqual(seeks, [0, .5, 1])
        self.assertTrue(project["ready"])
        self.assertEqual(project["draft"]["revision"], 1)
        self.assertEqual(project["draft"]["start"], 1)
        self.assertEqual(len(project["thumbnails"]), 2)
        self.assertTrue(project["thumbnail_warning"])
        self.assertFalse((self.root / "runs" / "web" / "direct" / "preview.mp4").exists())


if __name__ == "__main__":
    unittest.main()
