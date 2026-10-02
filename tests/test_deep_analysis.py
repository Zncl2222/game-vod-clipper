"""Adaptive inspection contracts with deterministic observations; no paid AI calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_vod_clipper.codex_analysis import Observation, missing_ranges, packet_effort, packets, run_analysis, validate_observation, verified_outcome
from game_vod_clipper.web_store import Store


def answer(**changes):
    return {"status": "candidate", "start": 4, "victory": 12, "postroll": 5,
            "entry_status": "clean",
            "outcome": {"player": "active", "opponent": "defeated", "signal": "reward"},
            "boss": "Fixture", "summary": "Synthetic observation", "warnings": [],
            "evidence": [], "sample_requests": [], "suspicious_windows": [], **changes}


def segment(key="fight-1", **changes):
    return {"id": key, "start": 3, "end": 10, "victory": None, "kind": "fight",
            "confidence": "low", "boss": "測試", "summary": "需核對", "warnings": [],
            "evidence": [], **changes}


class DeepAnalysisTest(unittest.TestCase):
    def test_dialogue_and_loading_cannot_certify_a_win(self):
        for signal in ("dialogue", "loading", "none"):
            with self.subTest(signal=signal):
                result = self.run_review(lambda *a, **k: (answer(review_complete=True,
                    outcome={"player": "active", "opponent": "defeated", "signal": signal}), {}), calls=None)
                self.assertEqual(result["status"], "uncertain")
                self.assertIsNone(result["victory"])
                self.assertTrue(result["review_complete"])
                self.assertLessEqual(result["rounds"], 3)

    def test_player_defeat_overrides_a_claimed_victory(self):
        value = validate_observation(answer(outcome={"player": "defeated",
            "opponent": "active", "signal": "reward"}), 0, 20, 20)
        self.assertEqual(value.status, "uncertain")
        self.assertIsNone(value.victory)
        self.assertFalse(verified_outcome(value))

    def test_visible_victory_requires_a_surviving_player(self):
        for state in ("unknown", "defeated"):
            self.assertFalse(verified_outcome(Observation.model_validate(answer(outcome={
                "player": state, "opponent": "defeated", "signal": "reward"}))))
        self.assertTrue(verified_outcome(Observation.model_validate(answer(outcome={
            "player": "active", "opponent": "surrendered", "signal": "postfight"}))))
        # Recovering lost currency mid-battle is not a boss victory.
        self.assertFalse(verified_outcome(Observation.model_validate(answer(outcome={
            "player": "active", "opponent": "active", "signal": "reward"}))))

    def test_missing_outcome_is_checked_before_entry_or_continuity(self):
        def observe(*args, **kwargs):
            checked = any(step == .1 for _, _, step in self.requests)
            return answer(outcome={"player": "active", "opponent": "defeated", "signal": "reward"}
                          if checked else None, review_complete=True), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(self.requests[1], (10, 14, .1))
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["checks"]["outcome"])
        self.assertEqual(packet_effort("xhigh", "adaptive", "outcome", (10, 14, .1), None), "xhigh")

    def test_rejected_first_focus_moves_to_the_next_encounter(self):
        self.project["duration"] = self.job["analysis"]["end"] = 6000
        def observe(*args, **kwargs):
            a, b, step = self.requests[-1]
            if step == 30:
                return answer(start=None, victory=None, status="uncertain",
                    candidates=[segment("failed", start=100, end=130, confidence="medium"),
                                segment("winner", start=200, end=300, confidence="medium")]), {}
            if a < 150:
                return answer(start=None, victory=None, status="not_found", review_complete=True,
                    candidates=[segment("failed", start=100, end=130, kind="death_retry", confidence="high")]), {}
            return answer(start=200, victory=290, entry_status="clean", review_complete=True), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["start"], 200)
        self.assertTrue(all(result["checks"].values()))
        self.assertIn("failed_attempt", result["closed_investigations"].values())

    def test_unconfirmed_entry_cannot_pass_even_without_annotation_records(self):
        result = self.run_review(lambda *a, **k: (answer(entry_status="unknown", review_complete=True), {}), calls=None)
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["checks"]["entry"])

    def test_adaptive_effort_escalates_relevant_ambiguity_and_respects_fixed_choice(self):
        last = Observation.model_validate(answer(suspicious_windows=[{"start": 9, "end": 10, "every": .1}]))
        self.assertEqual(packet_effort("xhigh", "adaptive", "search", (0, 30, 1), last), "high")
        self.assertEqual(packet_effort("xhigh", "adaptive", "boundaries", (2, 6, .1), last), "high")
        self.assertEqual(packet_effort("xhigh", "adaptive", "boundaries", (8, 12, .1), last), "xhigh")
        self.assertEqual(packet_effort("xhigh", "fixed", "search", (0, 30, 1), last), "xhigh")
        self.assertEqual(packet_effort("medium", "adaptive", "suspicious", (9, 10, .1), last), "medium")

    def test_entry_is_localized_in_context_before_tiny_boundary_checks(self):
        self.project["duration"] = self.job["analysis"]["end"] = 300
        def observe(*args, **kwargs):
            a, b, step = self.requests[-1]
            if len(self.requests) == 1:
                return answer(start=150, victory=210, entry_status="mid_fight",
                    candidates=[segment("boss", start=150, end=220, victory=210,
                                        kind="possible_win", confidence="high")]), {}
            entry_seen = any(step == 2 and b - a > 30 for a, b, step in self.requests)
            return answer(start=170 if entry_seen else 150, victory=210,
                entry_status="clean" if entry_seen else "mid_fight", review_complete=True), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(self.requests[1][2], 2)
        self.assertGreater(self.requests[1][1] - self.requests[1][0], 30)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["start"], 170)
        self.assertTrue(result["checks"]["entry"])

    def test_earlier_failure_repairs_entry_without_discarding_a_later_verified_win(self):
        self.project["duration"] = self.job["analysis"]["end"] = 300
        failure_reported = False
        def observe(*args, **kwargs):
            nonlocal failure_reported
            a, b, step = self.requests[-1]
            if len(self.requests) == 1:
                return answer(start=150, victory=210, entry_status="mid_fight",
                    candidates=[segment("boss", start=150, end=220, victory=210,
                                        kind="possible_win", confidence="high")]), {}
            if step == 2 and not failure_reported:
                failure_reported = True
                return answer(status="uncertain", start=None, victory=None, entry_status="unknown",
                    outcome={"player": "defeated", "opponent": "active", "signal": "loading"},
                    candidates=[segment("c0001", start=150, end=min(b, 180),
                        kind="death_retry", confidence="high")], review_complete=True), {}
            return answer(start=185, victory=210, entry_status="clean", review_complete=True), {}
        # The ending was verified in a separate packet. Coarse coverage also
        # occupies its late range, so the backward entry packet ends earlier.
        self.run_review(lambda *a, **k: (answer(start=150, victory=210,
            candidates=[segment("boss", start=150, end=220, victory=210,
                                kind="possible_win", confidence="high")]), {}), calls=1)
        saved_path = self.store.root / "runs/web/p/codex/first/checkpoint.json"
        saved = json.loads(saved_path.read_text())
        saved["history"].append({"packet": {"start": 190, "end": 220, "every": .5,
            "timestamps": [190 + i * .5 for i in range(61)]}, "purpose": "refine", "scope": "c0001",
            "observation": answer(start=150, victory=210, entry_status="mid_fight", review_complete=True)})
        saved["queue"] = []
        saved["entry_plan"] = {}
        saved_path.write_text(json.dumps(saved))
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        result = self.run_review(observe, calls=None, job=resumed)
        self.assertTrue(failure_reported)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["victory"], 210)
        self.assertEqual(result["start"], 185)
        self.assertTrue(any(c["kind"] == "death_retry" for c in result["candidates"]))
        self.assertTrue(all(result["checks"].values()))

    def test_incomplete_candidate_is_preserved_as_uncertain_instead_of_failing_the_job(self):
        result = self.run_review(lambda *a, **k: (answer(victory=None,
            candidates=[segment()], review_complete=True), {}), calls=None)
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["victory"])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertTrue(result["review_complete"])

    def test_stalled_provider_call_keeps_the_inflight_packet_unreviewed(self):
        from game_vod_clipper.codex_runtime import CodexCallError
        def stalled(*args, **kwargs):
            raise CodexCallError("stalled", kind="timeout")
        with self.assertRaises(CodexCallError):
            self.run_review(stalled, calls=None)
        path = self.store.root / "runs/web/p/codex/first/checkpoint.json"
        saved = json.loads(path.read_text())
        self.assertEqual(saved["history"], [])
        self.assertEqual(len(saved["queue"]), 1)
        self.assertNotIn("result", self.store.get("jobs", "first"))

    def test_host_localizes_a_compact_encounter_before_unrelated_long_fights(self):
        self.project["duration"] = self.job["analysis"]["end"] = 7200
        def observe(*args, **kwargs):
            if self.requests[-1][2] == 30:
                return answer(status="uncertain", start=None, victory=None,
                    candidates=[segment("short", start=100, end=130, confidence="medium"),
                                segment("long", start=200, end=1000, confidence="high")],
                    sample_requests=[{"start": 200, "end": 1000, "every": .5}]), {}
            return answer(start=100, victory=120, entry_status="clean", review_complete=True), {}
        result = self.run_review(observe, calls=None)
        self.assertTrue(result["checks"]["search"])
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["start"], 100)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertFalse(any(a >= 200 and step < 30 for a, _, step in self.requests))
        self.assertTrue(all(result["checks"].values()))

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
                return answer(start=2, review_complete=True), {}
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

    def test_analysis_bounds_a_stuck_call_without_a_whole_vod_round_budget(self):
        from game_vod_clipper.codex_analysis import MAX_CALLS
        self.assertIsNone(MAX_CALLS)
        def observe(work, images, prompt, timeout, **kwargs):
            self.assertEqual(timeout, 180)
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
        self.assertGreater(result["rounds"], 2)
        self.assertFalse(list(missing_ranges(4, 57, .5,
            [{"packet": p} for p in result["coverage"]])))
        self.assertTrue(all(result["checks"].values()))
        self.assertTrue(any(step == .5 for _, _, step in self.requests))
        self.assertTrue(any(step <= .1 for _, _, step in self.requests))
        self.assertFalse(result["can_continue"])
        self.assertFalse(result["reviewed"])

    def test_continuity_is_reviewed_in_short_packets_without_coverage_gaps(self):
        self.project["duration"] = self.job["analysis"]["end"] = 150
        result = self.run_review(lambda *a, **k: (answer(victory=130), {}), calls=None)
        dense = [(a, b, step) for a, b, step in self.requests if step == .5]
        self.assertGreater(len(dense), 1)
        self.assertTrue(all(b - a <= 11.5 for a, b, _ in dense))
        self.assertFalse(list(missing_ranges(4, 135, .5, [{"packet": p} for p in result["coverage"]])))
        self.assertEqual(result["status"], "candidate")

    def test_unrelated_packet_cannot_erase_an_unresolved_failure(self):
        reported = False
        def observe(work, images, prompt, *args, **kwargs):
            nonlocal reported
            purpose = json.loads(prompt.split("CONTEXT:\n")[1])["task"]
            windows = []
            if purpose == "boundaries" and not reported:
                reported = True
                windows = [{"start": 4.5, "end": 5, "every": .1}]
            # The next packet checks victory at 10–14, and forgets the entry suspicion.
            return answer(review_complete=True, suspicious_windows=windows), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["unresolved_windows"], [{"start": 4.5, "end": 5, "every": .1}])
        self.assertFalse(result["checks"]["failure_free"])

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
        self.assertTrue(any(6 <= a <= 10 and step <= .1 for a, _, step in self.requests))

    def test_suspicious_transition_requires_frame_level_evidence(self):
        def observe(*args, **kwargs):
            inspected = any(a <= 9 and b >= 9.25 and step <= 1 / 60 for a, b, step in self.requests)
            return answer(suspicious_windows=[] if inspected else [{"start": 9, "end": 9.25, "every": 1 / 60}]), {}
        result = self.run_review(observe)
        self.assertEqual(result["status"], "candidate")
        self.assertIn((9, 9.25, 1 / 60), self.requests)

    def test_unresolved_failure_never_becomes_a_candidate(self):
        result = self.run_review(lambda *a, **k: (answer(suspicious_windows=[{"start": 9, "end": 9.25, "every": 2}]), {}))
        self.assertEqual(result["status"], "uncertain")

    def test_verified_candidate_finishes_without_unrelated_refinement(self):
        self.project["duration"] = self.job["analysis"]["end"] = 180
        def observe(*args, **kwargs):
            return answer(sample_requests=[{"start": 80, "end": 179, "every": .5}]), {}
        result = self.run_review(observe, calls=None)
        self.assertFalse(any(a >= 80 and step == .5 for a, _, step in self.requests))
        reviewed = [{"packet": {"start": a, "end": b, "every": step}}
                    for a, b, step in self.requests]
        for a, b, step in [(4, 17, .5), (2, 6, .1), (10, 14, .1)]:
            self.assertFalse(list(missing_ranges(a, b, step, reviewed)))
        self.assertTrue(result["review_complete"])

    def test_moving_suspicious_windows_exhaust_without_a_time_or_round_limit(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                suspicious_windows=[{"start": at, "end": at + .2, "every": .1}]), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["completion_reason"], "evidence_exhausted")
        self.assertTrue(result["exhausted_reviews"])
        self.assertTrue(result["review_complete"])
        self.assertFalse(result["can_continue"])

    def test_suspicion_exhaustion_survives_resume(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                suspicious_windows=[{"start": at, "end": at + .2, "every": .1}]), {}
        self.run_review(observe, calls=3)
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        result = self.run_review(observe, calls=None, job=resumed)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(result["completion_reason"], "evidence_exhausted")

    def test_boundary_jitter_and_unrelated_discoveries_do_not_reset_local_stall(self):
        self.project["duration"] = self.job["analysis"]["end"] = 180
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                candidates=[segment("local", start=1 + at / 10, end=20 + at / 10),
                            segment(f"distant{at}", start=90 + at, end=91 + at)],
                suspicious_windows=[{"start": 2 + at, "end": 2.2 + at, "every": .1}]), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(len(result["exhausted_reviews"]), 1)

    def test_long_suspicion_first_localizes_before_frame_level_work(self):
        result = self.run_review(lambda *a, **k: (answer(status="uncertain", start=None, victory=None,
            suspicious_windows=[{"start": 8, "end": 18, "every": 1 / 60}]), {}), calls=None)
        self.assertEqual(result["rounds"], 2)
        self.assertIn((8, 18, .5), self.requests)
        self.assertTrue(all(step >= .5 for _, _, step in self.requests))

    def test_known_earlier_failure_does_not_block_preferred_candidate(self):
        result = self.run_review(lambda *a, **k: (answer(
            candidates=[segment("earlier", start=0, end=1, kind="death_retry", confidence="high")],
            suspicious_windows=[{"start": 0, "end": 1, "every": .1}],
            sample_requests=[{"start": 0, "end": 1, "every": .1}]), {}), calls=None)
        self.assertEqual(result["status"], "candidate")
        self.assertTrue(result["review_complete"])
        self.assertTrue(result["unresolved_windows"])
        self.assertFalse(any(a < 2 and step < 1 for a, _, step in self.requests))

    def test_death_annotation_inside_candidate_blocks_acceptance_after_review_ends(self):
        result = self.run_review(lambda *a, **k: (answer(review_complete=True,
            candidates=[segment("failure", start=8, end=9, kind="death_retry", confidence="high")]), {}), calls=None)
        self.assertTrue(result["review_complete"])
        self.assertFalse(result["checks"]["failure_free"])
        self.assertEqual(result["status"], "uncertain")
        self.assertTrue(any("重疊" in warning for warning in result["warnings"]))

    def test_suspicious_pass_finishes_before_model_extends_its_window(self):
        self.project["duration"] = self.job["analysis"]["end"] = 600
        def observe(*args, **kwargs):
            return answer(status="uncertain", start=None, victory=None,
                suspicious_windows=[{"start": 0, "end": 299 + len(self.requests), "every": .5}]), {}
        result = self.run_review(observe, calls=None)
        self.assertTrue(result["review_complete"])
        self.assertFalse(result["can_continue"])
        self.assertLess(result["rounds"], 15)
        self.assertFalse(list(missing_ranges(0, 300, .5,
            [{"packet": p} for p in result["coverage"]])))

    def test_priority_coverage_does_not_silently_drop_next_local_question(self):
        def observe(*args, **kwargs):
            covered = not list(missing_ranges(4, 17, .5,
                [{"packet": {"start": a, "end": b, "every": step}} for a, b, step in self.requests]))
            request = {"start": 8, "end": 8.2, "every": .1} if covered else {"start": 4, "end": 17, "every": .5}
            return answer(sample_requests=[request]), {}
        result = self.run_review(observe, calls=None)
        self.assertIn((8, 8.2, .1), self.requests)
        self.assertTrue(result["review_complete"])

    def test_renaming_an_unchanged_hypothesis_cannot_restart_inspection(self):
        def observe(*args, **kwargs):
            at = len(self.requests)
            return answer(status="uncertain", start=None, victory=None,
                candidates=[segment("new1", start=1 + at / 10, end=20 + at / 10)],
                sample_requests=[{"start": 2 + at, "end": 2.2 + at, "every": .1}]), {}
        result = self.run_review(observe, calls=None)
        self.assertEqual(result["rounds"], 4)
        self.assertEqual(result["completion_reason"], "evidence_exhausted")

    def test_version_three_checkpoint_migrates_without_resampling(self):
        self.run_review(calls=2)
        checkpoint = self.root / "runs/web/p/codex/first/checkpoint.json"
        saved = json.loads(checkpoint.read_text())
        saved["version"] = 3
        saved["queue"] = [q[:4] for q in saved["queue"]]
        saved["convergence"] = {"seen_findings": [], "stalled_refinements": 0, "refinement_closed": False}
        for item in saved["history"]:
            item.pop("scope", None)
            item.pop("purpose", None)
        checkpoint.write_text(json.dumps(saved))
        done = set(self.requests)
        self.requests.clear()
        resumed = {**self.job, "id": "second", "analysis": {**self.job["analysis"], "resume_from": "first"}}
        self.store.put("jobs", resumed)
        result = self.run_review(job=resumed, calls=None)
        self.assertTrue(result["review_complete"])
        self.assertEqual(result["status"], "candidate")
        self.assertFalse(done.intersection(self.requests))

    def test_unstable_required_boundaries_finish_uncertain_without_false_approval(self):
        def observe(*args, **kwargs):
            return answer(start=4 + len(self.requests) / 10), {}
        result = self.run_review(observe, calls=None)
        self.assertLess(result["rounds"], 10)
        self.assertTrue(result["review_complete"])
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["completion_reason"], "evidence_exhausted")
        self.assertFalse(all(result["checks"].values()))
        self.assertEqual(result["exhausted_reviews"][0]["reason"], "unstable_boundaries")

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
