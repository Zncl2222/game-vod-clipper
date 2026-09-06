"""Offline adapter tests; the explicitly enabled live check uses synthetic images only."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

try:
    from fastapi.testclient import TestClient

    from game_vod_clipper.codex_analysis import (
        MODEL,
        AnalysisProgress,
        invoke_codex,
        packets,
        run_analysis,
        validate_observation,
    )
    from game_vod_clipper.web import create_app
    from game_vod_clipper.web_store import Store

    AVAILABLE = True
except ImportError:
    AVAILABLE = False


def observation(**changes):
    return {
        "status": "not_found",
        "start": None,
        "victory": None,
        "postroll": 8,
        "boss": "",
        "summary": "測試圖樣中沒有 Boss 戰。",
        "warnings": [],
        "evidence": [],
        "sample_requests": [],
    } | changes


@unittest.skipUnless(AVAILABLE, "Install web/test extras")
class CodexStreamingTest(unittest.TestCase):
    def test_analysis_passes_selected_model_to_shared_executor(self):
        with patch("game_vod_clipper.codex_analysis.execute",
                   return_value={"reply": "{}", "usage": {}}) as execute:
            invoke_codex(self.work, [], "metadata only", 10, model="picked", effort="low")
        self.assertEqual(execute.call_args.kwargs["model"], "picked")
        self.assertEqual(execute.call_args.kwargs["effort"], "low")
        self.assertIn("schema", execute.call_args.kwargs)

    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="codex-stream-test-", dir=runs)
        self.work = Path(self.temp.name)
        self.script = self.work / "fake_codex.py"
        self.script.write_text('''
import json, pathlib, sys, time
mode, result = sys.argv[1], pathlib.Path(sys.argv[2])
print('{"type":"thread.started"}', flush=True)
sys.stderr.write("diagnostic " * 20000)
sys.stderr.flush()
if mode == "timeout":
    time.sleep(10)
    sys.exit(1)
if mode == "failed":
    print('{"type":"turn.failed","error":{"message":"fixture failure"}}', flush=True)
    sys.exit(2)
deadline = time.monotonic() + 4
while not (result.parent / "continue").exists():
    if time.monotonic() > deadline:
        sys.exit(3)
    time.sleep(0.02)
print('not json')
print('[]')
sys.stdout.write('{"type":"item.')
sys.stdout.flush()
time.sleep(0.25)
print('completed","item":{"type":"reasoning","text":"private reasoning"}}', flush=True)
result.write_text('{"status":"not_found"}')
sys.stdout.write('{"type":"turn.completed","usage":{"input_tokens":12}}')
sys.stdout.flush()
''', encoding="utf-8")
        self.processes = []

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, mode, callback, timeout=5):
        real_popen = subprocess.Popen

        def fake_popen(args, **kwargs):
            process = real_popen(
                [sys.executable, "-u", str(self.script), mode, args[args.index("-o") + 1]],
                **kwargs,
            )
            self.processes.append(process)
            return process

        with patch("game_vod_clipper.codex_runtime.shutil.which", return_value=sys.executable), patch(
            "game_vod_clipper.codex_runtime.subprocess.Popen", side_effect=fake_popen
        ):
            return invoke_codex(self.work, [], "fixture prompt" * 20000, timeout, on_event=callback)

    def test_events_arrive_before_exit_and_partial_lines_are_preserved(self):
        received = []

        def update(event):
            received.append(event)
            if event["type"] == "thread.started":
                self.assertIsNone(self.processes[0].poll())
                (self.work / "continue").touch()

        result, usage = self.invoke("success", update)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(usage, {"input_tokens": 12})
        self.assertEqual([e["type"] for e in received], ["thread.started", "item.completed", "turn.completed"])
        self.assertIn("item.completed", (self.work / "events.jsonl").read_text())
        self.assertGreater((self.work / "diagnostics.log").stat().st_size, 100000)

    def test_timeout_kills_process_and_preserves_partial_logs(self):
        with self.assertRaisesRegex(RuntimeError, "已停止"):
            self.invoke("timeout", lambda event: None, timeout=0.4)
        self.assertIsNotNone(self.processes[0].poll())
        self.assertIn("thread.started", (self.work / "events.jsonl").read_text())

    def test_failure_is_not_reported_as_a_result(self):
        (self.work / "response.json").write_text('{"stale":true}')
        with self.assertRaisesRegex(RuntimeError, "呼叫失敗"):
            self.invoke("failed", lambda event: None)
        self.assertFalse((self.work / "response.json").exists())

    def test_heartbeat_is_distinct_from_activity_and_stops_on_exit(self):
        store = Store(self.work)
        store.put("jobs", {"id": "analysis"})
        with patch("game_vod_clipper.codex_analysis.HEARTBEAT_INTERVAL", 0.02):
            with AnalysisProgress(store, "analysis") as progress:
                progress.codex_event({"type": "item.completed", "item": {"type": "reasoning", "text": "private reasoning"}})
                initial = store.get("jobs", "analysis")
                deadline = time.monotonic() + 2
                while store.get("jobs", "analysis")["heartbeat_at"] <= initial["heartbeat_at"]:
                    self.assertLess(time.monotonic(), deadline)
                    threading.Event().wait(0.01)
                current = store.get("jobs", "analysis")
                self.assertEqual(current["last_activity_at"], initial["last_activity_at"])
                self.assertNotIn("private reasoning", json.dumps(current))
                for index in range(20):
                    progress.report("extracting", f"packet {index}")
                self.assertEqual(len(store.get("jobs", "analysis")["activity"]), 12)
            self.assertFalse(progress.thread.is_alive())


@unittest.skipUnless(
    AVAILABLE and shutil.which("ffmpeg"), "Install web/test extras and FFmpeg"
)
class CodexAnalysisTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="codex-test-", dir=runs)
        self.root = Path(self.temp.name)
        (self.root / "downloads").mkdir()
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30",
                "-t",
                "16",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                str(self.root / "downloads" / "test.mp4"),
            ],
            check=True,
            capture_output=True,
        )
        self.store = Store(self.root)
        self.project = {
            "id": "synthetic",
            "source": "downloads/test.mp4",
            "duration": 16,
            "ready": True,
            "thumbnails": [],
            "draft": {
                "start": 1,
                "victory": 8,
                "postroll": 5,
                "revision": 0,
                "reviewed": True,
                "origin": "manual",
            },
        }
        self.job = {
            "id": "analysis",
            "project_id": "synthetic",
            "kind": "analyze",
            "status": "running",
            "analysis": {"start": 0, "end": 16},
        }
        self.store.put("projects", self.project)
        self.store.put("jobs", self.job)

    def tearDown(self):
        self.temp.cleanup()

    def test_observation_boundaries_and_sample_budget(self):
        for values in (
            {"start": -1, "victory": 8},
            {"start": 9, "victory": 8},
            {"start": 1, "victory": 15},
            {"start": float("nan"), "victory": 8},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_observation(
                    observation(status="candidate", **values), 0, 16, 16
                )
        with self.assertRaises(ValueError):
            packets(0, 100, 0.00001)
        with self.assertRaises(ValueError):
            packets(0, 100, float("inf"))
        self.assertEqual(len(packets(0, 1800, 30)), 2)

    def test_offline_analysis_preserves_existing_draft(self):
        with patch(
            "game_vod_clipper.codex_analysis.invoke_codex",
            return_value=(observation(), {"input_tokens": 10}),
        ) as invoke:
            run_analysis(self.store, self.job, self.project)
        result = self.store.get("jobs", "analysis")["result"]
        self.assertEqual(result["model"], MODEL)
        self.assertFalse(result["reviewed"])
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(
            self.store.get("projects", "synthetic")["draft"], self.project["draft"]
        )
        self.assertTrue(all(path.is_file() for path in invoke.call_args.args[1]))

    def test_reject_unobserved_evidence_and_out_of_range_refinement(self):
        with (
            patch(
                "game_vod_clipper.codex_analysis.invoke_codex",
                return_value=(
                    observation(evidence=[{"time": 0.5, "event": "victory"}]),
                    {},
                ),
            ),
            self.assertRaises(ValueError),
        ):
            run_analysis(self.store, self.job, self.project)
        with patch(
            "game_vod_clipper.codex_analysis.invoke_codex",
            return_value=(
                observation(sample_requests=[{"start": 50, "end": 60, "every": 1}]),
                {},
            ),
        ):
            run_analysis(self.store, self.job, self.project)
        self.assertEqual(
            self.store.get("jobs", "analysis")["result"]["status"], "uncertain"
        )

    def test_api_validates_range_and_queues_exact_model_job(self):
        # A mocked connection and queue avoid paid model calls.
        app = create_app(self.root)
        app.state.codex.status = AsyncMock(return_value={"available": True})
        app.state.codex.models = AsyncMock(return_value=[{
            "id": MODEL, "effort": "medium", "input_modalities": ["text", "image"]
        }])
        with (
            TestClient(app) as client,
            patch(
                "game_vod_clipper.web.Jobs.submit", return_value={"id": "queued"}
            ) as submit,
        ):
            for bounds in (
                {"start": 3, "end": 2},
                {"start": 0, "end": 17},
                {"start": "NaN", "end": 10},
            ):
                self.assertEqual(
                    client.post(
                        "/api/projects/synthetic/analyze", json=bounds
                    ).status_code,
                    422,
                )
            self.assertEqual(
                client.post(
                    "/api/projects/synthetic/analyze", json={"start": 0, "end": 16}
                ).status_code,
                202,
            )
            submit.assert_called_once_with(
                "synthetic", "analyze", analysis={"start": 0.0, "end": 16.0,
                    "model": MODEL, "effort": "medium", "request_id": ANY}
            )

    @unittest.skipUnless(
        os.environ.get("GAME_VOD_LIVE_CODEX_TEST") == "1", "Opt-in live Codex check"
    )
    def test_live_codex_with_synthetic_images(self):
        run_analysis(self.store, self.job, self.project)
        result = self.store.get("jobs", "analysis")["result"]
        self.assertEqual(result["model"], "gpt-5.6-luna")
        self.assertIn(result["status"], {"not_found", "uncertain"})
        print("LIVE_CODEX_RESULT", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
