"""Persist analysis activity and liveness independently of model output."""

from __future__ import annotations

import threading
import time

from ..storage.store import Store

HEARTBEAT_INTERVAL = 5


class AnalysisProgress:
    """Persist real activity separately from the worker's liveness heartbeat."""

    def __init__(self, store: Store, job_id: str):
        self.store, self.job_id = store, job_id
        self.activity: list[dict] = []
        self.round_effort = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)

    def __enter__(self):
        self.report("starting", "正在準備分析", frames=0, rounds=0)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()

    def heartbeat(self):
        while not self.stop.wait(HEARTBEAT_INTERVAL):
            self.store.patch("jobs", self.job_id, heartbeat_at=time.time())

    def report(self, phase: str, message: str, **fields):
        self.round_effort = fields.get("round_effort", self.round_effort)
        now = time.time()
        if not self.activity or self.activity[-1]["message"] != message:
            self.activity = (self.activity + [{"time": now, "message": message}])[-12:]
        self.store.patch(
            "jobs", self.job_id, phase=phase, stage=message,
            heartbeat_at=now, last_activity_at=now, activity=self.activity, **fields,
        )

    def codex_event(self, event: dict):
        kind = event.get("type")
        message = {
            "thread.started": "Codex 已啟動，等待模型回應",
            "turn.started": "Codex 已開始本輪判讀",
            "turn.completed": "Codex 已完成本輪回應",
            "turn.failed": "Codex 回報本輪失敗",
            "error": "Codex 回報連線或執行問題",
        }.get(kind)
        if kind == "analysis.retry":
            message = event["message"]
        item = event.get("item")
        if kind in {"item.started", "item.updated", "item.completed"} and isinstance(item, dict):
            # Show activity categories, never raw reasoning, commands, or model text.
            message = {
                "reasoning": "Codex 正在判讀抽樣畫面",
                "agent_message": "Codex 正在整理判讀結果",
                "command_execution": "Codex 回報工具執行活動",
                "mcp_tool_call": "Codex 回報工具執行活動",
                "web_search": "Codex 回報搜尋活動",
                "plan": "Codex 正在更新分析步驟",
            }.get(item.get("type"), "收到 Codex 活動更新")
        if message:
            if self.round_effort:
                message += f"（{self.round_effort}）"
            self.report("analyzing", message)
