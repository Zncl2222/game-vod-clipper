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

    def test_selected_effort_reaches_search_and_retry_without_checkpoint(self):
        self.codex.models.return_value[0]["supported_efforts"] = ["low", "high"]
        first = self.request(intent="search", search_start=0, search_end=120, effort="high")
        job = self.store.get("jobs", first["job_id"])
        self.assertEqual(job["analysis"]["effort"], "high")
        self.store.patch("jobs", job["id"], status="failed")
        retry = self.client.post(f'/api/jobs/{job["id"]}/retry')
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.json()["analysis"]["effort"], "high")

    def test_youtube_auto_analysis_uses_visual_review_effort_without_changing_chat(self):
        selected = self.codex.models.return_value[0]
        selected.update(effort="medium", supported_efforts=["low", "medium", "high", "xhigh"])
        automatic = self.client.portal.call(self.app.state.youtube.analyze,
            self.store.get("projects", "p"), "picked", "youtube-import:p")
        self.assertEqual(automatic["analysis"]["effort"], "xhigh")
        self.assertEqual(automatic["analysis"]["effort_policy"], "adaptive")
        self.store.patch("jobs", automatic["id"], status="cancelled")
        explicit = self.request(intent="search", search_start=0, search_end=120, effort="low")
        self.assertEqual(self.store.get("jobs", explicit["job_id"])["analysis"]["effort"], "low")
        self.assertEqual(selected["effort"], "medium")

    def test_youtube_auto_analysis_only_uses_supported_efforts(self):
        selected = self.codex.models.return_value[0]
        for supported, expected in ((["medium", "high"], "high"), (["medium"], "medium"), ([], "medium")):
            with self.subTest(supported=supported):
                selected.update(effort="medium", supported_efforts=supported)
                automatic = self.client.portal.call(self.app.state.youtube.analyze,
                    self.store.get("projects", "p"), "picked", "auto:" + expected + str(supported))
                self.store.patch("jobs", automatic["id"], status="cancelled")
                self.assertEqual(automatic["analysis"]["effort"], expected)

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

    def test_ordinary_chat_with_a_selected_project_does_not_schedule_work(self):
        self.codex.respond.return_value = {"reply": json.dumps({"reply": "這裡有三個直播標題。", "action": None})}
        for draft in ({"start": 10, "victory": 100, "postroll": 8}, None,
                      {"start": 100, "victory": 10, "postroll": 8}):
            with self.subTest(draft=draft):
                result = self.request(message="幫我想三個直播標題", context={"project_id": "p", "draft": draft})
                self.assertEqual(result["type"], "reply")
                self.assertIsNone(result["action"])
                self.assertNotIn("job_id", result)
                self.assertEqual(self.store.all("jobs"), [])

    def test_search_tools_work_while_the_current_draft_is_incomplete(self):
        for options in ({"intent": "search", "search_start": 0, "search_end": 120}, {}):
            with self.subTest(options=options):
                result = self.request(context={"project_id": "p", "draft": None}, **options)
                self.assertEqual(result["type"], "reply")
                self.assertEqual(self.store.get("jobs", result["job_id"])["analysis"]["end"], 120)
                self.store.patch("jobs", result["job_id"], status="cancelled")

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

    def test_progress_reset_preserves_edits_candidates_exports_and_other_projects(self):
        checkpoint = self.prepare_reset()
        draft = self.store.get("projects", "p")["draft"]
        queued = self.request(intent="search", search_start=0, search_end=120, request_id="original")
        old_id = queued["job_id"]
        candidate = {"id": f"{old_id}:c1", "start": 20, "end": 108, "victory": 100,
                     "kind": "possible_win", "confidence": "low", "boss": "Boss", "summary": "待核對",
                     "warnings": [], "evidence": [{"time": 100, "event": "勝利文字"}]}
        self.store.patch("jobs", old_id, candidates=[candidate], resumable=True,
                         coverage=[{"start": 0, "end": 120, "every": 5}])
        self.store.set_candidate_review("p", candidate["id"], "keep", 0)
        before = self.client.get("/api/state").json()
        log = self.store.root / f"runs/web/{old_id}.log"
        log.write_text("old log")

        response = self.client.post('/api/projects/p/reset-analysis-progress')
        self.assertEqual(response.status_code, 200)
        project = response.json()["project"]
        self.assertEqual(project["draft"], draft)
        self.assertEqual(project["analysis_generation"], 1)
        self.assertEqual(project["editor_generation"], 0)
        self.assertEqual(project["candidate_reviews"], {candidate["id"]: "keep"})
        old_project = next(p for p in before["projects"] if p["id"] == "p")
        self.assertEqual(project["review_candidates"], old_project["review_candidates"])
        old_job = self.store.get("jobs", old_id)
        self.assertEqual(old_job["status"], "cancelled")
        self.assertTrue(old_job["progress_reset"])
        self.assertFalse(old_job["resumable"])
        self.assertEqual(old_job["coverage"], [])
        self.assertEqual(old_job["candidates"], [candidate])
        self.assertFalse(checkpoint.exists())
        self.assertFalse(log.exists())
        self.assertEqual(self.client.post(f'/api/jobs/{old_id}/retry').status_code, 409)
        for relative in ("downloads/source.mp4", "clips/export.mp4", "runs/web/p/preview.mp4", "runs/web/p/thumb-001.jpg", "runs/web/other/codex/keep.json"):
            self.assertEqual((self.store.root / relative).read_bytes(), b"keep")
        after = self.client.get("/api/state").json()
        self.assertEqual(next(p for p in after["projects"] if p["id"] == "p"), project)
        for job_id in ("export", "other-analysis"):
            self.assertEqual(next(j for j in before["jobs"] if j["id"] == job_id),
                             next(j for j in after["jobs"] if j["id"] == job_id))
        self.assertEqual(self.request(intent="search", search_start=0, search_end=120)["type"], "error")
        fresh = self.request(intent="search", search_start=0, search_end=300, request_id="original",
            context={"project_id": "p", "analysis_generation": 1,
                     "draft": {k: draft[k] for k in ("start", "victory", "postroll")}})
        self.assertNotEqual(fresh["job_id"], old_id)
        self.assertNotIn("resume_from", self.store.get("jobs", fresh["job_id"])["analysis"])

    def test_completed_progress_reset_hides_previous_search_from_chat(self):
        self.prepare_reset()
        self.store.put("jobs", {"id": "completed", "project_id": "p", "kind": "analyze", "status": "succeeded",
            "result": {"status": "uncertain", "can_continue": True, "summary": "OLD_PROGRESS_SENTINEL",
                       "coverage": [{"start": 0, "end": 120, "every": 5}]}})
        self.assertEqual(self.client.post('/api/projects/p/reset-analysis-progress').status_code, 200)
        old = self.store.get("jobs", "completed")
        self.assertFalse(old["result"]["can_continue"])
        self.assertEqual(old["result"]["coverage"], [])
        self.assertEqual(self.client.post('/api/jobs/completed/retry').status_code, 409)
        self.codex.respond.return_value = {"reply": json.dumps({"reply": "可以重新搜尋", "action": None})}
        result = self.request(message="現在進度如何？", context={"project_id": "p", "analysis_generation": 1,
            "draft": {"start": 20, "victory": 100, "postroll": 8}})
        self.assertEqual(result["type"], "reply")
        self.assertNotIn("OLD_PROGRESS_SENTINEL", self.codex.respond.call_args.args[0])
        # Repeated progress resets keep editing state; a full reset still clears it.
        self.assertEqual(self.client.post('/api/projects/p/reset-analysis-progress').json()["project"]["editor_generation"], 0)
        project = self.client.post('/api/projects/p/reset-analysis').json()["project"]
        self.assertEqual(project["analysis_generation"], 3)
        self.assertEqual(project["editor_generation"], 1)
        self.assertIsNone(self.store.get("jobs", "completed"))
        self.assertEqual(project["draft"]["start"], 0)

    def test_progress_reset_rejects_late_search_and_failed_cleanup_is_retryable(self):
        self.prepare_reset()
        queued = self.request(intent="search", search_start=0, search_end=120)
        with patch("game_vod_clipper.web.shutil.rmtree", side_effect=OSError("busy")):
            response = self.client.post('/api/projects/p/reset-analysis-progress')
        self.assertEqual(response.status_code, 500)
        self.assertFalse(self.store.get("jobs", queued["job_id"]).get("progress_reset"))
        self.assertEqual(self.store.get("projects", "p").get("analysis_generation", 0), 0)
        async def reset_during_response(*args, **kwargs):
            self.store.reset_analysis("p", progress_only=True)
            return {"reply": json.dumps({"reply": "search", "action": self.action})}
        self.codex.respond.side_effect = reset_during_response
        result = self.request()
        self.assertEqual(result["type"], "error")
        self.assertIn("重置", result["detail"])
        self.assertEqual(self.client.post('/api/projects/p/reset-analysis-progress').status_code, 200)
        self.assertFalse(any(j["project_id"] == "p" and j["status"] in {"queued", "running"} for j in self.store.all("jobs")))


if __name__ == "__main__":
    unittest.main()
