"""Call Codex with the observation schema and bounded retry policy."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from ..codex.runtime import CodexCallError, execute
from .models import Observation

MODEL = "gpt-5.6-luna"
MODEL_RETRY_DELAYS = (10, 30)
MODEL_CALL_TIMEOUT = 180  # A stalled provider call must not hold a job forever.


def invoke_codex(
    work: Path, images: list[Path], prompt: str, timeout: float | None,
    *, on_event: Callable[[dict], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
    model: str = MODEL, effort: str | None = "medium",
) -> tuple[dict, dict]:
    deadline = time.monotonic() + timeout if timeout is not None else None
    schema = Observation.model_json_schema()
    schema["required"].append("suspicious_windows")
    schema["required"].append("candidates")
    schema["required"].append("review_complete")
    schema["required"].append("entry_status")
    schema["required"].append("outcome")
    schema["$defs"]["CandidateSegment"]["required"].append("replaces")
    schema["$defs"]["CandidateSegment"]["properties"]["replaces"].pop("default", None)
    for field in ("suspicious_windows", "candidates", "review_complete", "entry_status", "outcome"):
        schema["properties"][field].pop("default", None)
    for attempt in range(len(MODEL_RETRY_DELAYS) + 1):
        # Keep every failed attempt's diagnostics. Reuse extracted images and
        # exactly the same model/effort; connection probes and chat do not retry.
        attempt_work = work if attempt == 0 else work / f"retry-{attempt}"
        try:
            remaining = max(.001, deadline - time.monotonic()) if deadline is not None else None
            result = execute(attempt_work, images, prompt, remaining, model=model,
                             schema=schema, effort=effort, on_event=on_event, on_usage=on_usage)
        except CodexCallError as exc:
            if not exc.retryable or attempt == len(MODEL_RETRY_DELAYS):
                message = str(exc) + (f" 已重試 {attempt} 次仍未恢復。" if attempt else "")
                raise CodexCallError(message + " 已保留分析進度，可稍後接續。",
                                     kind=exc.kind, retryable=exc.retryable) from exc
            delay = MODEL_RETRY_DELAYS[attempt]
            if deadline is not None and deadline - time.monotonic() <= delay:
                raise CodexCallError(str(exc) + " 本輪等待額度已用完，已保留進度，可稍後接續。",
                                     kind=exc.kind, retryable=exc.retryable) from exc
            if on_event:
                on_event({"type": "analysis.retry", "message":
                    f"{exc} {delay} 秒後重試本輪（{attempt + 1}/{len(MODEL_RETRY_DELAYS)}），已完成的判讀會保留。"})
            time.sleep(delay)
            continue
        if attempt:
            (work / "response.json").write_text(result["reply"], encoding="utf-8")
        return json.loads(result["reply"]), result["usage"]
