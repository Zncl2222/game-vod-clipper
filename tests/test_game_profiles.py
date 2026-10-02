"""Per-game reference profiles feed example screenshots to the visual worker."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from game_vod_clipper.codex_connection import MODEL
from game_vod_clipper.game_profiles import GameProfiles
from game_vod_clipper.review_prompt import review_prompt
from game_vod_clipper.web import create_app


def png(width=2560, height=1440):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return buffer.getvalue()


MANIFEST = {"start": 0, "end": 10, "every": 5, "timestamps": [0, 5]}


class GameProfilesTest(unittest.TestCase):
    def setUp(self):
        runs = Path(__file__).resolve().parents[1] / "runs"
        runs.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="profiles-", dir=runs)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = self.enterContext(TestClient(self.app))
        self.app.state.store.put("projects", {"id": "p", "title": "p", "ready": True, "duration": 60,
                                              "source": "downloads/s.mp4", "thumbnails": []})

    def create(self, title="Rise of the Ronin"):
        response = self.client.post("/api/profiles", json={"title": title, "notes": "Boss 有下方大血條"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_images_are_resized_captioned_limited_and_removable(self):
        profile = self.create()
        url = f"/api/profiles/{profile['id']}/images"
        response = self.client.post(url, params={"kind": "boss", "caption": "紅框是 Boss 血條"}, content=png())
        self.assertEqual(response.status_code, 200, response.text)
        image = response.json()["images"][0]
        self.assertEqual((image["kind"], image["caption"]), ("boss", "紅框是 Boss 血條"))
        served = self.client.get(f"{url}/{image['id']}")
        self.assertEqual(served.headers["content-type"], "image/jpeg")
        self.assertEqual(max(Image.open(io.BytesIO(served.content)).size), 1280)
        for _ in range(2):
            self.assertEqual(self.client.post(url, params={"kind": "boss"}, content=png(10, 10)).status_code, 200)
        self.assertEqual(self.client.post(url, params={"kind": "boss"}, content=png(10, 10)).status_code, 409)
        self.assertEqual(self.client.post(url, params={"kind": "other"}, content=png(10, 10)).status_code, 422)
        self.assertEqual(self.client.post(url, params={"kind": "victory"}, content=b"not an image").status_code, 422)
        edited = self.client.patch(f"{url}/{image['id']}", json={"caption": "新說明"}).json()
        self.assertEqual(edited["images"][0]["caption"], "新說明")
        remaining = self.client.delete(f"{url}/{image['id']}").json()["images"]
        self.assertEqual(len(remaining), 2)
        self.assertEqual(self.client.get(f"{url}/{image['id']}").status_code, 404)

    def test_project_follows_default_until_it_picks_a_profile_or_none(self):
        ronin, souls = self.create(), self.create("Elden Ring")
        profiles = GameProfiles(self.root)
        store = self.app.state.store
        self.assertIsNone(profiles.resolve(store.get("projects", "p")))  # No profile: current behaviour.
        self.client.put("/api/profiles/default", json={"profile_id": ronin["id"]})
        self.assertEqual(profiles.resolve(store.get("projects", "p"))["id"], ronin["id"])
        # Picking a game (or none) also becomes the default, so the next import keeps it.
        for choice, expected, default in ((souls["id"], souls["id"], souls["id"]), (None, None, None),
                                          ("default", None, None), (ronin["id"], ronin["id"], ronin["id"]),
                                          ("default", ronin["id"], ronin["id"])):
            response = self.client.put("/api/projects/p/profile", json={"profile_id": choice})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((profiles.resolve(store.get("projects", "p")) or {}).get("id"), expected)
            self.assertEqual(self.client.get("/api/profiles").json()["default_id"], default)
        # A freshly imported project has no choice of its own and follows that default.
        store.put("projects", {key: value for key, value in store.get("projects", "p").items() if key != "profile_id"} | {"id": "new"})
        self.assertEqual(profiles.resolve(store.get("projects", "new"))["id"], ronin["id"])
        self.assertEqual(self.client.put("/api/projects/p/profile", json={"profile_id": "0" * 16}).status_code, 404)
        self.client.put("/api/projects/p/profile", json={"profile_id": souls["id"]})
        listing = self.client.delete(f"/api/profiles/{souls['id']}").json()
        self.assertEqual([item["id"] for item in listing["profiles"]], [ronin["id"]])
        self.assertEqual(store.get("projects", "p")["profile_id"], "default")
        self.client.delete(f"/api/profiles/{ronin['id']}")
        self.assertIsNone(self.client.get("/api/profiles").json()["default_id"])

    def test_analysis_job_snapshots_the_projects_profile(self):
        profile = self.create()
        self.client.post(f"/api/profiles/{profile['id']}/images", params={"kind": "victory"}, content=png(10, 10))
        self.client.put("/api/projects/p/profile", json={"profile_id": profile["id"]})
        self.app.state.codex.status = AsyncMock(return_value={"available": True})
        self.app.state.codex.models = AsyncMock(return_value=[{"id": MODEL, "effort": "medium",
                                                               "input_modalities": ["text", "image"]}])
        with patch("game_vod_clipper.web.Jobs.submit", return_value={"id": "queued"}) as submit:
            self.assertEqual(self.client.post("/api/projects/p/analyze", json={"start": 0, "end": 60}).status_code, 202)
        snapshot = submit.call_args.kwargs["analysis"]["profile"]
        self.assertEqual((snapshot["id"], snapshot["title"], [i["kind"] for i in snapshot["images"]]),
                         (profile["id"], "Rise of the Ronin", ["victory"]))
        work = self.root / "runs" / "job"
        paths, labels = GameProfiles(self.root).materialize(snapshot, work)
        self.assertEqual(labels, [{"kind": "victory", "caption": ""}])
        self.assertTrue(paths[0].is_file() and paths[0].is_relative_to(work))

    def test_prompt_is_unchanged_without_a_profile_and_labels_references_with_one(self):
        plain = review_prompt(manifest=MANIFEST, purpose="search", start=0, end=10, duration=10)
        self.assertTrue(plain.startswith("You inspect timestamped gameplay images"))
        self.assertEqual(plain, review_prompt(manifest=MANIFEST, purpose="search", start=0, end=10, duration=10,
                                              profile={"title": "Empty", "notes": " ", "images": []}))
        guided = review_prompt(manifest=MANIFEST, purpose="search", start=0, end=10, duration=10, profile={
            "title": "Ronin", "notes": "大血條", "images": [{"kind": "victory", "caption": "完成字樣"},
                                                          {"kind": "boss", "caption": ""}]})
        self.assertTrue(guided.endswith(plain.split("You inspect", 1)[1]))
        self.assertIn("FIRST 2 attached images are reference screenshots", guided)
        self.assertIn('Reference 1: VICTORY example', guided)
        self.assertIn('"完成字樣"', guided)
        self.assertIn("Red boxes", guided)


if __name__ == "__main__":
    unittest.main()
