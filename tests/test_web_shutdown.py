"""Real HTTP streams and process signals, without FFmpeg, user video or AI."""

import http.client
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from game_vod_clipper.web import create_app
from game_vod_clipper.web_store import Store


class WebSocketRoutingTest(unittest.TestCase):
    def test_unsupported_websockets_do_not_reach_static_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frontend = root / "frontend"
            frontend.mkdir()
            (frontend / "index.html").write_text("test frontend")
            app = create_app(root)
            # Exercise the static mount even when web/dist has not been built.
            app.router.routes[:] = [r for r in app.routes if r.name != "frontend"]
            app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
            with TestClient(app) as client:
                for path in ("/", "/assets/app.js", "/api/events"):
                    with self.subTest(path=path):
                        with self.assertRaises(WebSocketDisconnect) as rejected:
                            with client.websocket_connect(path):
                                self.fail("Unsupported WebSocket was accepted")
                        self.assertEqual(rejected.exception.code, 1008)
                self.assertEqual(client.get("/").text, "test frontend")
                response = client.get("/api/state")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")


@unittest.skipUnless(os.name == "posix", "Uses POSIX process signals")
class WebShutdownTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="shutdown-test-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        store = Store(self.root)
        store.put("projects", {"id": "p", "ready": True, "thumbnails": []})
        media = self.root / "runs" / "web" / "p" / "preview.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        # Only byte-range transport is under test; this is not decoded video.
        self.media_bytes = bytes(range(256)) * 4
        media.write_bytes(self.media_bytes)
        self.log_path = self.root / "server.log"
        log = self.log_path.open("w")
        self.addCleanup(log.close)
        # Replace only AI dispatch. Exercise the actual CLI and server lifecycle.
        script = """
import asyncio
import os
from pathlib import Path
from game_vod_clipper import web

async def pending_chat(*args):
    try:
        await asyncio.Future()
    finally:
        (Path(os.environ['GAME_VOD_ROOT']) / 'chat-cancelled').write_text('done')

web.chat = pending_chat
web.main()
"""
        self.process = subprocess.Popen(
            [sys.executable, "-c", script, "--port", "0"],
            env={**os.environ, "GAME_VOD_ROOT": str(self.root)},
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        self.addCleanup(self.stop_process)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            output = self.log_path.read_text()
            match = re.search(r"Uvicorn running on http://127\.0\.0\.1:(\d+)", output)
            if match:
                self.port = int(match[1])
                return
            if self.process.poll() is not None:
                self.fail(output)
            time.sleep(0.02)
        self.fail("Server did not start: " + self.log_path.read_text())

    def stop_process(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)

    def connect(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        return connection

    def assert_clean_shutdown(self, sig):
        started = time.monotonic()
        self.process.send_signal(sig)
        try:
            self.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.fail("Shutdown stalled: " + self.log_path.read_text())
        self.assertLess(time.monotonic() - started, 4)
        output = self.log_path.read_text()
        self.assertIn("Application shutdown complete.", output)
        self.assertIn("Finished server process", output)
        for error in ("ERROR:", "Traceback", "timeout graceful shutdown exceeded"):
            self.assertNotIn(error, output)
        # Uvicorn re-raises the captured signal after a clean shutdown on POSIX.
        self.assertIn(self.process.returncode, (0, -sig, 128 + sig))

    def test_sigint_closes_open_events_after_preview_range_request(self):
        connection = self.connect()
        connection.request("GET", "/api/events")
        events = connection.getresponse()
        self.assertEqual(events.status, 200)
        self.assertTrue(events.readline().startswith(b"data: "))
        self.assertEqual(events.readline(), b"\n")
        media = self.connect()
        media.request("GET", "/api/projects/p/media/preview.mp4",
                      headers={"Range": "bytes=100-199"})
        response = media.getresponse()
        self.assertEqual(response.status, 206)
        self.assertEqual(response.getheader("Content-Range"), "bytes 100-199/1024")
        self.assertEqual(response.read(), self.media_bytes[100:200])
        # Keep EventSource and the preview keep-alive socket open during Ctrl+C.
        self.assert_clean_shutdown(signal.SIGINT)
        self.assertEqual(events.read(), b"")

    def test_sigterm_cancels_pending_chat_before_draining_connections(self):
        connection = self.connect()
        connection.request("POST", "/api/codex/chat", body='{"message":"hello","model":"test"}',
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'"waiting"', response.readline())
        self.assert_clean_shutdown(signal.SIGTERM)
        self.assertEqual(response.read(), b"")
        self.assertEqual((self.root / "chat-cancelled").read_text(), "done")

    def test_sigint_stops_preview_when_player_is_not_reading(self):
        with (self.root / "runs" / "web" / "p" / "preview.mp4").open("r+b") as media:
            media.truncate(32 * 1024 * 1024)
        connection = self.connect()
        connection.request("GET", "/api/projects/p/media/preview.mp4",
                           headers={"Range": "bytes=0-"})
        response = connection.getresponse()
        self.assertEqual(response.status, 206)
        self.assertEqual(response.read(1), self.media_bytes[:1])
        # Leave the body unread, as a paused/preloaded browser video can do.
        self.assert_clean_shutdown(signal.SIGINT)


if __name__ == "__main__":
    unittest.main()
