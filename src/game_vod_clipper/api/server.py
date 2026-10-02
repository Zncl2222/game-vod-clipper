"""Local media responses and graceful server shutdown."""

from __future__ import annotations

import asyncio
import re

import anyio
import uvicorn
from fastapi.responses import FileResponse

PREVIEW_RANGE_LIMIT = 8 * 1024 * 1024
OPEN_RANGE = re.compile(r"\s*bytes\s*=\s*(\d+)\s*-\s*")


class LocalFileResponse(FileResponse):
    def __init__(self, *args, range_limit: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.range_limit = range_limit

    async def __call__(self, scope, receive, send):
        scope["game_vod_clipper.file_response"] = True
        if self.range_limit:
            # Players open with "bytes=0-" and re-request as they need more.
            # Answering that with the whole multi-GB file lets proxies (e.g.
            # VS Code port forwarding) buffer it all in memory while paused.
            headers = []
            for key, value in scope["headers"]:
                match = key == b"range" and OPEN_RANGE.fullmatch(value.decode("latin-1"))
                if match:
                    start = int(match[1])
                    value = f"bytes={start}-{start + self.range_limit - 1}".encode()
                headers.append((key, value))
            scope["headers"] = headers

        async def disconnected():
            while True:
                if (await receive())["type"] == "http.disconnect":
                    group.cancel_scope.cancel()
                    return

        # Stop disk reads when a player disconnects or the server closes its
        # transport. FileResponse otherwise keeps reading the entire file.
        async with anyio.create_task_group() as group:
            group.start_soon(disconnected)
            await super().__call__(scope, receive, send)
            group.cancel_scope.cancel()


class LocalServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, shutdown_event: asyncio.Event):
        super().__init__(config)
        self.shutdown_event = shutdown_event

    async def shutdown(self, sockets=None):
        # Uvicorn drains HTTP requests BEFORE sending lifespan.shutdown. Notify
        # our persistent streams here so they can finish before that drain.
        self.shutdown_event.set()
        for connection in list(self.server_state.connections):
            if getattr(connection, "scope", {}).get("game_vod_clipper.file_response"):
                # A paused player may never drain a large Range response. Closing
                # with buffered bytes would still wait; abort releases it now and
                # LocalFileResponse's disconnect listener stops the file reader.
                connection.transport.abort()
        await super().shutdown(sockets=sockets)
