"""Official Codex account RPCs and a bounded, text-only connection check.

Codex owns credentials. Never read auth.json, proxy private endpoints, or expose
raw CLI diagnostics (which can contain account information) to the browser.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading

from .codex_runtime import execute
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

MODEL = "gpt-5.6-luna"


class ConnectionError(RuntimeError):
    pass


class CodexConnection:
    def __init__(self, root: Path):
        self.root = root
        self.process = None
        self.reader = None
        self.pending: dict[int, asyncio.Future] = {}
        self.sequence = 0
        self.lock = asyncio.Lock()
        self.busy = asyncio.Lock()
        self.login: dict | None = None
        self.completed_login: dict | None = None

    async def start(self):
        async with self.lock:
            if self.process and self.process.returncode is None and self.reader and not self.reader.done():
                return
            await self.close()
            executable = shutil.which("codex")
            if not executable:
                raise ConnectionError("後端尚未安裝 Codex CLI，請先安裝官方 Codex CLI。")
            try:
                self.process = await asyncio.create_subprocess_exec(
                    executable, "app-server", "--listen", "stdio://",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
                )
                self.reader = asyncio.create_task(self.read())
                await self.rpc("initialize", {
                    "clientInfo": {"name": "bosscut", "title": "BossCut", "version": "0.1.0"},
                })
                await self.send({"method": "initialized", "params": {}})
            except (OSError, ConnectionError):
                await self.close()
                raise ConnectionError("Codex App Server 無法啟動，請更新官方 Codex CLI 後重試。") from None

    async def send(self, message: dict):
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            await self.process.stdin.drain()
        except (AttributeError, OSError):
            raise ConnectionError("Codex 連線已中斷，請重新整理連線狀態。") from None

    async def read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message and "id" in message:
                    # This client never supplies external tokens or approves tools.
                    await self.send({"id": message["id"], "error": {
                        "code": -32601, "message": "Unsupported client request",
                    }})
                elif "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(ConnectionError(
                                "Codex 拒絕此操作。請確認 CLI 版本、登入狀態與帳號設定後重試。"
                            ))
                        else:
                            future.set_result(message.get("result", {}))
                elif message.get("method") == "account/login/completed":
                    params = message.get("params", {})
                    self.completed_login = params
                    if self.login and params.get("loginId") == self.login.get("loginId"):
                        self.login = {
                            "status": "succeeded" if params.get("success") else "failed",
                        }
        except (ValueError, OSError):
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Codex 連線已中斷，請重新整理連線狀態。"))

    async def rpc(self, method: str, params: dict | None = None):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, 15)
        except TimeoutError:
            # A timed-out login RPC must not leave an invisible callback running.
            await self.close()
            raise ConnectionError("Codex 操作逾時，請稍後重試。") from None
        finally:
            self.pending.pop(request_id, None)

    async def status(self):
        try:
            await self.start()
            result = await self.rpc("account/read", {"refreshToken": False})
        except ConnectionError as error:
            return {"available": False, "model": MODEL, "detail": str(error), "login": None}
        account = result.get("account") or {}
        mode = account.get("type")
        available = mode in {"chatgpt", "apiKey"}
        return {
            "available": available, "model": MODEL, "auth_mode": mode,
            "email": account.get("email"), "plan": account.get("planType"),
            "detail": (
                "已登入 ChatGPT，使用訂閱中的 Codex 額度；模型存取權限須以回應測試確認。"
                if mode == "chatgpt" else
                "已使用 API Key 登入，會依 API 用量另外計費，不使用 ChatGPT 訂閱額度。"
                if mode == "apiKey" else "尚未連接 ChatGPT 帳號。"
            ),
            "login": self.login,
        }

    async def begin_login(self, method: str):
        async with self.busy:
            await self.start()
            if self.login and self.login.get("status") == "pending":
                return self.login
            result = await self.rpc("account/login/start", {"type": method})
            # Allow only official HTTPS login destinations returned by Codex.
            url = result.get("authUrl") or result.get("verificationUrl") or ""
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {
                "auth.openai.com", "chatgpt.com", "auth.chatgpt.com",
            } or parsed.username or parsed.password:
                await self.close()
                raise ConnectionError("Codex 未傳回支援的官方登入網址，請更新 CLI。")
            self.login = {"status": "pending", "loginId": result["loginId"], "url": url,
                          "userCode": result.get("userCode")}
            if self.completed_login and self.completed_login.get("loginId") == result["loginId"]:
                self.login = {"status": "succeeded" if self.completed_login.get("success") else "failed"}
            return self.login

    async def cancel_login(self):
        async with self.busy:
            if self.login and self.login.get("status") == "pending":
                await self.rpc("account/login/cancel", {"loginId": self.login["loginId"]})
            self.login = None
        return {"cancelled": True}

    async def models(self):
        await self.start()
        models = {}
        cursor = None
        seen = set()
        for _ in range(20):
            page = await self.rpc("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor})
            for item in page.get("data", []):
                if item.get("hidden") or "text" not in item.get("inputModalities", ["text"]):
                    continue
                model = item.get("model")
                if not isinstance(model, str) or not model:
                    continue
                models[model] = {
                    "id": model, "name": item.get("displayName") or model,
                    "description": item.get("description", ""),
                    "is_default": bool(item.get("isDefault")),
                    "effort": item.get("defaultReasoningEffort"),
                    "input_modalities": item.get("inputModalities", ["text"]),
                }
            cursor = page.get("nextCursor")
            if not cursor:
                return list(models.values())
            if cursor in seen:
                break
            seen.add(cursor)
        raise ConnectionError("無法完整取得模型清單，請重新整理。")

    async def probe(self):
        return await self.respond(
            "This is a text-only connection check. Do not use any tools, read files, "
            "or process media. Reply in Traditional Chinese with exactly: AI 連線成功。",
        )

    async def respond(self, prompt: str, *, model: str = MODEL,
                      schema: dict | None = None, effort: str | None = "low", timeout: int = 60):
        if self.busy.locked():
            raise ConnectionError("AI 連線操作進行中，請等候完成。")
        async with self.busy:
            status = await self.status()
            if not status["available"]:
                raise ConnectionError(status["detail"])
            if self.login and self.login.get("status") == "pending":
                raise ConnectionError("請先完成或取消登入，再測試回應。")
            work = self.root / "runs" / "web" / "ai-check"
            work.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=work) as directory:
                cancel = threading.Event()
                task = asyncio.create_task(asyncio.to_thread(
                    execute, Path(directory), [], prompt, timeout,
                    model=model, schema=schema, effort=effort, cancel=cancel,
                ))
                try:
                    result = await asyncio.shield(task)
                    return {**result, "auth_mode": status["auth_mode"]}
                except asyncio.CancelledError:
                    cancel.set()
                    # Do not remove temporary files before the child has stopped.
                    with suppress(Exception):
                        await asyncio.shield(task)
                    raise
                except (RuntimeError, OSError) as error:
                    raise ConnectionError(str(error) if isinstance(error, RuntimeError)
                                          else "無法啟動 Codex，請檢查 CLI 安裝。") from None

    async def close(self):
        if self.process and self.process.returncode is None:
            with suppress(ProcessLookupError):
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader:
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        self.process = self.reader = None
        self.login = None
        self.completed_login = None
