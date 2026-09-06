"""Review ranges survive ambiguity and stay isolated from export approval."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from game_vod_clipper.candidates import project_candidates
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
