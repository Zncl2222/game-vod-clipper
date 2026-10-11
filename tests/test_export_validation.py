"""Encoded-file failures must not become downloadable completed exports."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_vod_clipper.media.progress import MediaProgress
from game_vod_clipper.media.validation import validate_export
from game_vod_clipper.storage.store import Store
from game_vod_clipper.web_worker import command, run


class DecodeOutputTests(unittest.TestCase):
    def validate(self, *, error=False, on_progress=None):
        metadata = {"format": {"duration": "10"}, "streams": [
            {"codec_type": "video", "start_time": "0", "duration": "10"},
            {"codec_type": "audio", "start_time": "0", "duration": "10"},
        ]}

        def fixture_command(args, **kwargs):
            if args[0] == "ffprobe":
                return json.dumps(metadata)
            # Exercise real pipe handling with an error-producing process that exits 0.
            script = "import sys\n"
            if error:
                script += "print('[h264 @ fixture] Error splitting the input into NAL units.', file=sys.stderr)\n"
            if "-progress" in args:
                script += "print('out_time_us=10000000')\nprint('progress=end')\n"
            return command([sys.executable, "-c", script], **kwargs)

        with patch("game_vod_clipper.media.validation.resolve_tool_command", side_effect=lambda name: [name]):
            return validate_export(Path("fixture.mp4"), 10, has_audio=True, command=fixture_command,
                                   on_progress=on_progress)

    def test_decode_error_rejects_zero_exit_code_without_progress(self):
        with self.assertRaisesRegex(RuntimeError, "Error splitting"):
            self.validate(error=True)

    def test_decode_error_rejects_zero_exit_code_with_progress(self):
        progress = MediaProgress(lambda *args: None).ffmpeg("驗證", "verify", 10)
        with self.assertRaisesRegex(RuntimeError, "Error splitting"):
            self.validate(error=True, on_progress=progress)

    def test_progress_records_allow_valid_export_and_update_progress(self):
        updates = []
        progress = MediaProgress(lambda *args: updates.append(args)).ffmpeg("驗證", "verify", 10)
        result = self.validate(on_progress=progress)
        self.assertTrue(result["full_decode_checked"])
        self.assertEqual(updates[-1][1], 100)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires media tools")
class ExportValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30",
                        "-f", "lavfi", "-i", "sine=sample_rate=48000", "-t", "10", "-c:v", "libx264",
                        "-threads", "1", "-preset", "ultrafast", "-c:a", "aac", "-movflags", "+faststart",
                        str(self.source)], check=True, capture_output=True)

    def corrupt(self, target):
        data = bytearray(self.source.read_bytes())
        data[-3000:] = bytes(3000)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_valid_export_decodes_both_tracks(self):
        result = validate_export(self.source, 10, has_audio=True, command=command)
        self.assertTrue(result["audio"])
        self.assertTrue(result["full_decode_checked"])

    def test_audio_track_cannot_disappear(self):
        silent = self.root / "silent.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.source), "-map", "0:v:0", "-c", "copy", str(silent)],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, "音訊"):
            validate_export(silent, 10, has_audio=True, command=command)

    def test_corrupt_late_packets_are_not_promoted_to_final_mp4(self):
        store = Store(self.root)
        store.put("projects", {"id": "p", "source": str(self.source), "duration": 10, "audio_codec": "aac"})
        store.put("jobs", {"id": "j", "project_id": "p", "kind": "export", "status": "running",
                           "draft": {"start": 0, "victory": 2, "postroll": 8, "reviewed": False}})
        final = self.root / "clips/web/p/j.mp4"
        with patch("game_vod_clipper.web_worker.clip_video", side_effect=lambda source, output, **kwargs: self.corrupt(output)):
            with self.assertRaises(RuntimeError):
                run(self.root, "j")
        self.assertTrue(final.with_suffix(".partial.mp4").exists())
        self.assertFalse(final.exists())
        self.assertFalse(final.with_suffix(".json").exists())
        self.assertNotIn("output", store.get("jobs", "j"))
