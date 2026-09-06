"""Offline regressions for YouTube runtime setup in both download entry points."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_vod_clipper.media import download_video
from game_vod_clipper.process import CommandResult, ToolMissingError, resolve_tool_command
from game_vod_clipper.web_store import Store
from game_vod_clipper.web_worker import run
from game_vod_clipper.youtube import javascript_runtime, youtube_command


class YouTubeTest(unittest.TestCase):
    def test_runtime_selection(self):
        cases = [
            ({"node": "v22.23.2"}, "node:/tools/node"),
            ({"deno": "deno 2.3.0\nv8 13.5.212.4", "node": "v22.0.0"}, "deno:/tools/deno"),
            ({"deno": "deno 2.2.0", "node": "v22.0.0"}, "node:/tools/node"),
            ({"node": "v20.19.0"}, None),
            ({"deno": "unknown version"}, None),
            ({}, None),
        ]
        for versions, expected in cases:
            with self.subTest(versions=versions), patch(
                "game_vod_clipper.youtube.shutil.which",
                side_effect=lambda name: f"/tools/{name}" if name in versions else None,
            ), patch(
                "game_vod_clipper.youtube.subprocess.run",
                side_effect=lambda args, **kw: subprocess.CompletedProcess(
                    args, 0, versions[Path(args[0]).name], ""
                ),
            ):
                if expected:
                    self.assertEqual(javascript_runtime(), expected)
                else:
                    with self.assertRaisesRegex(ToolMissingError, "Node.js >= 22"):
                        javascript_runtime()

    def test_broken_deno_falls_back_to_node(self):
        for failure in (
            OSError("cannot execute"),
            subprocess.TimeoutExpired(["deno", "--version"], 5),
            subprocess.CompletedProcess([], 1, "deno 2.3.0", "failed"),
        ):
            with self.subTest(failure=failure), patch(
                "game_vod_clipper.youtube.shutil.which", side_effect=lambda name: f"/tools/{name}"
            ), patch(
                "game_vod_clipper.youtube.subprocess.run",
                side_effect=[failure, subprocess.CompletedProcess([], 0, "v22.0.0", "")],
            ):
                self.assertEqual(javascript_runtime(), "node:/tools/node")

    def test_project_ytdlp_takes_precedence_over_global_executable(self):
        with patch("game_vod_clipper.process.importlib.util.find_spec", return_value=object()), patch(
            "game_vod_clipper.process.shutil.which", return_value="/global/yt-dlp"
        ):
            self.assertEqual(resolve_tool_command("yt-dlp"), [sys.executable, "-m", "yt_dlp"])

    def test_standalone_ytdlp_fallback(self):
        with patch("game_vod_clipper.process.importlib.util.find_spec", return_value=None), patch(
            "game_vod_clipper.process.shutil.which", return_value="/global/yt-dlp"
        ):
            self.assertEqual(resolve_tool_command("yt-dlp"), ["/global/yt-dlp"])

    def assert_runtime_enabled(self, args):
        self.assertIn("--no-js-runtimes", args)
        self.assertEqual(args[args.index("--js-runtimes") + 1], "node:/tools/node")

    @patch("game_vod_clipper.youtube.javascript_runtime", return_value="node:/tools/node")
    def test_cli_download_enables_runtime(self, runtime):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs) as directory:
            output = Path(directory) / "source.mp4"
            output.touch()
            with patch("game_vod_clipper.media.run_command", return_value=CommandResult(
                [], 0, str(output) + "\n", ""
            )) as command:
                self.assertEqual(download_video("https://youtu.be/abcdefghijk", Path(directory)), output)
            self.assert_runtime_enabled(command.call_args.args[0])

    @patch("game_vod_clipper.youtube.javascript_runtime", return_value="node:/tools/node")
    def test_web_download_enables_runtime_despite_ignore_config(self, runtime):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs) as directory:
            root = Path(directory)
            store = Store(root)
            store.put("projects", {"id": "video", "url": "https://youtu.be/abcdefghijk"})
            store.put("jobs", {"id": "prepare", "project_id": "video", "kind": "prepare"})
            source = root / "downloads" / "web" / "video" / "source.mp4"
            source.parent.mkdir(parents=True)
            source.touch()
            with patch("game_vod_clipper.web_worker.command", return_value=str(source) + "\n") as command, patch(
                "game_vod_clipper.web_worker.probe", return_value={"duration": 16, "width": 320, "height": 180}
            ):
                run(root, "prepare")
            args = command.call_args_list[0].args[0]
            self.assert_runtime_enabled(args)
            self.assertIn("--ignore-config", args)
            self.assertIn("duration <= 21600 & !is_live", args)
            self.assertTrue(store.get("projects", "video")["ready"])

    def test_actual_installed_ytdlp_recognizes_runtime_and_ejs(self):
        try:
            args = youtube_command()
        except ToolMissingError as exc:
            self.skipTest(str(exc))
        result = subprocess.run(
            args + ["--ignore-config", "--verbose"], capture_output=True,
            text=True, timeout=15, check=False,
        )
        # No URL: inspect startup diagnostics without contacting YouTube.
        self.assertIn("yt_dlp_ejs-", result.stderr)
        self.assertRegex(result.stderr, r"JS runtimes:.*(?:node|deno)-")
        self.assertNotIn("No supported JavaScript runtime", result.stderr)


if __name__ == "__main__":
    unittest.main()
