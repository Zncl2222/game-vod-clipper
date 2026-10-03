"""Actual FFmpeg pagination: every frame, including the last partial page, is visible."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from game_vod_clipper.cli import main
from game_vod_clipper.media.operations import create_contact_sheet


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class ContactSheetTest(unittest.TestCase):
    def setUp(self):
        Path("runs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir="runs", prefix="test-sheets-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.frames = self.root / "frames"
        self.frames.mkdir()

    def make_frames(self, count):
        for index in range(count):
            Image.new("RGB", (64, 64), (index * 9, 40, 90)).save(self.frames / f"frame_{index:04d}.jpg")

    def test_all_frames_and_partial_last_page_are_in_manifest_and_images(self):
        self.make_frames(25)
        pages = create_contact_sheet(self.frames, self.root / "overview.jpg", width=64)
        manifest = json.loads((self.root / "overview.json").read_text())
        self.assertEqual(len(pages), 2)
        self.assertEqual(manifest["frame_count"], 25)
        self.assertEqual(manifest["page_count"], 2)
        self.assertEqual([len(p["frames"]) for p in manifest["pages"]], [20, 5])
        self.assertEqual([Path(f) for p in manifest["pages"] for f in p["frames"]],
                         sorted(self.frames.glob("*.jpg")))
        for index in range(25):
            page, cell = divmod(index, 20)
            with Image.open(pages[page]) as image:
                pixel = image.getpixel(((cell % 5) * 64 + 32, (cell // 5) * 64 + 32))
                self.assertLess(abs(pixel[0] - index * 9), 8)

    def test_single_page_keeps_requested_path_and_cli_lists_manifest(self):
        self.make_frames(2)
        stdout = io.StringIO()
        output = self.root / "overview.jpg"
        with contextlib.redirect_stdout(stdout):
            result = main(["sheet", str(self.frames), "-o", str(output)])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue().splitlines(), [str(output), str(output.with_suffix(".json"))])
        self.assertTrue(output.is_file())
