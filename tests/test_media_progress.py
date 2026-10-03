"""Offline progress parsing, streaming, timeout, and independent worker queues."""

import asyncio
import functools
import http.server
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from game_vod_clipper.media.progress import DOWNLOAD_PREFIX, DOWNLOAD_TEMPLATE, MediaProgress, streamed_command
from game_vod_clipper.jobs.scheduler import Jobs
from game_vod_clipper.storage.store import Store

ROOT = Path(__file__).resolve().parents[1]


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="progress-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.updates = []
        self.reporter = MediaProgress(lambda *args: self.updates.append(args))

    def event(self, data, **info):
        self.reporter.download(DOWNLOAD_PREFIX + json.dumps(data) + "\t" + json.dumps(info))
        return self.updates[-1][2]

    def test_download_tracks_bytes_estimates_and_separate_audio_without_inventing_totals(self):
        detail = self.event({"downloaded_bytes": 500, "total_bytes": 1000, "speed": 100, "eta": 5}, vcodec="vp9")
        self.assertEqual((detail["percent"], detail["speed_bps"], detail["eta_seconds"], detail["stream"]), (50, 100, 5, "video"))
        detail = self.event({"downloaded_bytes": 250, "total_bytes_estimate": 500}, vcodec="none", acodec="opus")
        self.assertEqual(detail["stream"], "audio")
        self.assertTrue(detail["total_is_estimate"])
        detail = self.event({"downloaded_bytes": 100, "speed": float("nan"), "eta": -1})
        self.assertIsNone(detail["percent"])
        self.assertIsNone(detail["total_bytes"])
        self.assertIsNone(detail["speed_bps"])
        self.assertIsNone(detail["eta_seconds"])
        self.assertEqual(self.event({"status": "finished", "downloaded_bytes": 100})["percent"], 100)
        count = len(self.updates)
        self.assertTrue(self.reporter.download(DOWNLOAD_PREFIX + "broken\t{}"))
        self.assertEqual(len(self.updates), count)

    def test_ffmpeg_percent_is_based_on_processed_source_duration(self):
        receive = self.reporter.ffmpeg("製作預覽", "preview", 120)
        receive("out_time_us=30000000")
        receive("progress=continue")
        self.assertEqual(self.updates[-1][1], 25)
        receive("out_time_us=N/A")
        receive("progress=continue")
        self.assertEqual(len(self.updates), 1)
        receive("out_time_us=120000000")
        receive("progress=end")
        self.assertEqual(self.updates[-1][1], 100)

    def test_ffmpeg_reports_processed_time_speed_and_eta_for_exports(self):
        receive = self.reporter.ffmpeg("重新編碼剪輯", "export", 60)
        receive("out_time_us=15000000")
        receive("speed=2.5x")
        receive("progress=continue")
        detail = self.updates[-1][2]
        self.assertEqual((detail["phase"], detail["processed_seconds"], detail["total_seconds"]), ("export", 15, 60))
        self.assertEqual((detail["speed_ratio"], detail["eta_seconds"]), (2.5, 18))
        receive("speed=N/A")
        receive("progress=continue")
        self.assertIsNone(self.updates[-1][2]["eta_seconds"])
        receive("progress=end")
        self.assertEqual((self.updates[-1][1], self.updates[-1][2]["eta_seconds"]), (100, None))

    def test_output_reaches_callback_before_exit_and_timeout_and_errors_are_bounded(self):
        acknowledged = self.root / "ack"
        script = ("import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); print('progress',flush=True); "
                  "[(time.sleep(.05)) for _ in range(20) if not p.exists()]; "
                  "print('finished',flush=True); sys.exit(0 if p.exists() else 4)")
        def receive(line):
            if line == "progress":
                acknowledged.touch()
                return True
            return False
        result = streamed_command([sys.executable, "-c", script, str(acknowledged)], receive, timeout=3)
        self.assertEqual(result.strip(), "finished")
        with self.assertRaises(TimeoutError):
            streamed_command([sys.executable, "-c", "import time; time.sleep(30)"], receive, timeout=.1)
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            streamed_command([sys.executable, "-c", "import sys; print('fixture failure',file=sys.stderr); sys.exit(2)"], receive)

    def test_real_ytdlp_emits_structured_progress_for_local_fixture(self):
        source = self.root / "fixture.mp4"
        source.write_bytes(b"fixture" * 100_000)
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(self.root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            output = streamed_command([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                "--newline", "--progress", "--progress-template", DOWNLOAD_TEMPLATE,
                "--print", "after_move:filepath", "-o", str(self.root / "copy.mp4"),
                f"http://127.0.0.1:{server.server_port}/fixture.mp4"], self.reporter.download, timeout=15)
            self.assertIn(str(self.root / "copy.mp4"), output)
            self.assertGreater(len(self.updates), 1)
            self.assertEqual(self.updates[-1][2]["downloaded_bytes"], source.stat().st_size)
            self.assertEqual(self.updates[-1][1], 100)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class WorkerQueueTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "runs", prefix="worker-queue-")
        self.store = Store(Path(self.temp.name))
        self.manager = Jobs(self.store)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def test_analysis_does_not_block_serial_downloads_and_cancel_releases_next(self):
        entered = {key: asyncio.Event() for key in ("analyze", "first", "second")}
        async def run(job_id):
            job = self.store.get("jobs", job_id)
            self.store.patch("jobs", job_id, status="running")
            entered[job["project_id"]].set()
            await asyncio.Future()
        self.manager.run = run
        self.manager.submit("analyze", "analyze")
        await asyncio.wait_for(entered["analyze"].wait(), 1)
        first = self.manager.submit("first", "prepare")
        self.manager.submit("second", "prepare")
        await asyncio.wait_for(entered["first"].wait(), 1)
        self.assertFalse(entered["second"].is_set())
        task = self.manager.tasks[first["id"]]
        task.cancel()
        await task
        await asyncio.wait_for(entered["second"].wait(), 1)
        self.assertEqual(self.store.get("jobs", first["id"])["status"], "cancelled")

    async def test_dispatch_failure_is_terminal_and_does_not_leave_a_ghost_queue_entry(self):
        connection = AsyncMock()
        connection.rate_limits.side_effect = RuntimeError("fixture quota read failed")
        self.manager.codex = connection
        job = self.manager.submit("project", "analyze")
        await self.manager.tasks[job["id"]]
        self.assertEqual(self.store.get("jobs", job["id"])["status"], "failed")
        self.assertIn("fixture quota read failed", self.store.get("jobs", job["id"])["error"])


if __name__ == "__main__":
    unittest.main()
