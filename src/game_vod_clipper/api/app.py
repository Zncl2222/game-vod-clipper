"""Create the local HTTP application and wire its shared resources."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..analysis.game_profiles import GameProfiles, ProfileError
from ..codex.connection import CodexConnection, ConnectionError
from ..jobs.scheduler import ACTIVE, Jobs
from ..storage.locations import Locations
from ..storage.store import Store
from ..youtube.routes import YouTubeWorkspace
from . import analysis, clips, jobs, media, profiles, projects, storage, system
from .context import Workspace
from .youtube import youtube_analyze, youtube_check_model, youtube_import


def http_origin(value: str):
    """Compare browser origins including scheme and effective port, not just host."""
    try:
        parsed = urlparse(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or Path(os.environ.get("GAME_VOD_ROOT", "."))).resolve()
    store = Store(root)
    codex = CodexConnection(root, store)
    ctx = Workspace(root, store, Locations(root), GameProfiles(root), codex, Jobs(store, codex))
    ctx.youtube = YouTubeWorkspace(
        store, partial(youtube_import, ctx), partial(youtube_analyze, ctx), partial(youtube_check_model, ctx))

    @asynccontextmanager
    async def lifespan(app):
        ctx.shutting_down.clear()
        for job in ctx.store.all("jobs"):
            if job["status"] in ACTIVE:
                ctx.store.patch(
                    "jobs", job["id"], status="interrupted", stage="服務重啟，請重試", finished_at=time.time()
                )
            if (job.get("quota_change") or {}).get("status") == "pending":
                ctx.store.patch("jobs", job["id"], quota_change={"status": "unavailable", "windows": []})
        ctx.youtube.start()
        try:
            yield
        finally:
            ctx.shutting_down.set()
            await ctx.youtube.close()
            await ctx.jobs.close()
            await ctx.codex.close()

    app = FastAPI(title="BossCut local POC", lifespan=lifespan)
    app.state.workspace = ctx
    app.state.store = ctx.store
    app.state.jobs = ctx.jobs
    app.state.codex = ctx.codex
    app.state.shutting_down = ctx.shutting_down
    app.state.youtube = ctx.youtube

    @app.exception_handler(ConnectionError)
    async def codex_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(ProfileError)
    async def profile_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    hosts = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    hosts += [h for h in os.environ.get("GAME_VOD_ALLOWED_HOSTS", "").split(",") if h]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        oauth_callback = request.method == "GET" and request.url.path == "/api/youtube/callback"
        source_origin = http_origin(origin) if origin else None
        if origin and (source_origin is None or source_origin != http_origin(str(request.base_url))) and not oauth_callback:
            return JSONResponse(
                {"detail": "不允許此來源存取本機工作區。"}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site" and not oauth_callback:
            return JSONResponse({"detail": "不允許跨站存取。"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    for routes in (system, profiles, storage, analysis, projects, clips, jobs, media):
        app.include_router(routes.router)
    ctx.youtube.mount(app)

    @app.websocket("/{path:path}")
    async def reject_websocket(websocket: WebSocket):
        await websocket.close(code=1008)

    frontend = Path(__file__).resolve().parents[3] / "web" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app
