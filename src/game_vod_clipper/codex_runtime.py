"""Single Codex CLI executor for conversation and visual search.

All consumers share credentials, isolation, cancellation and structured output.
Python owns media operations; Codex receives only supplied text and images.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

def execute(
    work: Path, images: list[Path], prompt: str, timeout: float,
    *, model: str, schema: dict | None = None, effort: str | None = None,
    on_event: Callable[[dict], None] | None = None,
    cancel: threading.Event | None = None,
) -> dict:
    if cancel and cancel.is_set():
        raise RuntimeError("AI 工作已取消。")
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError(
            "找不到 Codex CLI。請在執行後端的環境安裝 Codex 並執行 codex login。"
        )
    work.mkdir(parents=True, exist_ok=True)
    schema_path = work / "schema.json"
    if schema:
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
    result_file = work / "response.json"
    result_file.unlink(missing_ok=True)
    args = [
        codex,
        "exec",
        "--ignore-user-config",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "--ephemeral",
        "--skip-git-repo-check",
        "--cd",
        str(work),
        "--json",
        "-o",
        str(result_file),
    ]
    for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins",
                    "hooks", "browser_use", "computer_use", "image_generation"):
        args += ["--disable", feature]
    args += ["-c", 'web_search="disabled"']
    if effort:
        args += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
    if schema:
        args += ["--output-schema", str(schema_path)]
    for picture in images:
        args += ["--image", str(picture)]
    args += ["--", "-"]
    usage = {}
    errors = []

    def consume(line: bytes):
        nonlocal usage
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "turn.completed":
            usage = event.get("usage", {})
        if event.get("type") in {"error", "turn.failed"}:
            errors.append(str(event.get("message") or event.get("error")))
        if on_event:
            on_event(event)

    # File-backed streams avoid blocked pipes (including a large stdin prompt),
    # preserve partial logs on failure, and work on Windows as well as POSIX.
    event_path = work / "events.jsonl"
    diagnostic_path = work / "diagnostics.log"
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=work) as prompt_input,
        event_path.open("wb") as output,
        diagnostic_path.open("wb") as diagnostics,
        event_path.open("rb") as events,
    ):
        prompt_input.write(prompt)
        prompt_input.seek(0)
        with subprocess.Popen(args, stdin=prompt_input, stdout=output, stderr=diagnostics) as process:
            deadline = time.monotonic() + timeout
            pending = b""
            try:
                while True:
                    code = process.poll()
                    pending += events.read()
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        consume(line)
                    if code is not None:
                        if pending:
                            consume(pending)
                        break
                    if cancel and cancel.is_set():
                        raise RuntimeError("AI 工作已取消。")
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            f"Codex 本輪超過 {timeout:.0f} 秒仍未完成，已停止。請重試或縮小分析範圍。"
                        )
                    time.sleep(0.2)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
    if code or errors or not result_file.is_file():
        raise RuntimeError(
            f"Codex ({model}) 呼叫失敗。請檢查登入、模型權限、額度與網路；不會自動切換模型或計費方式。"
        )
    if result_file.stat().st_size > 100_000:
        raise RuntimeError("AI 回應過長，請縮小問題範圍。")
    reply = result_file.read_text(encoding="utf-8").strip()
    if not reply:
        raise RuntimeError("Codex 傳回空白回應，請重試。")
    return {"reply": reply, "model": model, "usage": usage}
