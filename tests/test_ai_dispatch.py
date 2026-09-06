"""Unified task dispatch using metadata and mocks, never media or live AI."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from game_vod_clipper.web import create_app


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        async def idle_worker(*args):
            await asyncio.Future()
        self.worker = patch("game_vod_clipper.web.Jobs.execute", new=idle_worker)
        self.worker.start()
        self.app = create_app(Path(self.temp.name))
        self.store = self.app.state.store
        self.store.put("projects", {"id": "p", "ready": True, "title": "Metadata only", "duration": 300})
        self.codex = self.app.state.codex
        self.codex.status = AsyncMock(return_value={"available": True})
        self.codex.models = AsyncMock(return_value=[{"id": "picked", "effort": "low", "input_modalities": ["text", "image"]}])
        self.action = {"kind": "search", "start": 0, "end": 120, "victory": None, "postroll": None, "seconds": None}
        self.codex.respond = AsyncMock(return_value={"reply": json.dumps({"reply": "搜尋這個範圍", "action": self.action})})
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.worker.stop()
        self.temp.cleanup()

    def request(self, **changes):
        body = {"message": "搜尋前兩分鐘", "model": "picked",
                "context": {"project_id": "p", "draft": {"start": 10, "victory": 100, "postroll": 8}}, **changes}
        response = self.client.post("/api/codex/chat", json=body)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.text.splitlines()[-1])

    def test_button_and_conversation_share_queue_and_pinned_model(self):
        click = self.request(intent="search", search_start=0, search_end=120)
        self.codex.respond.assert_not_awaited()
        first = self.store.get("jobs", click["job_id"])
        self.store.patch("jobs", first["id"], status="cancelled")
        text = self.request()
        second = self.store.get("jobs", text["job_id"])
        for field in ("start", "end", "model", "effort"):
            self.assertEqual(first["analysis"][field], second["analysis"][field])
        self.assertEqual(second["model"], "picked")
        self.assertIsNone(text["action"])

    def test_repeated_request_is_idempotent_and_other_search_is_rejected(self):
        body = {"intent": "search", "search_start": 0, "search_end": 120, "request_id": "same-request"}
        first = self.request(**body)
        self.assertEqual(first["job_id"], self.request(**body)["job_id"])
        self.assertEqual(len(self.store.all("jobs")), 1)
        self.assertEqual(self.request(**{**body, "request_id": "another"})["type"], "error")

    def test_vision_capability_required_without_fallback(self):
        self.codex.models.return_value = [{"id": "picked", "effort": "low", "input_modalities": ["text"]}]
        result = self.request(intent="search", search_start=0, search_end=120)
        self.assertEqual(result["type"], "error")
        self.assertEqual(self.store.all("jobs"), [])

    def test_results_are_included_in_followup_context(self):
        self.store.put("jobs", {"id": "completed", "kind": "analyze", "project_id": "p", "status": "succeeded",
                                "result": {"status": "uncertain", "summary": "勝利畫面不明確"}})
        self.codex.respond.return_value = {"reply": json.dumps({"reply": "因為勝利畫面不明確。", "action": None})}
        result = self.request(message="為什麼不確定？")
        self.assertIn("勝利畫面不明確", self.codex.respond.call_args.args[0])
        self.assertNotIn("job_id", result)

    def test_retry_and_compatibility_route_use_same_dispatch(self):
        response = self.client.post("/api/projects/p/analyze", json={"start": 0, "end": 120, "model": "picked"})
        self.assertEqual(response.status_code, 202)
        first = response.json()
        self.store.patch("jobs", first["id"], status="failed")
        response = self.client.post(f'/api/jobs/{first["id"]}/retry')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["analysis"]["model"], "picked")

    def test_ordinary_chat_cannot_schedule_search_without_project(self):
        result = self.request(context=None)
        self.assertEqual(result["type"], "error")
        self.assertEqual(self.store.all("jobs"), [])

    def test_conversation_can_cancel_its_own_search(self):
        queued = self.request(intent="search", search_start=0, search_end=120)
        self.codex.respond.return_value = {"reply": json.dumps({"reply": "取消搜尋", "action": {
            "kind": "cancel_search", "start": None, "end": None, "victory": None,
            "postroll": None, "seconds": None}})}
        result = self.request(message="取消目前搜尋")
        self.assertIn("已取消", result["reply"])
        self.assertEqual(self.store.get("jobs", queued["job_id"])["status"], "cancelled")


    def test_full_vod_button_and_chat_accept_more_than_thirty_minutes(self):
        self.store.patch("projects", "p", duration=7200)
        first = self.request(intent="search", search_start=0, search_end=7200)
        self.assertEqual(self.store.get("jobs", first["job_id"])["analysis"]["end"], 7200)
        self.store.patch("jobs", first["job_id"], status="cancelled")
        self.action["end"] = 7200
        self.codex.respond.return_value = {"reply": json.dumps({"reply": "搜尋全片", "action": self.action})}
        second = self.request(message="搜尋全片")
        self.assertEqual(self.store.get("jobs", second["job_id"])["analysis"]["end"], 7200)
        self.assertIn("use the entire video", self.codex.respond.call_args.args[0])

    def test_continue_uncertain_preserves_original_model_effort_and_checkpoint(self):
        original = self.request(intent="search", search_start=0, search_end=120)
        original_id = original["job_id"]
        self.store.patch("jobs", original_id, status="succeeded", result={"status": "uncertain", "can_continue": True})
        checkpoint = self.store.root / "runs/web/p/codex" / original_id / "checkpoint.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text('{}')
        # Model defaults may change between calls; a continuation stays pinned.
        self.codex.models.return_value[0]["effort"] = "high"
        response = self.client.post(f"/api/jobs/{original_id}/retry")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["analysis"]["resume_from"], original_id)
        self.assertEqual(response.json()["analysis"]["effort"], "low")
        self.assertEqual(response.json()["analysis"]["model"], "picked")
        self.assertEqual(self.client.post(f"/api/jobs/{original_id}/retry").status_code, 409)


class ResetAnalysisTest(unittest.TestCase):
    setUp = DispatchTest.setUp
    tearDown = DispatchTest.tearDown
    request = DispatchTest.request

    def prepare_reset(self):
        draft = {"start": 20, "victory": 100, "postroll": 8, "reviewed": True, "revision": 4, "origin": "agent"}
        self.store.patch("projects", "p", draft=draft, source="downloads/source.mp4")
        self.store.put("projects", {"id": "other", "ready": True, "draft": draft, "duration": 300})
        self.store.put("jobs", {"id": "other-analysis", "project_id": "other", "kind": "analyze", "status": "succeeded"})
        self.store.put("jobs", {"id": "export", "project_id": "p", "kind": "export", "status": "succeeded", "draft": draft})
        root = self.store.root
        for relative in ("downloads/source.mp4", "clips/export.mp4", "runs/web/p/preview.mp4", "runs/web/p/thumb-001.jpg", "runs/web/other/codex/keep.json"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"keep")
        checkpoint = root / "runs/web/p/codex/old/checkpoint.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text('{}')
        return checkpoint

    def test_reset_cancels_work_and_clears_only_selected_project_analysis(self):
        checkpoint = self.prepare_reset()
        queued = self.request(intent="search", search_start=0, search_end=120)
        old_id = queued["job_id"]
        (self.store.root / f"runs/web/{old_id}.log").write_text('old log')
        response = self.client.post('/api/projects/p/reset-analysis')
        self.assertEqual(response.status_code, 200)
        project = response.json()["project"]
        self.assertEqual(project["analysis_generation"], 1)
        self.assertEqual(project["draft"]["revision"], 5)
        self.assertEqual(project["draft"]["origin"], "manual")
        self.assertFalse(project["draft"]["reviewed"])
        self.assertIsNone(self.store.get("jobs", old_id))
        self.assertFalse(checkpoint.exists())
        self.assertFalse((self.store.root / f"runs/web/{old_id}.log").exists())
        for relative in ("downloads/source.mp4", "clips/export.mp4", "runs/web/p/preview.mp4", "runs/web/p/thumb-001.jpg", "runs/web/other/codex/keep.json"):
            self.assertEqual((self.store.root / relative).read_bytes(), b"keep")
        self.assertIsNotNone(self.store.get("jobs", "export"))
        self.assertIsNotNone(self.store.get("jobs", "other-analysis"))
        self.assertEqual(self.client.post(f'/api/jobs/{old_id}/retry').status_code, 404)
        self.assertEqual(self.client.put('/api/projects/p/draft', json={"start": 20, "victory": 100, "postroll": 8, "reviewed": True, "revision": 4, "origin": "agent"}).status_code, 409)
        self.assertEqual(self.request(intent="search", search_start=0, search_end=120)["type"], "error")
        fresh = self.request(intent="search", search_start=0, search_end=300,
            context={"project_id": "p", "analysis_generation": 1, "draft": {"start": 0, "victory": 292, "postroll": 8}})
        self.assertNotIn("resume_from", self.store.get("jobs", fresh["job_id"])["analysis"])

    def test_late_chat_cannot_recreate_search_after_reset(self):
        self.prepare_reset()
        async def reset_during_response(*args, **kwargs):
            self.store.reset_analysis("p")
            return {"reply": json.dumps({"reply": "search", "action": self.action})}
        self.codex.respond.side_effect = reset_during_response
        result = self.request()
        self.assertEqual(result["type"], "error")
        self.assertIn("重置", result["detail"])
        self.assertFalse(any(j["project_id"] == "p" and j["kind"] == "analyze" for j in self.store.all("jobs")))


if __name__ == "__main__":
    unittest.main()
