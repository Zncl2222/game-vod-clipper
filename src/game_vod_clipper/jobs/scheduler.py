"""Isolated background jobs, cancellation, and quota snapshots."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from uuid import uuid4

from ..codex.connection import MODEL, CodexConnection
from ..codex.usage import quota_change
from ..storage.store import Store

ACTIVE = {"queued", "running"}
logger = logging.getLogger(__name__)


class Jobs:
    def __init__(self, store: Store, codex: CodexConnection | None = None):
        self.store = store
        self.codex = codex
        self.limit = asyncio.Semaphore(1)
        # A long AI search must not occupy the download / export worker.
        self.analysis_limit = asyncio.Semaphore(1)
        self.tasks: dict[str, asyncio.Task] = {}

    def submit(
        self,
        project_id: str,
        kind: str,
        draft: dict | None = None,
        analysis: dict | None = None,
        source_job_id: str | None = None,
        export_quality: str | None = None,
    ) -> dict:
        job = {
            "id": uuid4().hex,
            "project_id": project_id,
            "kind": kind,
            "status": "queued",
            "stage": "等待處理",
            "progress": 0,
            "created": time.time(),
            "draft": draft,
            "analysis": analysis,
            "source_job_id": source_job_id,
            **({"export_quality": export_quality} if kind == "export" else {}),
            "model": analysis.get("model", MODEL) if analysis else None,
            "error": None,
        }
        self.store.put("jobs", job)
        task = asyncio.create_task(self.execute(job["id"]))
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return job

    async def execute(self, job_id: str):
        try:
            job = self.store.get("jobs", job_id)
            async with self.analysis_limit if job["kind"] == "analyze" else self.limit:
                job = self.store.get("jobs", job_id)
                before = None
                if job["kind"] == "analyze" and self.codex:
                    before = await self.codex.rate_limits()
                    self.store.patch("jobs", job_id, quota_before=before,
                                     quota_change={"status": "pending", "windows": []})
                try:
                    await self.run(job_id)
                finally:
                    if before is not None:
                        after = await self.codex.rate_limits()
                        self.store.patch("jobs", job_id, quota_after=after,
                                         quota_change=quota_change(before, after))
        except asyncio.CancelledError:
            # Cancellation during the trailing metadata read must not turn a
            # completed analysis into a cancelled result.
            current = self.store.get("jobs", job_id)
            if current and current["status"] in ACTIVE:
                self.store.patch("jobs", job_id, status="cancelled", stage="已取消", finished_at=time.time())
            if current and (current.get("quota_change") or {}).get("status") == "pending":
                self.store.patch("jobs", job_id, quota_change={"status": "unavailable", "windows": []})
        except Exception as exc:
            logger.exception("Job %s could not complete dispatch", job_id)
            current = self.store.get("jobs", job_id)
            if current and current["status"] in ACTIVE:
                self.store.patch("jobs", job_id, status="failed", error=str(exc), finished_at=time.time())
            if current and (current.get("quota_change") or {}).get("status") == "pending":
                self.store.patch("jobs", job_id, quota_change={"status": "unavailable", "windows": []})

    async def run(self, job_id: str):
        process = None
        log = self.store.root / "runs" / "web" / f"{job_id}.log"
        try:
            self.store.patch("jobs", job_id, status="running", started_at=time.time())
            with log.open("wb") as output:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "game_vod_clipper.web_worker",
                    str(self.store.root),
                    job_id,
                    stdout=output,
                    stderr=output,
                    start_new_session=os.name == "posix",
                )
                code = await process.wait()
            job = self.store.get("jobs", job_id)
            self.store.patch(
                "jobs", job_id, status="succeeded" if code == 0 else "failed",
                finished_at=time.time(), error=job.get("error")
                if code == 0 or job.get("error")
                else "處理失敗，請查看 runs/web/ 下的任務日誌。",
            )
        except asyncio.CancelledError:
            if process and process.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        killer = await asyncio.create_subprocess_exec(
                            "taskkill", "/PID", str(process.pid), "/T", "/F"
                        )
                        await killer.wait()
                except ProcessLookupError:
                    pass
                await process.wait()
            self.store.patch("jobs", job_id, status="cancelled", stage="已取消", finished_at=time.time())
        except Exception as exc:
            logger.exception("Media job %s failed", job_id)
            self.store.patch("jobs", job_id, status="failed", error=str(exc), finished_at=time.time())

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
