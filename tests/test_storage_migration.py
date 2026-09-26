"""Safety checks for the one-time offline storage relocation tool."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "migration", Path(__file__).resolve().parents[1] / "scripts/migrate_storage_once.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.target = Path(self.temp.name) / "E/BossCut"
        self.target.mkdir(parents=True)
        for folder in ("downloads/web/p", "clips", "runs/web/p/codex/j",
                       "runs/web/youtube", "runs/web/profiles", "runs/browser-deps-test"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.source = self.root / "downloads/web/p/source.webm"
        self.source.write_bytes(b"original-media-content")
        self.checkpoint = self.root / "runs/web/p/codex/j/checkpoint.json"
        self.checkpoint.write_text(json.dumps({"identity": {
            "source": "downloads/web/p/source.webm", "size": self.source.stat().st_size,
            "mtime": self.source.stat().st_mtime_ns}, "results": [{"path": "runs/web/p/frame.jpg"}]}))
        (self.root / "runs/web/p/frame.jpg").write_bytes(b"thumbnail")
        self.protected = [self.root / name for name in (
            "runs/web/locations.json", "runs/web/youtube/account.json",
            "runs/web/profiles/profile.json", "runs/browser-deps-test/runtime")]
        for file in self.protected:
            file.write_text("keep-me")
        self.output = self.target / "clips/new-export.mp4"
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"new-export")
        self.output.with_suffix(".json").write_text(json.dumps({
            "source": str(self.source), "output": str(self.output)}))
        self.db_path = self.root / "runs/web/state.sqlite3"
        self.history = '{"id":"yt-video", "title":"downloads/web/p/source.webm"}'
        with sqlite3.connect(self.db_path) as db:
            for table in ("projects", "jobs", "retained_media", "youtube_history"):
                db.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY, data TEXT)")
            db.execute("INSERT INTO projects VALUES (?, ?)", ("p", json.dumps({
                "id": "p", "source": "downloads/web/p/source.webm", "title": "runs/web/p"})))
            db.execute("INSERT INTO jobs VALUES (?, ?)", ("j", json.dumps({
                "id": "j", "kind": "export", "output": str(self.output)})))
            db.execute("INSERT INTO retained_media VALUES (?, ?)", ("old", json.dumps({
                "path": str(self.source)})))
            db.execute("INSERT INTO youtube_history VALUES (?, ?)", ("yt-video", self.history))

    def planned(self):
        manifest = migration.plan(self.root, self.target)
        return manifest, json.loads(manifest.read_text())

    def test_full_relocation_preserves_history_and_protected_files(self):
        manifest, data = self.planned()
        migration.copy_files(manifest, data)
        self.assertTrue(self.source.exists())
        self.assertEqual(len(data["files"]), 3)
        for entry in data["files"]:
            self.assertEqual(migration.digest(Path(entry["destination"])), entry["sha256"])
        migration.switch_paths(manifest, data)
        self.assertTrue(self.source.exists())
        with sqlite3.connect(self.db_path) as db:
            project = json.loads(db.execute("SELECT data FROM projects").fetchone()[0])
            self.assertEqual(db.execute("SELECT data FROM youtube_history").fetchone()[0], self.history)
        self.assertEqual(project["source"], str(self.target / "downloads/web/p/source.webm"))
        self.assertEqual(project["work"], str(self.target / "runs/web/p"))
        self.assertEqual(project["title"], "runs/web/p")
        checkpoint = json.loads((self.target / self.checkpoint.relative_to(self.root)).read_text())
        self.assertEqual(checkpoint["identity"]["source"], project["source"])
        self.assertEqual(checkpoint["identity"]["mtime"], Path(project["source"]).stat().st_mtime_ns)
        receipt = json.loads(self.output.with_suffix(".json").read_text())
        self.assertEqual(receipt["source"], project["source"])
        migration.cleanup(manifest, data)
        self.assertFalse(self.source.exists())
        self.assertEqual(Path(project["source"]).read_bytes(), b"original-media-content")
        for file in self.protected:
            self.assertEqual(file.read_text(), "keep-me")
        self.assertTrue((manifest.parent / "state-before.sqlite3").exists())
        self.assertEqual(data["phase"], "complete")

    def test_collision_and_link_refused(self):
        dest = self.target / "downloads/web/p/source.webm"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"do-not-overwrite")
        with self.assertRaisesRegex(ValueError, "collision"):
            self.planned()
        self.assertEqual(dest.read_bytes(), b"do-not-overwrite")
        dest.unlink()
        (self.root / "downloads/link").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.planned()

    def test_changed_source_blocks_copy(self):
        manifest, data = self.planned()
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            migration.copy_files(manifest, data)
        self.assertTrue(self.source.exists())

    def test_windows_case_collision_is_refused(self):
        (self.root / "downloads/Video.webm").write_bytes(b"A")
        (self.root / "downloads/video.webm").write_bytes(b"B")
        with self.assertRaisesRegex(ValueError, "collision"):
            self.planned()

    def test_changed_copy_blocks_reference_switch(self):
        manifest, data = self.planned()
        migration.copy_files(manifest, data)
        Path(data["files"][0]["destination"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "changed"):
            migration.switch_paths(manifest, data)
        with sqlite3.connect(self.db_path) as db:
            project = json.loads(db.execute("SELECT data FROM projects").fetchone()[0])
        self.assertEqual(project["source"], "downloads/web/p/source.webm")

    def test_cleanup_rejected_before_switch(self):
        manifest, data = self.planned()
        migration.copy_files(manifest, data)
        with self.assertRaisesRegex(ValueError, "Switch paths"):
            migration.cleanup(manifest, data)
        self.assertTrue(all(Path(entry["source"]).exists() for entry in data["files"]))

    def test_changed_destination_blocks_cleanup_without_deleting_originals(self):
        manifest, data = self.planned()
        migration.copy_files(manifest, data)
        migration.switch_paths(manifest, data)
        Path(data["files"][-1]["destination"]).write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "changed"):
            migration.cleanup(manifest, data)
        self.assertTrue(all(Path(entry["source"]).exists() for entry in data["files"]))

    def test_cleanup_recovers_after_unlink_before_journal(self):
        manifest, data = self.planned()
        migration.copy_files(manifest, data)
        migration.switch_paths(manifest, data)
        Path(data["files"][0]["source"]).unlink()
        migration.cleanup(manifest, data)
        self.assertEqual(data["phase"], "complete")


if __name__ == "__main__":
    unittest.main()
