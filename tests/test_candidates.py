"""Review ranges survive ambiguity and stay isolated from export approval."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from game_vod_clipper.candidates import project_candidates
from game_vod_clipper.candidate_registry import CandidateRegistry
from game_vod_clipper.web import create_app
from game_vod_clipper.web_store import Store


class CandidatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.store = self.app.state.store
        self.project = {"id": "p", "title": "Fixture", "duration": 100, "ready": True,
            "draft": {"start": 1, "victory": 50, "postroll": 8, "revision": 0, "reviewed": False, "origin": "manual"}}
        self.segment = {"id": "first:c1", "start": 20, "end": 40, "victory": None,
            "kind": "fight", "confidence": "low", "boss": "Fixture", "summary": "待核對", "warnings": [], "evidence": []}
        self.job = {"id": "first", "kind": "analyze", "project_id": "p", "status": "cancelled", "candidates": [self.segment]}
        self.store.put("projects", self.project)
        self.store.put("jobs", self.job)

    def tearDown(self):
        self.temp.cleanup()

    def test_resume_refines_ids_and_numbers_without_merging_different_projects(self):
        self.store.put("jobs", {**self.job, "id": "resume", "candidates": [dict(self.segment, start=22),
            dict(self.segment, id="first:c2", start=45, end=60)]})
        self.store.put("jobs", {**self.job, "id": "foreign", "project_id": "other"})
        values = project_candidates(self.project, self.store.all("jobs"))
        self.assertEqual([v["number"] for v in values], [1, 2])
        self.assertEqual(values[0]["start"], 22)

    def test_provisional_and_failed_verification_are_visible_on_individual_candidates(self):
        first = dict(self.segment, kind="possible_win", victory=35)
        second = dict(first, id="first:c2", start=50, end=80, victory=80,
                      confidence="high", summary="完整成功嘗試")
        result = {"status": "uncertain", "start": 50, "victory": 80, "postroll": 8,
                  "review_complete": True, "checks": {"dense": True},
                  "warnings": ["仍與死亡／重試片段重疊"]}
        job = self.job | {"status": "succeeded", "candidates": [first, second], "result": result}
        values = project_candidates(self.project, [job])
        self.assertEqual([v["verification"] for v in values], ["unverified", "blocked"])
        self.assertIn("仍與死亡／重試片段重疊", values[1]["warnings"])
        self.assertNotIn("仍與死亡／重試片段重疊", values[0]["warnings"])
        self.assertEqual(second["warnings"], [])  # Public projection cannot rewrite evidence.

    def test_only_exact_verified_attempt_gets_verified_label_and_its_postroll(self):
        segment = dict(self.segment, kind="possible_win", victory=35)
        result = {"status": "candidate", "start": 20, "victory": 35, "postroll": 6,
                  "review_complete": True, "warnings": [],
                  "checks": dict.fromkeys(("search", "entry", "outcome", "boundaries", "dense", "continuity"), True)}
        job = self.job | {"status": "succeeded", "result": result, "candidates": [segment]}
        verified = project_candidates(self.project, [job])[0]
        self.assertEqual(verified["verification"], "verified")
        self.assertEqual(verified["postroll"], 6)
        for changes in ({"start": 19}, {"victory": 34}):
            other = job | {"candidates": [segment | changes]}
            self.assertEqual(project_candidates(self.project, [other])[0]["verification"], "unverified")
        for changes in ({"checks": {}}, {"review_complete": False}):
            incomplete = job | {"result": result | changes}
            self.assertNotEqual(project_candidates(self.project, [incomplete])[0]["verification"], "verified")

    def test_failure_in_postroll_blocks_candidate_but_earlier_failure_does_not(self):
        winner = dict(self.segment, kind="possible_win", victory=35)
        failure = dict(self.segment, id="first:failure", start=38, end=39,
                       kind="death_retry", confidence="high")
        job = self.job | {"candidates": [winner, failure]}
        value = project_candidates(self.project, [job])[0]
        self.assertEqual(value["verification"], "blocked")
        self.assertTrue(any("死亡" in w for w in value["warnings"]))
        failure.update(start=10, end=15)
        self.assertEqual(project_candidates(self.project, [job])[0]["verification"], "unverified")

    def test_review_persists_without_approving_draft_and_reset_invalidates_tags(self):
        with TestClient(self.app) as client:
            body = {"candidate_id": "first:c1", "review": "keep", "analysis_generation": 0}
            self.assertEqual(client.put("/api/projects/p/candidate-review", json=body).status_code, 200)
            saved = Store(Path(self.temp.name)).get("projects", "p")
            self.assertEqual(saved["candidate_reviews"], {"first:c1": "keep"})
            self.assertEqual(saved["draft"], self.project["draft"])
            self.assertEqual(client.post("/api/projects/p/exports", json={"revision": 0}).status_code, 422)
            for changes, expected in [({"candidate_id": "other:c1"}, 404), ({"review": "approved"}, 422)]:
                self.assertEqual(client.put("/api/projects/p/candidate-review", json=body | changes).status_code, expected)
            self.store.reset_analysis("p")
            self.assertEqual(client.put("/api/projects/p/candidate-review", json=body).status_code, 409)
            self.assertEqual(self.store.get("projects", "p")["candidate_reviews"], {})

    def test_legacy_duplicates_share_canonical_ui_and_chat_view_preserving_review(self):
        duplicate = dict(self.segment, id="first:duplicate", summary="updated")
        self.store.put("jobs", self.job | {"candidates": [self.segment, duplicate]})
        self.store.set_candidate_review("p", duplicate["id"], "keep", 0)
        with TestClient(self.app) as client:
            state = client.get("/api/state").json()
        project = state["projects"][0]
        values = project["review_candidates"]
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["id"], self.segment["id"])
        self.assertEqual(values[0]["summary"], "updated")
        self.assertEqual(values[0]["review"], "keep")
        self.assertEqual(values, project_candidates(project, state["jobs"]))
        self.assertEqual(len(self.store.get("jobs", "first")["candidates"]), 2)

    def test_superseded_candidates_do_not_reappear_from_previous_jobs(self):
        self.store.put("jobs", self.job | {"id": "second", "superseded_candidates": [self.segment["id"]],
            "candidates": [dict(self.segment, id="first:c2", end=50)]})
        values = project_candidates(self.project, self.store.all("jobs"))
        self.assertEqual([v["id"] for v in values], ["first:c2"])

    def test_legacy_resume_changes_bounds_without_resurrecting_old_ids_or_losing_tags(self):
        registry = CandidateRegistry("first")
        registry.update([self.segment])
        registry.update([dict(self.segment, id="c0001", start=22, end=42)])
        self.store.put("jobs", self.job | {"id": "resume", "candidates": registry.public(),
            "superseded_candidates": registry.superseded_ids()})
        project = self.project | {"candidate_reviews": {self.segment["id"]: "keep"}}
        values = project_candidates(project, self.store.all("jobs"))
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["start"], 22)
        self.assertEqual(values[0]["review"], "keep")

    def test_chat_receives_numbered_uncertain_candidates_and_saved_tags(self):
        self.store.set_candidate_review("p", "first:c1", "keep", 0)
        self.app.state.codex.models = AsyncMock(return_value=[{"id": "test"}])
        self.app.state.codex.respond = AsyncMock(return_value={"reply": json.dumps({"reply": "查看 #1", "action": {
            "kind": "select_candidate", "candidate_id": "first:c1", "start": None, "victory": None, "postroll": None, "seconds": None}})})
        with TestClient(self.app) as client:
            response = client.post("/api/codex/chat", json={"model": "test", "message": "查看 #1",
                "context": {"project_id": "p", "draft": {"start": 1, "victory": 50, "postroll": 8}}})
            self.assertEqual(json.loads(response.text.splitlines()[-1])["action"]["candidate_id"], "first:c1")
            prompt = self.app.state.codex.respond.call_args.args[0]
            self.assertIn('"number": 1', prompt)
            self.assertIn('"review": "keep"', prompt)
            self.assertIn('"victory": null', prompt)
            self.app.state.codex.respond.return_value = {"reply": json.dumps({"reply": "bad id", "action": {
                "kind": "select_candidate", "candidate_id": "other:c1", "start": None, "victory": None, "postroll": None, "seconds": None}})}
            response = client.post("/api/codex/chat", json={"model": "test", "message": "查看 #1",
                "context": {"project_id": "p", "draft": {"start": 1, "victory": 50, "postroll": 8}}})
            self.assertEqual(json.loads(response.text.splitlines()[-1])["type"], "error")
