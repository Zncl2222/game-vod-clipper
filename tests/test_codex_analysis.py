"""Offline adapter tests; the explicitly enabled live check uses synthetic images only."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    from game_vod_clipper.codex_analysis import (
        MODEL,
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
            packets(0, 100, 0.01)
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
        # A mocked queue keeps the regular test suite free of paid model calls.
        with (
            TestClient(create_app(self.root)) as client,
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
                "synthetic", "analyze", analysis={"start": 0.0, "end": 16.0}
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
