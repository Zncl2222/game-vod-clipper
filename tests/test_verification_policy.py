"""Stronger-model calls are local, visible and bounded across resumptions."""
import unittest

from game_vod_clipper.analysis.verification import verification_reason
from test_encounter_evidence import observation


class VerificationPolicyTests(unittest.TestCase):
    def test_unresolved_entry_uses_sol_only_in_a_short_relevant_dense_window(self):
        previous = observation(start=2397.5, entry_status="unknown", entry_proof=None)
        self.assertEqual(verification_reason("entry", (2395.5, 2409.5, .5), previous, None, [])[0], "entry")
        self.assertIsNone(verification_reason("entry", (2339.5, 2399.5, 2), previous, None, []))
        self.assertIsNone(verification_reason("entry", (2277.5, 2337.5, .5), previous, None, []))
        self.assertIsNone(verification_reason("entry", (2395.5, 2409.5, .5), previous, None, [{"role": "entry"}]))

    def test_discovery_and_ordinary_combat_never_escalate(self):
        self.assertIsNone(verification_reason("search", (0, 1770, 30), None, None, []))
        self.assertIsNone(verification_reason("dense", (2400, 2412, .5), observation(), observation(), []))

    def test_ending_is_checked_once_and_completed_ending_does_not_escalate(self):
        self.assertEqual(verification_reason("refine", (2580, 2600, .5), observation(ending_proof=None), None, [])[0], "ending")
        self.assertIsNone(verification_reason("refine", (2580, 2600, .5), None, None, []))
        self.assertEqual(verification_reason("refine", (2580, 2600, .5), None, observation(), [])[0], "ending")
        self.assertIsNone(verification_reason("refine", (2580, 2600, .5), observation(), None, []))
        self.assertIsNone(verification_reason("refine", (2580, 2600, .5), None, None, [{"role": "ending"}]))

    def test_new_entry_requires_a_proof_inside_the_current_packet(self):
        self.assertEqual(verification_reason("entry", (2380, 2420, 2), observation(), observation(), [])[0], "entry")
        self.assertIsNone(verification_reason("entry", (2490, 2502, .5), observation(), observation(), []))

    def test_transition_needs_local_dense_evidence_and_affects_the_attempt(self):
        local = observation(suspicious_windows=[{"start": 2484, "end": 2486, "every": .1}])
        self.assertEqual(verification_reason("dense", (2480, 2492, .5), observation(), local, [])[0], "transition")
        self.assertIsNone(verification_reason("dense", (2487, 2492, .5), observation(), local, []))
        self.assertIsNone(verification_reason("dense", (2480, 2492, 2), observation(), local, []))

    def test_three_recorded_calls_remain_the_limit_after_resume(self):
        prior = [{"role": "ending"}, {"role": "entry"}, {"role": "transition"}]
        self.assertIsNone(verification_reason("refine", (2580, 2600, .5), None, None, prior))
        self.assertIsNone(verification_reason("entry", (2380, 2420, 2), observation(), observation(), prior))
