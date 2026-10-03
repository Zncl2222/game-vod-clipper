import unittest
import random

from game_vod_clipper.analysis.registry import CandidateRegistry
from game_vod_clipper.analysis.sampling import PACKET_SIZE, enqueue_unseen, missing_ranges, next_unseen, normalized_request


def segment(key, start=0, end=10, **changes):
    return dict(id=key, start=start, end=end, kind="fight", boss="Boss", **changes)


def observed(start, end, every):
    return {"packet": {"start": start, "end": end, "every": every}}


class RegistryTest(unittest.TestCase):
    def test_reusing_temporary_new1_in_later_round_does_not_overwrite_an_overlapping_event(self):
        registry = CandidateRegistry("job")
        registry.update([segment("new1", 0, 99) | {"kind": "possible_win"}])
        registry.update([segment("new1", 98, 100) | {"kind": "unknown"}])
        self.assertEqual(len(registry.public()), 2)
        self.assertEqual(registry.records["c0001"]["kind"], "possible_win")
        self.assertEqual(registry.records["c0001"]["start"], 0)
        self.assertEqual(registry.records["c0002"]["kind"], "unknown")
        self.assertNotIn("new1", registry.aliases)

    def test_host_ids_survive_prefixed_aliases_and_boundary_refinement(self):
        registry = CandidateRegistry("job")
        registry.update([segment("fight-1")])
        registry.update([segment("job-job-fight-1", start=1)])
        registry.update([segment("c0001", start=2, summary="refined")])
        self.assertEqual(len(registry.public()), 1)
        self.assertEqual(registry.public()[0]["id"], "job:c0001")
        self.assertEqual(registry.public()[0]["start"], 2)

    def test_duplicate_or_reused_model_id_does_not_destroy_separate_attempts(self):
        registry = CandidateRegistry("job")
        registry.update([segment("same"), segment("same", 15, 25)])
        self.assertEqual(len(registry.public()), 2)
        registry.update([segment("same", 30, 40)])
        self.assertEqual(len(registry.public()), 3)
        self.assertEqual(len({r["id"] for r in registry.public()}), 3)

    def test_renamed_identical_ranges_deduplicate_but_other_event_types_survive(self):
        registry = CandidateRegistry("job")
        registry.update([segment("one"), segment("two", start=.0167)])
        self.assertEqual(len(registry.public()), 1)
        death = segment("death") | {"kind": "death_retry"}
        registry.update([death])
        self.assertEqual(len(registry.public()), 2)

    def test_superseding_overlapping_hypothesis_is_explicit_and_persisted(self):
        registry = CandidateRegistry("job")
        registry.update([segment("one"), segment("two", 5, 20)])
        registry.update([segment("c0001", 0, 20, replaces=["c0002"])])
        self.assertEqual(len(registry.public()), 1)
        self.assertEqual(registry.retired["c0002"]["superseded_by"], "c0001")
        registry.update([segment("c0002", 0, 19)])
        self.assertEqual(len(registry.public()), 1)
        resumed = CandidateRegistry("job", registry.snapshot())
        resumed.update([segment("three", 30, 40)])
        self.assertEqual(resumed.public()[-1]["id"], "job:c0003")

    def test_replaces_cannot_hide_other_attempt_or_death_evidence(self):
        registry = CandidateRegistry("job")
        registry.update([segment("one"), segment("two", 30, 40),
                         segment("death", 5, 8) | {"kind": "death_retry"}])
        registry.update([segment("c0001", replaces=["c0002", "c0003"])])
        self.assertEqual(len(registry.public()), 3)


class QueueTest(unittest.TestCase):
    def test_coverage_matches_brute_force_grid_for_overlapping_intervals(self):
        rng = random.Random(1847)
        for _ in range(100):
            history = []
            for _ in range(10):
                a, b = sorted(rng.sample(range(21), 2))
                history.append(observed(a / 2, b / 2, rng.choice([.25, .5, 1])))
            gaps = list(missing_ranges(0, 10, .5, history))
            actual = {round((a + i * .5) * 2) for a, b in gaps for i in range(round((b - a) / .5) + 1)}
            expected = {i for i in range(21) if not any(h["packet"]["every"] <= .5
                and h["packet"]["start"] <= i / 2 <= h["packet"]["end"] for h in history)}
            self.assertEqual(actual, expected)

    def test_dequeue_rechecks_union_of_newly_observed_packets(self):
        queue = [[0, 5, .5, "refine"], [5, 8, .5, "refine"]]
        history = [observed(0, 2, .5), observed(2.5, 6, .5)]
        request, purpose = next_unseen(queue, history)
        self.assertEqual(request, (6.5, 8, .5))
        self.assertEqual(purpose, "refine")
        self.assertIsNone(next_unseen(queue, history + [observed(*request)]))

    def test_pending_ranges_deduplicate_alternate_packet_tilings(self):
        queue = []
        enqueue_unseen(queue, [], (0, 8, .5), "refine")
        enqueue_unseen(queue, [], (1, 6, 1), "refine")
        enqueue_unseen(queue, [], (2, 10, .5), "refine")
        self.assertEqual(queue, [[0, 8, .5, "refine"], [8.5, 10, .5, "refine"]])

    def test_frame_density_has_one_grid_and_cannot_repeat_subframe_sampling(self):
        queue = []
        enqueue_unseen(queue, [], (0, 1, .0167), "refine")
        enqueue_unseen(queue, [], (.001, .999, .001), "refine")
        self.assertEqual(queue, [[0, 1, 1 / 60, "refine"]])
        self.assertEqual(normalized_request(.001, .999, .001), (1 / 60, 59 / 60, 1 / 60))

    def test_larger_window_executes_in_small_nonrepeating_packets(self):
        queue = []
        enqueue_unseen(queue, [], (0, 4, 1 / 60), "refine")
        history = []
        while selected := next_unseen(queue, history):
            request, _ = selected
            self.assertLessEqual(round((request[1] - request[0]) / request[2]) + 1, PACKET_SIZE)
            history.append(observed(*request))
            enqueue_unseen(queue, history, (0, 4, .0167), "refine")
        self.assertEqual(len(history), 3)
