"""Connection-only tests: no FFmpeg, downloads, user media, or live AI calls."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from game_vod_clipper.codex_connection import CodexConnection, ConnectionError, MODEL
from game_vod_clipper.web import create_app


class ConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.connection = CodexConnection(Path(self.temp.name))

    async def asyncTearDown(self):
        await self.connection.close()
        self.temp.cleanup()

    async def test_missing_cli_is_not_ready(self):
        with patch("game_vod_clipper.codex_connection.shutil.which", return_value=None):
            self.assertFalse((await self.connection.status())["available"])

    async def test_account_modes_and_no_credentials_exposed(self):
        self.connection.start = AsyncMock()
        for mode in ("chatgpt", "apiKey", None, "amazonBedrock"):
            self.connection.rpc = AsyncMock(return_value={"account": {
                "type": mode, "email": "test@example.com", "planType": "plus",
                "accessToken": "SECRET",
            }})
            result = await self.connection.status()
            self.assertEqual(result["available"], mode in {"chatgpt", "apiKey"})
            self.assertNotIn("SECRET", json.dumps(result))
            if mode == "apiKey":
                self.assertIn("另外計費", result["detail"])

    async def test_login_is_reused_and_cancelled(self):
        self.connection.start = AsyncMock()
        self.connection.rpc = AsyncMock(return_value={
            "loginId": "login-1", "verificationUrl": "https://auth.openai.com/codex/device",
            "userCode": "ABCD-1234",
        })
        first = await self.connection.begin_login("chatgptDeviceCode")
        self.assertEqual(first, await self.connection.begin_login("chatgptDeviceCode"))
        self.assertEqual(self.connection.rpc.await_count, 1)
        await self.connection.cancel_login()
        self.connection.rpc.assert_awaited_with("account/login/cancel", {"loginId": "login-1"})
        self.assertIsNone(self.connection.login)

    async def test_untrusted_login_url_rejected(self):
        self.connection.start = AsyncMock()
        for url in ("http://auth.openai.com/login", "https://auth.openai.com.evil.test/", "javascript:alert(1)"):
            self.connection.rpc = AsyncMock(return_value={"loginId": "1", "authUrl": url})
            with self.assertRaises(ConnectionError):
                await self.connection.begin_login("chatgpt")

    async def test_early_login_notification_is_not_lost(self):
        self.connection.start = AsyncMock()
        self.connection.completed_login = {"loginId": "1", "success": True}
        self.connection.rpc = AsyncMock(return_value={
            "loginId": "1", "authUrl": "https://auth.openai.com/authorize",
        })
        self.assertEqual((await self.connection.begin_login("chatgpt"))["status"], "succeeded")

    async def test_probe_refuses_signed_out_and_concurrent_requests(self):
        self.connection.status = AsyncMock(return_value={"available": False, "detail": "未登入"})
        with patch("asyncio.create_subprocess_exec") as launch:
            with self.assertRaises(ConnectionError):
                await self.connection.probe()
            async with self.connection.busy:
                with self.assertRaises(ConnectionError):
                    await self.connection.probe()
            launch.assert_not_called()

    async def test_probe_uses_shared_executor_and_removes_temporary_files(self):
        self.connection.status = AsyncMock(return_value={"available": True, "auth_mode": "chatgpt"})
        def execute(work, images, prompt, timeout, **kwargs):
            self.assertEqual(images, [])
            self.assertEqual(kwargs["model"], MODEL)
            (work / "response.json").write_text("AI 連線成功。", encoding="utf-8")
            return {"reply": "AI 連線成功。", "model": MODEL, "usage": {}}
        with patch("game_vod_clipper.codex_connection.execute", side_effect=execute):
            result = await self.connection.probe()
        self.assertEqual(result["reply"], "AI 連線成功。")
        self.assertEqual(list((Path(self.temp.name) / "runs/web/ai-check").iterdir()), [])

    async def test_probe_failure_does_not_fabricate_reply(self):
        self.connection.status = AsyncMock(return_value={"available": True, "auth_mode": "chatgpt"})
        with patch("game_vod_clipper.codex_connection.execute", side_effect=RuntimeError("模型呼叫失敗")):
            with self.assertRaises(ConnectionError):
                await self.connection.probe()

    async def test_probe_timeout_is_reported(self):
        self.connection.status = AsyncMock(return_value={"available": True, "auth_mode": "chatgpt"})
        with patch("game_vod_clipper.codex_connection.execute", side_effect=RuntimeError("AI 回應超過 60 秒，已停止")):
            with self.assertRaisesRegex(ConnectionError, "60 秒"):
                await self.connection.probe()

    async def test_login_completion_clears_code_and_url(self):
        connection = self.connection
        connection.login = {"status": "pending", "loginId": "1", "userCode": "SECRET-CODE"}
        process = Mock()
        process.returncode = 0
        process.stdout = asyncio.StreamReader()
        connection.process = process
        process.stdout.feed_data(b'{"method":"account/login/completed","params":{"loginId":"1","success":true}}\n')
        process.stdout.feed_eof()
        await connection.read()
        self.assertEqual(connection.login, {"status": "succeeded"})

    async def test_rpc_correlates_response_and_rejects_server_requests(self):
        connection = self.connection
        connection.send = AsyncMock()
        process = AsyncMock()
        process.returncode = 0
        process.stdout = asyncio.StreamReader()
        connection.process = process
        task = asyncio.create_task(connection.rpc("account/read"))
        await asyncio.sleep(0)
        process.stdout.feed_data(b'{"method":"unexpected/tool","id":99}\n')
        process.stdout.feed_data(b'{"id":1,"result":{"account":null}}\n')
        process.stdout.feed_eof()
        await connection.read()
        self.assertEqual(await task, {"account": None})
        self.assertEqual(connection.send.call_args.args[0]["error"]["code"], -32601)


class ConnectionRoutesTest(unittest.TestCase):
    def test_routes_do_not_create_media_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory))
            connection = app.state.codex
            connection.status = AsyncMock(return_value={"available": True})
            connection.probe = AsyncMock(return_value={"reply": "AI 連線成功。"})
            connection.begin_login = AsyncMock(return_value={"status": "pending"})
            connection.cancel_login = AsyncMock(return_value={"cancelled": True})
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/codex").status_code, 200)
                self.assertEqual(client.post("/api/codex/login", json={}).status_code, 200)
                self.assertEqual(client.post("/api/codex/login/cancel").status_code, 200)
                self.assertEqual(client.post("/api/codex/test").json()["reply"], "AI 連線成功。")
                self.assertEqual(client.get("/api/state").json()["jobs"], [])
                self.assertEqual(client.post("/api/codex/login", json={"method": "apiKey"}).status_code, 422)
                self.assertEqual(client.post("/api/codex/test", headers={"origin": "https://evil.test"}).status_code, 403)
                connection.probe = AsyncMock(side_effect=ConnectionError("尚未登入"))
                self.assertEqual(client.post("/api/codex/test").status_code, 503)


if __name__ == "__main__":
    unittest.main()
