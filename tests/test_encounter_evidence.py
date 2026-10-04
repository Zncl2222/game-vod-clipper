"""Boss eligibility and packet-local evidence regressions from the VOD audit."""
import json
import unittest

from game_vod_clipper.analysis.models import Observation
from game_vod_clipper.analysis.sampling import normalized_request
from game_vod_clipper.analysis.validation import (
    failure_overlaps, preserve_verified_ending, validate_observation,
    localized_ending, verified_encounter, verified_entry, verified_outcome,
)


def observation(**changes):
    return Observation.model_validate({
        "status": "candidate", "start": 2400.5, "victory": 2588, "postroll": 8,
        "boss": "山縣昌景", "summary": "", "warnings": [], "evidence": [], "sample_requests": [],
        "entry_status": "clean", "entry_proof": {"time": 2400.5, "event": "進入戰場", "kind": "arena_entry"},
        "outcome": {"player": "active", "opponent": "defeated", "signal": "objective_complete"},
        "ending_proof": {"phase": "onset", "last_combat": {"time": 2587.5, "event": "最後交戰"},
                         "first_defeat": {"time": 2588, "event": "達成"}},
        "encounter": {"status": "confirmed", "signal": "boss_hud",
                      "evidence": [{"time": 2520, "event": "山縣昌景首領血條"}]}, **changes,
    })


