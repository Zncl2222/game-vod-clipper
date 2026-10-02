"""Service readiness without account login, media work or external requests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name))

    def test_ready_without_starting_ai_or_revealing_workspace(self):
        with TestClient(self.app) as client, patch.object(self.app.state.codex, "start") as start:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        start.assert_not_called()

    def test_unavailable_database_returns_redacted_failure(self):
        with TestClient(self.app) as client, patch.object(
            self.app.state.store, "connect", side_effect=sqlite3.OperationalError("private/path.db")
        ):
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Workspace database is unavailable"})

    def test_shutdown_is_not_ready(self):
        with TestClient(self.app) as client:
            self.app.state.shutting_down.set()
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
