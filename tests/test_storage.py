"""Storage totals count files on disk, independent of project records or list limits."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.storage import video_storage
from game_vod_clipper.web import create_app


class StorageTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="storage-test-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()

    def file(self, name, size):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def test_totals_include_unimported_sources_exports_previews_and_partial_downloads(self):
        self.file("downloads/source.MP4", 1024)
        self.file("clips/web/project/clip.mp4", 200)
        self.file("runs/web/project/preview.mp4", 300)
        self.file("downloads/pending.webm.part", 76)
        self.file("runs/web/project/thumb.jpg", 500)
        with TestClient(create_app(self.root)) as client:
            value = client.get("/api/storage").json()
            self.assertEqual(value["bytes"], 1600)
            self.assertEqual(value["files"], 4)
            self.assertEqual(value["categories"]["sources"], {"bytes": 1100, "files": 2})
            self.assertEqual(value["categories"]["exports"]["bytes"], 200)
            self.assertEqual(value["categories"]["previews"]["bytes"], 300)
            self.assertFalse(value["incomplete"])
            (self.root / "clips/web/project/clip.mp4").unlink()
            self.assertEqual(client.get("/api/storage").json()["bytes"], 1400)

    def test_no_200_file_limit_and_hard_links_are_only_counted_once(self):
        for index in range(205):
            self.file(f"downloads/{index}.mp4", 1)
        os.link(self.root / "downloads/0.mp4", self.root / "downloads/alias.mp4")
        (self.root / "downloads/link.mp4").symlink_to("0.mp4")
        self.assertEqual(video_storage(self.root)["bytes"], 205)
        self.assertEqual(video_storage(self.root)["files"], 205)

    def test_external_files_and_linked_folders_are_not_scanned(self):
        outside = Path(self.temp.name) / "private.mp4"
        outside.write_bytes(b"external")
        (self.root / "downloads").mkdir()
        (self.root / "downloads/outside.mp4").symlink_to(outside)
        (self.root / "downloads/loop").symlink_to(self.root, target_is_directory=True)
        self.assertEqual(video_storage(self.root)["bytes"], 0)
        self.assertFalse(video_storage(self.root)["incomplete"])

    def test_empty_and_unreadable_workspaces_are_distinguishable(self):
        self.assertEqual(video_storage(self.root)["files"], 0)
        self.assertFalse(video_storage(self.root)["incomplete"])
        self.file("downloads/video.mp4", 10)
        original_stat = Path.stat

        def denied(path, *args, **kwargs):
            if path.name == "video.mp4":
                raise PermissionError("unreadable")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", denied):
            self.assertTrue(video_storage(self.root)["incomplete"])
