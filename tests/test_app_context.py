"""Feature routers must keep separate app instances isolated."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from game_vod_clipper.web import create_app


class AppIsolationTest(unittest.TestCase):
    def test_project_changes_and_shutdown_stay_in_their_own_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = create_app(root / "first")
            second = create_app(root / "second")
            for app, title in ((first, "First"), (second, "Second")):
                app.state.store.put("projects", {
                    "id": "same-id", "title": title, "ready": False,
                    "source": None, "thumbnails": [],
                })

            with TestClient(second) as second_client:
                with TestClient(first) as first_client:
                    response = first_client.patch("/api/projects/same-id", json={"title": "Renamed"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["title"], "Renamed")
                    self.assertEqual(second_client.get("/api/projects/same-id").json()["title"], "Second")

                    response = first_client.delete("/api/projects/same-id")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(first_client.get("/api/state").json()["projects"], [])
                    projects = second_client.get("/api/state").json()["projects"]
                    self.assertEqual([project["title"] for project in projects], ["Second"])

                # Closing one app must not stop another app's routes or streams.
                self.assertTrue(first.state.shutting_down.is_set())
                self.assertEqual(second_client.get("/api/health").status_code, 200)
                self.assertEqual(second_client.get("/api/projects/same-id").status_code, 200)
