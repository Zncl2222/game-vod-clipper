"""System HTTP routes and request operations."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .context import WorkspaceDep

router = APIRouter()


@router.get("/api/health")
def health(ctx: WorkspaceDep):
    """Local readiness only; never start Codex or contact an external API."""
    if ctx.shutting_down.is_set():
        raise HTTPException(503, "Service is shutting down")
    try:
        with ctx.store.connect() as db:
            db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
    except sqlite3.Error:
        raise HTTPException(503, "Workspace database is unavailable") from None
    return {"status": "ok"}


@router.get("/api/state")
async def read_state(ctx: WorkspaceDep):
    return ctx.state()


@router.get("/api/events")
async def events(ctx: WorkspaceDep, request: Request):
    async def stream():
        previous = ""
        while not ctx.shutting_down.is_set() and not await request.is_disconnected():
            current = json.dumps(ctx.state(), ensure_ascii=False)
            yield (
                f"data: {current}\n\n" if current != previous else ": heartbeat\n\n"
            )
            previous = current
            try:
                await asyncio.wait_for(ctx.shutting_down.wait(), timeout=1)
            except TimeoutError:
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
