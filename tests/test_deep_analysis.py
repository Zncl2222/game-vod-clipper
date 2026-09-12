"""Adaptive inspection contracts with deterministic observations; no paid AI calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_vod_clipper.codex_analysis import missing_ranges, packets, run_analysis, validate_observation
from game_vod_clipper.web_store import Store


def answer(**changes):
    return {"status": "candidate", "start": 4, "victory": 12, "postroll": 5,
            "boss": "Fixture", "summary": "Synthetic observation", "warnings": [],
            "evidence": [], "sample_requests": [], "suspicious_windows": [], **changes}


def segment(key="fight-1", **changes):
    return {"id": key, "start": 3, "end": 10, "victory": None, "kind": "fight",
            "confidence": "low", "boss": "測試", "summary": "需核對", "warnings": [],
            "evidence": [], **changes}


class DeepAnalysisTest(unittest.TestCase):
    def test_unproductive_new_windows_finish_without_a_round_cap(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                summary=f"Ordinary combat, reworded {at}", candidates=[segment()],
                evidence=[{"time": self.requests[-1][0], "event": f"Combat {at}"}],
                sample_requests=[{"start": at, "end": at + .2, "every": .1}]), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["completion_reason"], "evidence_exhausted")
        self.assertTrue(result["review_complete"])
        self.assertTrue(result["checks"]["search"])
        self.assertFalse(result["can_continue"])
        self.assertFalse(self.store.get("jobs", "first")["resumable"])
        self.assertEqual(len(result["candidates"]), 1)

    def test_stalled_refinement_state_survives_resume(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                sample_requests=[{"start": at, "end": at + .2, "every": .1}]), {}
        first = self.run_review(observe, calls=3)
        self.assertTrue(first["can_continue"])
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        result = self.run_review(observe, calls=None, job=resumed)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(result["completion_reason"], "evidence_exhausted")

    def test_new_victory_resets_stall_and_completes_required_checks(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            if at >= 4:
                return answer(review_complete=True), {}
            return answer(status="uncertain", start=None, victory=None,
                sample_requests=[{"start": at, "end": at + .2, "every": .1}]), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["completion_reason"], "review_complete")

    def test_long_pass_finishes_all_packets_before_opening_another(self):
        self.project["duration"] = self.job["analysis"]["end"] = 400
        def observe(*args, **kwargs):
            # Repeatedly requests greater density while the first pass is pending.
            return answer(status="uncertain", start=None, victory=None,
                sample_requests=[{"start": 0, "end": 399, "every": .5 / len(self.requests)}]), {}
        result = self.run_review(observe, calls=None)
        self.assertGreater(result["rounds"], 4)
        self.assertFalse(list(missing_ranges(0, 399, .5,
            [{"packet": p} for p in result["coverage"]])))
        self.assertTrue(all(step >= .5 for _, _, step in self.requests))
        self.assertTrue(result["review_complete"])
        self.assertFalse(result["can_continue"])

    def test_large_suspicion_is_localized_without_claiming_a_win(self):
        result = self.run_review(lambda *a, **k: (answer(status="uncertain", start=None, victory=None,
            suspicious_windows=[{"start": 0, "end": 29, "every": .0001}]), {}), calls=None)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["rounds"], 2)
        self.assertTrue(all(step >= .5 for _, _, step in self.requests))
        self.assertFalse(result["can_continue"])

    def test_early_completion_does_not_skip_the_rest_of_the_vod(self):
        self.project["duration"] = self.job["analysis"]["end"] = 7200
        result = self.run_review(lambda *a, **k: (answer(status="not_found", start=None, victory=None,
            review_complete=True), {}), calls=None)
        self.assertTrue(result["checks"]["search"])
        self.assertGreater(max(b for _, b, _ in self.requests), 7100)

    def test_later_coarse_packets_keep_their_own_encounter_checks(self):
        self.project["duration"] = self.job["analysis"]["end"] = 7200
        def observe(*args, **kwargs):
            a, _, step = self.requests[-1]
            samples = [{"start": a + 10, "end": a + 10.2, "every": .1}] if step == 30 else []
            return answer(status="uncertain", start=None, victory=None, sample_requests=samples), {}
        result = self.run_review(observe, calls=None)
        self.assertTrue(result["checks"]["search"])
        self.assertTrue(any(a == 10 and step == .1 for a, _, step in self.requests))
        self.assertTrue(any(a == 3610 and step == .1 for a, _, step in self.requests))

    def test_timestamp_jitter_cannot_restart_completed_required_checks(self):
        def observe(*args, **kwargs):
            jitter = len(self.requests) * .000001
            return answer(start=4 - jitter, victory=12 + jitter), {}
        result = self.run_review(observe, calls=20)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["review_complete"])
        self.assertTrue(all(result["checks"].values()))
        self.assertLess(result["rounds"], 10)

    def test_analysis_runs_without_model_timeout_or_default_round_budget(self):
        from game_vod_clipper.codex_analysis import MAX_CALLS
        self.assertIsNone(MAX_CALLS)
        def observe(work, images, prompt, timeout, **kwargs):
            self.assertIsNone(timeout)
            return answer(), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["status"], "candidate")
        self.assertFalse(result["can_continue"])

    def test_uncertain_multiple_ranges_publish_before_completion_and_survive_resume(self):
        observations = [segment(), segment("win-2", start=15, end=25, victory=20, kind="possible_win")]
        first = self.run_review(lambda *a, **k: (answer(status="uncertain", start=None, victory=None,
            candidates=observations, sample_requests=[{"start": 3, "end": 10, "every": .5}]), {}), calls=1)
        published = self.store.get("jobs", "first")["candidates"]
        self.assertEqual(len(published), 2)
        self.assertEqual(first["status"], "uncertain")
        self.assertTrue(first["can_continue"])
        self.assertIsNone(published[0]["victory"])
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        result = self.run_review(lambda *a, **k: (answer(status="uncertain", start=None, victory=None,
            candidates=[segment(start=4, kind="death_retry")]), {}), job=resumed)
        self.assertEqual([c["id"] for c in result["candidates"]], [c["id"] for c in published])
        self.assertEqual(result["candidates"][0]["start"], 4)
        self.assertEqual(result["candidates"][0]["kind"], "death_retry")
        self.assertEqual(result["candidates"][1], published[1])

    def test_new_annotations_are_available_during_next_model_call_and_after_failure(self):
        def observe(*args, **kwargs):
            if len(self.requests) > 1:
                self.assertEqual(len(self.store.get("jobs", "first")["candidates"]), 2)
                raise RuntimeError("model disconnected")
            return answer(status="uncertain", candidates=[segment(), segment("second", start=14, end=20)]), {}
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            self.run_review(observe)
        self.assertEqual(len(self.store.get("jobs", "first")["candidates"]), 2)

    def test_empty_annotation_delta_does_not_add_another_primary_candidate(self):
        def observe(*args, **kwargs):
            candidates = [segment("one", start=4, end=19)] if len(self.requests) == 1 else []
            return answer(candidates=candidates, review_complete=True), {}
        result = self.run_review(observe)
        self.assertEqual(len(result["candidates"]), 1)

    def test_completed_uncertain_review_finishes_without_repeating_unresolved_window(self):
        result = self.run_review(lambda *a, **k: (answer(status="uncertain", start=None, victory=None,
            review_complete=True, suspicious_windows=[{"start": 9, "end": 9.25, "every": .0167}],
            sample_requests=[{"start": 0, "end": 29, "every": .001}]), {}))
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["can_continue"])
        self.assertEqual(result["rounds"], 2)
        self.assertTrue(result["checks"]["suspicious"])

    def test_resolved_suspicion_discards_obsolete_pending_safety_packets(self):
        def observe(*args, **kwargs):
            windows = [{"start": 9, "end": 15, "every": .0167}] if len(self.requests) == 1 else []
            return answer(status="uncertain", start=None, victory=None, suspicious_windows=windows), {}
        result = self.run_review(observe)
        self.assertEqual(result["rounds"], 2)
        self.assertFalse(result["can_continue"])

    def test_annotation_validation_and_grounding(self):
        for changes in ({"start": -1}, {"end": 31}, {"victory": 11}, {"start": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_observation(answer(candidates=[segment(**changes)]), 0, 30, 30)
        # Model aliases are untrusted; the host registry resolves collisions.
        self.assertEqual(len(validate_observation(answer(candidates=[segment(), segment()]), 0, 30, 30).candidates), 2)
        with self.assertRaisesRegex(ValueError, "實際抽樣"):
            self.run_review(lambda *a, **k: (answer(candidates=[segment(evidence=[{"time": .123, "event": "unseen"}])]), {}))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "downloads").mkdir()
        (self.root / "downloads/test.mp4").touch()
        self.store = Store(self.root)
        self.project = {"id": "p", "source": "downloads/test.mp4", "duration": 30}
        self.job = {"id": "first", "project_id": "p", "analysis": {"start": 0, "end": 30, "model": "chosen"}}
        self.store.put("jobs", self.job)
        self.requests = []

    def tearDown(self):
        self.temp.cleanup()

    def extract(self, source, work, request, **kwargs):
        self.requests.append(request)
        a, b, step = request
        times = [round(a + i * step, 4) for i in range(int((b-a) / step + 1e-6) + 1)]
        return [], {"start": a, "end": b, "every": step, "timestamps": times}

    def run_review(self, observation=None, calls=240, job=None):
        with patch("game_vod_clipper.codex_analysis.extract_packet", side_effect=self.extract), \
             patch("game_vod_clipper.codex_analysis.invoke_codex", side_effect=observation or (lambda *a, **k: (answer(), {}))), \
             patch("game_vod_clipper.codex_analysis.MAX_CALLS", calls):
            run_analysis(self.store, job or self.job, self.project)
        return self.store.get("jobs", (job or self.job)["id"])["result"]

    def test_short_candidate_cannot_skip_dense_and_boundary_review(self):
        self.project["duration"] = 70
        self.job["analysis"]["end"] = 70
        result = self.run_review(lambda *a, **k: (answer(victory=52), {}))
        self.assertEqual(result["status"], "candidate")
        self.assertGreater(result["rounds"], 6)
        self.assertGreater(result["frames"], 600)
        self.assertTrue(all(result["checks"].values()))
        self.assertTrue(any(step == .5 for _, _, step in self.requests))
        self.assertTrue(any(step <= 1 / 60 for _, _, step in self.requests))
        self.assertFalse(result["can_continue"])
        self.assertFalse(result["reviewed"])

    def test_budget_exhaustion_is_uncertain_and_resume_does_not_resample(self):
        first = self.run_review(calls=2)
        self.assertEqual(first["status"], "uncertain")
        self.assertTrue(first["can_continue"])
        done = list(self.requests)
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        self.requests.clear()
        result = self.run_review(job=resumed)
        self.assertEqual(result["status"], "candidate")
        self.assertFalse(set(done).intersection(self.requests))
        self.assertEqual(result["rounds"], len(done) + len(self.requests))

    def test_new_failure_moves_start_and_old_attempt_is_excluded(self):
        def observe(*args, **kwargs):
            # Dense inspection sees an earlier failed attempt missed by coarse sampling.
            dense_seen = any(step <= .5 for _, _, step in self.requests)
            return answer(start=8 if dense_seen else 4), {}
        result = self.run_review(observe)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["start"], 8)
        self.assertTrue(result["checks"]["boundaries"])
        self.assertTrue(any(6 <= a <= 10 and step <= 1 / 60 for a, _, step in self.requests))

    def test_suspicious_transition_requires_frame_level_evidence(self):
        def observe(*args, **kwargs):
            inspected = any(a <= 9 and b >= 9.25 and step <= 1 / 60 for a, b, step in self.requests)
            return answer(suspicious_windows=[] if inspected else [{"start": 9, "end": 9.25, "every": 2}]), {}
        result = self.run_review(observe)
        self.assertEqual(result["status"], "candidate")
        self.assertIn((9, 9.25, 1 / 60), self.requests)

    def test_unresolved_failure_never_becomes_a_candidate(self):
        result = self.run_review(lambda *a, **k: (answer(suspicious_windows=[{"start": 9, "end": 9.25, "every": 2}]), {}))
        self.assertEqual(result["status"], "uncertain")

    def test_whole_vod_is_scanned_beyond_thirty_minutes(self):
        self.project["duration"] = 7200
        self.job["analysis"]["end"] = 7200
        result = self.run_review(lambda *a, **k: (answer(status="not_found", start=None, victory=None), {}))
        self.assertEqual(result["status"], "not_found")
        self.assertGreater(max(b for _, b, _ in self.requests), 7100)

    def test_resume_rejects_source_replacement(self):
        self.run_review(calls=1)
        (self.root / "downloads/test.mp4").write_bytes(b"changed")
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        with self.assertRaisesRegex(ValueError, "來源或分析設定已變更"):
            self.run_review(job=resumed)

    def test_requests_can_span_multiple_execution_budgets(self):
        chunks = packets(0, 600, 1 / 60)
        self.assertGreater(len(chunks), 240)
        self.assertEqual(chunks[-1][1], 600)

    def test_single_frame_requests_and_coverage_gaps(self):
        self.assertEqual(list(missing_ranges(2, 2, .01, [])), [(2, 2)])
        history = [{"packet": {"start": 0, "end": 1, "every": .5}},
                   {"packet": {"start": 3, "end": 4, "every": .5}}]
        self.assertEqual(list(missing_ranges(0, 4, .5, history)), [(1.5, 2.5)])

    def test_stopped_extraction_retries_pending_packet_from_checkpoint(self):
        with patch("game_vod_clipper.codex_analysis.extract_packet", side_effect=RuntimeError("stopped")):
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                run_analysis(self.store, self.job, self.project)
        saved = json.loads((self.root / "runs/web/p/codex/first/checkpoint.json").read_text())
        self.assertEqual(saved["history"], [])
        self.assertTrue(saved["queue"])
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        self.assertEqual(self.run_review(job=resumed)["status"], "candidate")