class EncounterEvidenceTests(unittest.TestCase):
    def test_inverted_range_keeps_only_a_grounded_unverified_ending_investigation(self):
        data = observation(status="uncertain", start=None, victory=None, entry_status="unknown",
                           entry_proof=None, outcome=None,
                           ending_proof={"phase": "unresolved", "last_combat": {"time": 2580, "event": "Still fighting"},
                                         "first_defeat": None}).model_dump()
        data["candidates"] = [{"id": "old", "replaces": ["failure"], "start": 1800, "end": 0, "victory": None,
                               "kind": "possible_win", "confidence": "high", "boss": "山縣昌景", "summary": "",
                               "warnings": [], "evidence": [{"time": 2580, "event": "Still fighting"}],
                               "encounter": {"status": "confirmed", "signal": "boss_hud",
                                             "evidence": [{"time": 1800, "event": "Named boss HUD"}]},
                               "ending_window": {"start": 2580, "end": 2850, "every": 5}}]
        value = validate_observation(data, 0, 3000, 3000)
        candidate = value.candidates[0]
        self.assertEqual((candidate.start, candidate.end), (1800, 2610))
        self.assertEqual(candidate.ending_window.start, 2580)
        self.assertEqual(candidate.confidence, "low")
        self.assertIsNone(candidate.victory)
        self.assertNotEqual(candidate.id, "old")
        self.assertFalse(candidate.replaces)
        self.assertFalse(localized_ending(value))
        self.assertFalse(verified_outcome(value))
        for condition in ("ordinary", "different_boss", "unrelated_combat", "defeated"):
            with self.subTest(condition=condition):
                other = json.loads(json.dumps(data))
                if condition == "ordinary":
                    other["candidates"][0]["encounter"]["status"] = "ordinary"
                elif condition == "different_boss":
                    other["candidates"][0]["boss"] = "Another boss"
                elif condition == "unrelated_combat":
                    other["candidates"][0]["evidence"][0]["time"] = 2400
                else:
                    other["outcome"] = {"player": "defeated", "opponent": "active", "signal": "none"}
                self.assertFalse(validate_observation(other, 0, 3000, 3000).candidates)

    def test_inconsistent_annotation_cannot_abort_or_certify_the_valid_focus(self):
        data = observation().model_dump()
        data["candidates"] = [{"id": "bad", "start": 2600, "end": 2596, "victory": 2588,
                               "kind": "possible_win", "confidence": "high", "boss": "", "summary": "",
                               "warnings": [], "evidence": []}]
        value = validate_observation(data, 0, 3000, 3000)
        self.assertFalse(value.candidates)
        self.assertTrue(localized_ending(value))
        data["candidates"][0]["kind"] = "death_retry"
        with self.assertRaisesRegex(ValueError, "死亡"):
            validate_observation(data, 0, 3000, 3000)

    def test_midfight_cannot_move_a_verified_entry_using_unrelated_combat(self):
        local = observation(start=2490.5, entry_proof={"time": 2490.5, "event": "交戰", "kind": "first_combat"})
        preserve_verified_ending(observation(), local, (2490.5, 2502, .5), "dense")
        self.assertEqual(local.start, 2400.5)
        self.assertEqual(local.entry_proof.time, 2400.5)

    def test_late_postfight_frame_cannot_be_the_defeat_onset(self):
        value = observation(victory=2600, ending_proof={"phase": "onset",
            "last_combat": {"time": 2585, "event": "最後交戰"}, "first_defeat": {"time": 2600, "event": "已在戰後"}})
        self.assertTrue(verified_outcome(value))
        self.assertFalse(localized_ending(value))
        self.assertFalse(localized_ending(observation(ending_proof={"phase": "already_over", "last_combat": None, "first_defeat": None})))
        self.assertTrue(localized_ending(observation()))

    def test_midfight_packet_preserves_separately_observed_win_and_entry(self):
        previous = observation()
        local = observation(start=2490.5, victory=None, entry_status="mid_fight", entry_proof=None,
                            encounter=None, outcome={"player": "active", "opponent": "active", "signal": "none"})
        self.assertTrue(preserve_verified_ending(previous, local, (2490.5, 2502, .5), "dense"))
        self.assertTrue(verified_outcome(local))
        self.assertTrue(verified_encounter(local))
        self.assertTrue(verified_entry(local))
        self.assertEqual(local.start, 2400.5)
        self.assertEqual(local.victory, 2588)

    def test_actual_ending_view_can_refute_saved_win(self):
        local = observation(victory=None, outcome={"player": "active", "opponent": "active", "signal": "none"})
        self.assertFalse(preserve_verified_ending(observation(), local, (2586, 2590, .1), "boundaries"))
        self.assertFalse(verified_outcome(local))

    def test_player_failure_is_retained_even_when_later_win_is_preserved(self):
        local = observation(outcome={"player": "defeated", "opponent": "active", "signal": "none"})
        preserve_verified_ending(observation(), local, (2490.5, 2502, .5), "dense")
        self.assertEqual(local.entry_status, "unknown")
        self.assertEqual(local.status, "uncertain")
        self.assertEqual(local.suspicious_windows[0].start, 2490.5)

    def test_failure_annotation_invalidates_a_previously_clean_entry(self):
        data = observation().model_dump()
        data["candidates"] = [{"id": "reset", "start": 2480, "end": 2490, "victory": None,
                               "kind": "death_retry", "confidence": "high", "boss": "", "summary": "",
                               "warnings": [], "evidence": []}]
        local = Observation.model_validate(data)
        preserve_verified_ending(observation(), local, (2480, 2500, .5), "dense")
        self.assertEqual(local.entry_status, "unknown")
        self.assertIsNone(local.entry_proof)
        self.assertTrue(verified_outcome(local))

    def test_new_clean_entry_after_a_failure_remains_valid(self):
        previous = observation(start=2300, entry_proof={"time": 2300, "kind": "arena_entry", "event": "舊進場"})
        data = observation().model_dump()
        data["candidates"] = [{"id": "reset", "start": 2386, "end": 2400, "victory": None,
                               "kind": "death_retry", "confidence": "high", "boss": "", "summary": "",
                               "warnings": [], "evidence": []}]
        local = Observation.model_validate(data)
        preserve_verified_ending(previous, local, (2380, 2420, .5), "entry")
        self.assertTrue(verified_entry(local))
        self.assertEqual(local.start, 2400.5)

    def test_ordinary_enemy_reward_does_not_establish_boss_eligibility(self):
        value = observation(encounter={"status": "ordinary", "signal": "none", "evidence": []})
        self.assertTrue(verified_outcome(value))
        self.assertFalse(verified_encounter(value))
        preserve_verified_ending(observation(), value, (2490.5, 2502, .5), "dense")
        self.assertFalse(verified_encounter(value))

    def test_boss_identity_from_an_earlier_attempt_does_not_certify_this_scene(self):
        value = observation(encounter={"status": "confirmed", "signal": "boss_hud",
                                       "evidence": [{"time": 1800, "event": "Earlier attempt HUD"}]})
        self.assertFalse(verified_encounter(value))
        preserve_verified_ending(observation(), value, (2490.5, 2502, .5), "dense")
        self.assertFalse(verified_encounter(value))

    def test_checkpoint_cannot_be_a_clean_entry(self):
        data = observation(start=2396, entry_proof={"time": 2396, "event": "重生點", "kind": "checkpoint"}).model_dump()
        value = validate_observation(data, 0, 3000, 3000)
        self.assertFalse(verified_entry(value))
        self.assertEqual(value.entry_status, "unknown")

    def test_shared_failure_endpoint_needs_independent_entry_proof(self):
        failure = {"start": 2386, "end": 2400.5}
        self.assertFalse(failure_overlaps(failure, observation()))
        self.assertTrue(failure_overlaps(failure, observation(entry_proof=None)))
        self.assertTrue(failure_overlaps({"start": 2400.5, "end": 2401}, observation()))

    def test_zero_duration_event_cannot_abort_or_certify_an_attempt(self):
        data = observation().model_dump()
        data["candidates"] = [{"id": "point", "start": 2588, "end": 2588, "victory": 2588,
                               "kind": "possible_win", "confidence": "high", "boss": "", "summary": "",
                               "warnings": [], "evidence": []}]
        value = validate_observation(data, 0, 3000, 3000, 30)
        self.assertEqual(value.candidates[0].kind, "unknown")
        self.assertIsNone(value.candidates[0].victory)
        self.assertAlmostEqual(value.candidates[0].end, 2588 + 1 / 30)

    def test_native_sampling_uses_thirty_fps_source(self):
        a, b, every = normalized_request(2010.01, 2010.11, .001, frame_rate=30)
        self.assertEqual(every, 1 / 30)
        self.assertAlmostEqual(a * 30, round(a * 30))
        self.assertAlmostEqual(b * 30, round(b * 30))

    def test_search_and_other_focus_do_not_transfer_identity(self):
        local = observation(encounter=None, victory=None, outcome=None)
        self.assertFalse(preserve_verified_ending(observation(), local, (0, 100, 30), "search"))
        self.assertFalse(verified_encounter(local))
