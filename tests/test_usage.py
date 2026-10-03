"""Accounting fixtures only: no model calls, account changes, or user media."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from game_vod_clipper.codex.connection import CodexConnection, ConnectionError
from game_vod_clipper.codex.usage import backfill_usage, quota_buckets, quota_change, record_usage, tokens, usage_summary
from game_vod_clipper.jobs.scheduler import Jobs
from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store


def snapshot(used=20, reset=200000, account="fixture", fetched=1000):
    return {"available": True, "fetched_at": fetched, "account_key": account, "buckets": [
        {"id": "codex", "name": "codex", "windows": [
            {"id": "secondary", "window_minutes": 10080, "used_percent": used, "resets_at": reset},
        ]},
    ]}


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def job(self, key, inputs, outputs, parent=None, **changes):
        usage = {"input_tokens": inputs, "output_tokens": outputs, "cached_input_tokens": inputs // 2}
        self.store.put("jobs", {"id": key, "kind": "analyze", "project_id": "p", "created": inputs,
                               "status": "succeeded", "model": "fixture", "analysis": {"resume_from": parent},
                               "usage": usage, "result": {"usage": usage}, **changes})

    def test_subsets_never_increase_total_and_invalid_counts_are_ignored(self):
        self.assertEqual(tokens({"input_tokens": 100, "output_tokens": 20,
                                 "cached_input_tokens": 70, "reasoning_output_tokens": 15})["total_tokens"], 120)
        self.assertEqual(tokens({"input_tokens": True, "output_tokens": -5,
                                 "reasoning_output_tokens": float("nan")})["total_tokens"], 0)

    def test_legacy_continuations_and_branches_import_only_their_own_increment(self):
        self.job("parent", 100, 20)
        self.job("child", 150, 35, "parent")
        self.job("branch", 170, 40, "parent")
        self.job("unchanged", 100, 20, "parent")
        backfill_usage(self.store)
        backfill_usage(self.store)
        result = usage_summary(self.store, "p")
        self.assertEqual(result["total"]["total_tokens"], 275)
        self.assertEqual(result["project"]["input_tokens"], 220)
        self.assertEqual(result["latest_analysis"]["tokens"]["total_tokens"], 90)
        # Parent deletion cannot cause inherited tokens to be re-imported.
        with self.store.connect() as db:
            db.execute("DELETE FROM jobs WHERE id='parent'")
        self.assertEqual(usage_summary(Store(self.root))["total"]["total_tokens"], 275)

    def test_new_ledger_is_not_duplicated_from_job_counters_and_survives_deletion(self):
        self.store.put("projects", {"id": "p", "duration": 100, "draft": {"revision": 0}})
        self.job("new", 100, 20, usage_tracked=True)
        for kind, project in (("analysis", "p"), ("chat", "p"), ("connection_test", None)):
            record_usage(self.store, {"input_tokens": 100, "output_tokens": 20}, kind=kind,
                         model="fixture", project_id=project, job_id="new" if kind == "analysis" else None)
        backfill_usage(self.store)
        self.assertEqual(usage_summary(self.store, "p")["project"]["total_tokens"], 240)
        self.store.reset_analysis("p")
        self.store.delete_project("p")
        self.assertEqual(usage_summary(Store(self.root))["total"]["total_tokens"], 360)

    def test_legacy_result_only_and_independent_searches_count_separately(self):
        self.job("one", 100, 20, usage=None)
        self.job("two", 100, 20)
        backfill_usage(self.store)
        self.assertEqual(usage_summary(self.store)["total"]["total_tokens"], 240)

    def test_routes_keep_local_usage_independent_of_unavailable_subscription(self):
        app = create_app(self.root)
        record_usage(app.state.store, {"input_tokens": 100}, kind="chat", model="fixture")
        app.state.codex.rate_limits = AsyncMock(return_value={"available": False, "detail": "未登入", "buckets": []})
        with TestClient(app) as client:
            response = client.get("/api/codex/usage")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.json()["total"]["total_tokens"], 100)
            self.assertFalse(client.get("/api/codex/rate-limits").json()["available"])
            self.assertEqual(client.get("/api/codex/usage?project_id=missing").status_code, 404)
            self.assertEqual(client.get("/api/codex/rate-limits", headers={"origin": "https://evil.test"}).status_code, 403)
            self.assertEqual(client.get("/api/state").json()["jobs"], [])

    def test_restart_does_not_leave_a_trailing_snapshot_loading_forever(self):
        self.job("done", 100, 20, quota_change={"status": "pending", "windows": []})
        app = create_app(self.root)
        with TestClient(app) as client:
            latest = client.get("/api/codex/usage").json()["latest_analysis"]
            self.assertEqual(latest["status"], "succeeded")
            self.assertEqual(latest["quota_change"]["status"], "unavailable")


class QuotaTest(unittest.TestCase):
    def test_multiple_buckets_preserve_actual_windows_and_strip_unrelated_fields(self):
        primary = {"usedPercent": 25.5, "windowDurationMins": 300, "resetsAt": 200000, "secret": "SECRET"}
        legacy = {"limitId": "codex", "primary": primary, "secondary": None, "credits": "SECRET"}
        result = quota_buckets({"rateLimits": legacy, "rateLimitsByLimitId": {
            "codex": {**legacy, "secondary": {**primary, "windowDurationMins": 10080}},
            "special": {"limitName": "Special", "primary": {**primary, "windowDurationMins": 60}},
        }})
        self.assertEqual(len(result), 2)
        self.assertEqual([w["window_minutes"] for w in result[0]["windows"]], [300, 10080])
        self.assertEqual(result[1]["windows"][0]["window_minutes"], 60)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(quota_buckets({"rateLimits": legacy})[0]["windows"][0]["used_percent"], 25.5)

    def test_missing_or_malformed_windows_do_not_become_zero_percent(self):
        for value in (None, {}, {"usedPercent": float("nan")}, {"usedPercent": True}, {"usedPercent": -1}):
            self.assertEqual(quota_buckets({"rateLimits": {"primary": value}}), [])
        self.assertIsNone(quota_buckets({"rateLimits": {"primary": {"usedPercent": 0}}})[0]["windows"][0]["window_minutes"])

    def test_delta_is_percentage_points_not_relative_growth(self):
        result = quota_change(snapshot(), snapshot(23))
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["windows"][0]["percentage_points"], 3)
        self.assertEqual(quota_change(snapshot(), snapshot())["windows"][0]["percentage_points"], 0)

    def test_resets_decreases_account_changes_and_missing_data_are_not_estimates(self):
        for after in (snapshot(2, reset=300000), snapshot(19), snapshot(21, fetched=200001)):
            result = quota_change(snapshot(), after)
            self.assertEqual(result["windows"][0]["status"], "reset")
            self.assertIsNone(result["windows"][0]["percentage_points"])
        self.assertEqual(quota_change(snapshot(), snapshot(account="other"))["status"], "account_changed")
        self.assertEqual(quota_change({"available": False}, snapshot())["status"], "unavailable")
        after = snapshot(23)
        after["buckets"][0]["windows"][0]["window_minutes"] = 300
        self.assertEqual(quota_change(snapshot(), after)["windows"][0]["status"], "unavailable")


class QuotaConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.connection = CodexConnection(self.root)

    async def asyncTearDown(self):
        await self.connection.close()
        self.temp.cleanup()

    async def test_official_read_only_rpc_and_graceful_unavailability(self):
        connection = self.connection
        connection.status = AsyncMock(return_value={"available": True, "auth_mode": "chatgpt", "email": "fixture@example.test", "plan": "plus"})
        connection.rpc = AsyncMock(return_value={"rateLimits": {"secondary": {
            "usedPercent": 25, "windowDurationMins": 10080, "resetsAt": 200000,
        }}})
        result = await connection.rate_limits()
        self.assertTrue(result["available"])
        self.assertNotIn("fixture@example.test", json.dumps(result))
        connection.rpc.assert_awaited_once_with("account/rateLimits/read")
        connection.rpc.side_effect = ConnectionError("SECRET DIAGNOSTIC")
        result = await connection.rate_limits()
        self.assertFalse(result["available"])
        self.assertNotIn("SECRET", json.dumps(result))
        for mode in ("apiKey", None):
            connection.rpc.reset_mock()
            connection.status.return_value = {"available": bool(mode), "auth_mode": mode, "detail": "未登入"}
            self.assertFalse((await connection.rate_limits())["available"])
            connection.rpc.assert_not_awaited()

    async def test_completed_usage_survives_a_later_reply_failure(self):
        self.connection.status = AsyncMock(return_value={"available": True, "auth_mode": "chatgpt"})
        def execute(*args, on_usage, **kwargs):
            on_usage({"input_tokens": 100, "output_tokens": 20})
            raise RuntimeError("fixture invalid response")
        with patch("game_vod_clipper.codex.connection.execute", side_effect=execute):
            with self.assertRaises(ConnectionError):
                await self.connection.respond("fixture", project_id="p")
        result = usage_summary(Store(self.root), "p")
        self.assertEqual(result["project"]["total_tokens"], 120)
        self.assertEqual(list((self.root / "runs/web/ai-check").iterdir()), [])

    async def test_job_snapshots_bracket_execution_inside_queue_and_survive_cancellation(self):
        store = self.connection.store
        store.put("jobs", {"id": "first", "project_id": "p", "kind": "analyze", "status": "queued"})
        store.put("jobs", {"id": "queued", "project_id": "p", "kind": "analyze", "status": "queued"})
        manager = Jobs(store, self.connection)
        self.connection.rate_limits = AsyncMock(side_effect=[snapshot(), snapshot(23)])
        entered = asyncio.Event()
        async def run(job_id):
            self.assertIsNotNone(store.get("jobs", job_id).get("quota_before"))
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                store.patch("jobs", job_id, status="cancelled")
        manager.run = run
        task = asyncio.create_task(manager.execute("first"))
        await asyncio.wait_for(entered.wait(), 2)
        queued = asyncio.create_task(manager.execute("queued"))
        await asyncio.sleep(0)
        queued.cancel()
        await queued
        self.assertEqual(self.connection.rate_limits.await_count, 1)
        task.cancel()
        await task
        first = store.get("jobs", "first")
        self.assertEqual(first["status"], "cancelled")
        self.assertEqual(first["quota_change"]["windows"][0]["percentage_points"], 3)
        self.assertNotIn("quota_before", store.get("jobs", "queued"))

    async def test_shutdown_during_trailing_quota_read_preserves_completed_result(self):
        store = self.connection.store
        store.put("jobs", {"id": "done", "project_id": "p", "kind": "analyze", "status": "queued"})
        manager = Jobs(store, self.connection)
        after_started = asyncio.Event()
        async def read():
            if store.get("jobs", "done")["status"] == "queued":
                return snapshot()
            after_started.set()
            await asyncio.Future()
        async def run(job_id):
            store.patch("jobs", job_id, status="succeeded", result={"status": "candidate"})
        self.connection.rate_limits = read
        manager.run = run
        task = asyncio.create_task(manager.execute("done"))
        await asyncio.wait_for(after_started.wait(), 2)
        task.cancel()
        await task
        self.assertEqual(store.get("jobs", "done")["status"], "succeeded")
        self.assertEqual(store.get("jobs", "done")["quota_change"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
