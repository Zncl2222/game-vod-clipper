"""Per-application resources shared by HTTP routes; never process-global state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request

from ..analysis.candidates import project_candidates
from ..analysis.game_profiles import GameProfiles
from ..codex.connection import CodexConnection
from ..jobs.scheduler import ACTIVE, Jobs
from ..storage.locations import Locations, media_path
from ..storage.store import Store

if TYPE_CHECKING:
    from ..youtube.routes import YouTubeWorkspace


def public_project(project):
    return {k: v for k, v in project.items() if k not in {"source", "url", "work"}}


def published(upload: dict):
    # Safe to drop the local MP4 only once YouTube holds the video and any
    # requested playlist placement has been confirmed.
    return upload["status"] == "succeeded" and (not upload.get("playlist_id") or upload.get("playlist_status") == "added")


@dataclass
class Workspace:
    root: Path
    store: Store
    locations: Locations
    profiles: GameProfiles
    codex: CodexConnection
    jobs: Jobs
    analysis_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    deleting_projects: set[str] = field(default_factory=set)
    shutting_down: asyncio.Event = field(default_factory=asyncio.Event)
    youtube: YouTubeWorkspace = field(init=False)

    def get(self, table: str, key: str):
        if table == "projects" and key in self.deleting_projects:
            raise HTTPException(409, "專案正在刪除，請稍候。")
        result = self.store.get(table, key)
        if result is None:
            raise HTTPException(404, "找不到項目。")
        return result

    def public_job(self, job):
        public = {k: v for k, v in job.items() if k != "output"}
        if job.get("output"):
            public["output_path"] = str(media_path(self.root, job["output"]))
        return public

    def clip_uploads(self):
        result = {}
        for upload in self.youtube.uploads.all().values():
            current = result.get(upload.get("export_id"))
            if not current or (published(upload), upload.get("created", 0)) > (published(current), current.get("created", 0)):
                result[upload.get("export_id")] = upload
        return {key: {"status": item["status"], "video_id": item.get("video_id"), "playlist_title": item.get("playlist_title"),
                      "playlist_status": item.get("playlist_status"), "published": published(item)}
                for key, item in result.items()}

    def state(self):
        all_jobs = self.store.all("jobs")
        uploads = self.clip_uploads()
        return {
            "projects": [public_project(p) | {"review_candidates": project_candidates(p, all_jobs)} for p in self.store.all("projects")],
            "jobs": [self.public_job(j) | ({"youtube_upload": uploads[j["id"]]} if j["id"] in uploads else {}) for j in all_jobs],
        }

    async def cancel_job(self, job_id: str):
        job = self.get("jobs", job_id)
        task = self.jobs.tasks.get(job_id)
        if task and job["status"] in ACTIVE:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first instruction never enters execute().
            if self.store.get("jobs", job_id) is not None:
                self.store.patch("jobs", job_id, status="cancelled", stage="已取消")
        return self.public_job(self.get("jobs", job_id))


async def get_workspace(request: Request) -> Workspace:
    return request.app.state.workspace


WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]
