"""Offline source-quality selection and real full-resolution export regressions."""

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from yt_dlp import YoutubeDL

from game_vod_clipper.web import Jobs, create_app
from game_vod_clipper.web_store import Store
from game_vod_clipper.web_worker import SOURCE_PREFIX, run
from game_vod_clipper.youtube import quality_format

ROOT = Path(__file__).resolve().parents[1]


class DownloadQualityTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "runs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="quality-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_real_ytdlp_selector_prefers_resolution_fps_and_keeps_audio(self):
        formats = [dict(format_id=f"{height}-{fps}", url=f"https://example.invalid/{height}-{fps}.webm",
                        height=height, width=height * 16 // 9, fps=fps, ext="webm", vcodec="vp9", acodec="none")
                   for height, fps in ((360, 30), (480, 30), (720, 60), (1080, 60), (1440, 30), (1440, 60), (2160, 30))]
        # A broadly compatible H264 format must not outrank higher-resolution VP9.
        formats.append(dict(format_id="1080-h264", url="https://example.invalid/avc.mp4", height=1080,
                            width=1920, fps=60, ext="mp4", vcodec="avc1", acodec="none"))
        formats.append(dict(format_id="audio", url="https://example.invalid/audio.m4a", ext="m4a", vcodec="none", acodec="mp4a", abr=128))
        for quality, expected in (("best", 2160), ("2160", 2160), ("1440", 1440), ("1080", 1080), ("720", 720), ("480", 480)):
            with self.subTest(quality=quality), YoutubeDL({"quiet": True, "no_warnings": True,
                    "format": quality_format(quality), "format_sort": ["res", "fps"]}) as downloader:
                selected = downloader.process_ie_result({"id": "fixture", "title": "fixture", "formats": copy.deepcopy(formats)}, download=False)
                self.assertEqual(selected["height"], expected)
                self.assertEqual(selected["requested_formats"][1]["format_id"], "audio")
                if quality == "1440":
                    self.assertEqual(selected["fps"], 60)
        # Choosing 1440p for a 1080p source keeps the actual available resolution.
        with YoutubeDL({"quiet": True, "no_warnings": True, "format": quality_format("1440"), "format_sort": ["res", "fps"]}) as downloader:
            selected = downloader.process_ie_result({"id": "lower", "title": "lower", "formats": [f for f in formats if f.get("height", 0) <= 1080]}, download=False)
            self.assertEqual(selected["height"], 1080)

    def test_url_and_account_imports_validate_and_persist_quality_before_worker_starts(self):
        with patch.object(Jobs, "execute", new=AsyncMock()), TestClient(create_app(self.root)) as client:
            for quality in (None, "1440", "720"):
                body = {"kind": "youtube", "source": "https://www.youtube.com/watch?v=abcdefghijk"}
                if quality:
                    body["download_quality"] = quality
                response = client.post("/api/projects", json=body)
                self.assertEqual(response.status_code, 202, response.text)
                project = Store(self.root).get("projects", response.json()["project"]["id"])
                self.assertEqual(project["download_quality"], quality or "best")
            for invalid in ("9999", "1440p", 1440, "best;echo bad"):
                self.assertEqual(client.post("/api/projects", json=body | {"download_quality": invalid}).status_code, 422)
                for path in ("/api/youtube/broadcasts/abcdefghijk/import", "/api/youtube/imports"):
                    response = client.post(path, json={"channel_id": "channel", "auto_analyze": False,
                        "download_quality": invalid, **({"videos": [{"id": "abcdefghijk"}]} if path.endswith("imports") else {})})
                    self.assertEqual(response.status_code, 422)

    def test_worker_uses_saved_choice_and_legacy_missing_choice_defaults_to_best(self):
        for quality in (None, "best", "1440", "720"):
            with self.subTest(quality=quality):
                store = Store(self.root)
                store.put("projects", {"id": "video", "url": "https://youtu.be/abcdefghijk",
                                       **({"download_quality": quality} if quality else {})})
                store.put("jobs", {"id": "prepare", "project_id": "video", "kind": "prepare"})
                source = self.root / "downloads/web/video/source.mkv"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.touch()
                with patch("game_vod_clipper.web_worker.youtube_command", return_value=["yt-dlp"]), \
                        patch("game_vod_clipper.web_worker.command", return_value=SOURCE_PREFIX + str(source) + "\n") as command, \
                        patch("game_vod_clipper.web_worker.probe", return_value={"duration": 16, "width": 2560, "height": 1440}):
                    run(self.root, "prepare")
                args = command.call_args_list[0].args[0]
                self.assertEqual(args[args.index("-f") + 1], quality_format(quality or "best"))
                self.assertEqual(args[args.index("-S") + 1], "res,fps")
                self.assertEqual(args[args.index("--merge-output-format") + 1], "mkv")
                self.assertEqual(store.get("projects", "video")["height"], 1440)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "trusted FFmpeg is required")
    def test_export_keeps_1440p_source_even_with_a_720p_preview(self):
        source = self.root / "downloads/source.mp4"
        source.parent.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=2560x1440:r=2",
                        "-t", "12", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast", str(source)], check=True)
        work = self.root / "runs/web/video"
        work.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", "scale=1280:720", "-c:v", "libx264",
                        "-threads", "2", "-preset", "ultrafast", str(work / "preview.mp4")], check=True)
        store = Store(self.root)
        store.put("projects", {"id": "video", "source": "downloads/source.mp4", "height": 1440, "width": 2560})
        store.put("jobs", {"id": "clip", "project_id": "video", "kind": "export",
                           "draft": {"start": 1, "victory": 3, "postroll": 5, "reviewed": False}})
        run(self.root, "clip")
        output = self.root / store.get("jobs", "clip")["output"]
        metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)]))
        stream = metadata["streams"][0]
        self.assertEqual((stream["width"], stream["height"]), (2560, 1440))
        self.assertEqual(stream["r_frame_rate"], "2/1")
