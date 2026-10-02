"""Per-game reference profiles: example screenshots and notes the visual worker sees.

A project follows the default profile unless it names one (or explicitly none).
Without any profile, analysis runs exactly as before with no reference images.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

KINDS = {"victory": "勝利畫面", "failure": "失敗畫面", "boss": "Boss 戰範例"}
PER_KIND = 3
MAX_UPLOAD = 20 * 1024 * 1024
# References are sent on every analysis round; keep them readable but small.
MAX_SIDE = 1280
ID = re.compile(r"[a-f0-9]{16}\Z")


class ProfileError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class GameProfiles:
    def __init__(self, root: Path):
        self.path = root / "runs" / "web" / "profiles"
        self.path.mkdir(parents=True, exist_ok=True)

    def _write(self, path: Path, value: dict):
        temporary = path.with_name(f".{secrets.token_hex(8)}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    def _folder(self, profile_id: str):
        if not ID.fullmatch(profile_id or ""):
            raise ProfileError("找不到這個遊戲範例設定。", 404)
        return self.path / profile_id

    def get(self, profile_id: str):
        path = self._folder(profile_id) / "profile.json"
        if not path.is_file():
            raise ProfileError("找不到這個遊戲範例設定。", 404)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, profile: dict):
        profile["updated"] = time.time()
        self._write(self._folder(profile["id"]) / "profile.json", profile)
        return profile

    def all(self):
        result = []
        for folder in self.path.iterdir():
            if folder.is_dir() and ID.fullmatch(folder.name) and (folder / "profile.json").is_file():
                result.append(self.get(folder.name))
        return sorted(result, key=lambda item: item.get("created", 0))

    def default_id(self):
        settings = self.path / "settings.json"
        value = json.loads(settings.read_text(encoding="utf-8")).get("default") if settings.is_file() else None
        return value if value and (self.path / value / "profile.json").is_file() else None

    def set_default(self, profile_id: str | None):
        if profile_id:
            self.get(profile_id)
        self._write(self.path / "settings.json", {"default": profile_id})

    def create(self, title: str, notes: str):
        profile_id = secrets.token_hex(8)
        self._folder(profile_id).mkdir()
        now = time.time()
        return self.save({"id": profile_id, "title": title, "notes": notes, "images": [], "created": now})

    def update(self, profile_id: str, **changes):
        return self.save(self.get(profile_id) | changes)

    def delete(self, profile_id: str):
        folder = self._folder(profile_id)
        self.get(profile_id)
        if self.default_id() == profile_id:
            self.set_default(None)
        shutil.rmtree(folder)

    def add_image(self, profile_id: str, kind: str, caption: str, data: bytes):
        if kind not in KINDS:
            raise ProfileError("範例類型無效。", 422)
        profile = self.get(profile_id)
        if sum(image["kind"] == kind for image in profile["images"]) >= PER_KIND:
            raise ProfileError(f"每種範例最多 {PER_KIND} 張，請先移除舊圖片。", 409)
        if not data or len(data) > MAX_UPLOAD:
            raise ProfileError("圖片須小於 20 MB。", 413)
        try:
            with Image.open(io.BytesIO(data)) as source:
                picture = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ProfileError("無法讀取這張圖片，請改用 PNG 或 JPEG。", 422) from None
        picture.thumbnail((MAX_SIDE, MAX_SIDE))
        image_id = secrets.token_hex(8)
        picture.save(self._folder(profile_id) / f"{image_id}.jpg", "JPEG", quality=90)
        profile["images"].append({"id": image_id, "kind": kind, "caption": caption})
        return self.save(profile)

    def update_image(self, profile_id: str, image_id: str, caption: str):
        profile = self.get(profile_id)
        image = next((item for item in profile["images"] if item["id"] == image_id), None)
        if not image:
            raise ProfileError("找不到這張範例圖片。", 404)
        image["caption"] = caption
        return self.save(profile)

    def remove_image(self, profile_id: str, image_id: str):
        profile = self.get(profile_id)
        if not any(item["id"] == image_id for item in profile["images"]):
            raise ProfileError("找不到這張範例圖片。", 404)
        profile["images"] = [item for item in profile["images"] if item["id"] != image_id]
        self.save(profile)
        (self._folder(profile_id) / f"{image_id}.jpg").unlink(missing_ok=True)
        return profile

    def image_path(self, profile_id: str, image_id: str):
        if not ID.fullmatch(image_id or ""):
            raise ProfileError("找不到這張範例圖片。", 404)
        path = self._folder(profile_id) / f"{image_id}.jpg"
        if not path.is_file():
            raise ProfileError("找不到這張範例圖片。", 404)
        return path

    def resolve(self, project: dict):
        """The profile a project analyses with: explicit choice, else the default."""
        profile_id = project.get("profile_id", "default")
        if profile_id == "default":
            profile_id = self.default_id()
        if not profile_id:
            return None
        try:
            return self.get(profile_id)
        except ProfileError:
            return None

    def snapshot(self, profile: dict | None):
        """What an analysis job records, so later profile edits cannot change it mid-run."""
        if not profile:
            return None
        images = sorted(profile["images"], key=lambda item: list(KINDS).index(item["kind"]))
        return {"id": profile["id"], "title": profile["title"], "notes": profile["notes"], "images": images}

    def materialize(self, snapshot: dict | None, work: Path):
        """Copy a job's reference images into its folder; returns (paths, labels)."""
        if not snapshot:
            return [], []
        target = work / "references"
        target.mkdir(parents=True, exist_ok=True)
        paths, labels = [], []
        for image in snapshot["images"]:
            copy = target / f"{image['id']}.jpg"
            if not copy.is_file():
                try:
                    shutil.copyfile(self.image_path(snapshot["id"], image["id"]), copy)
                except (ProfileError, OSError):
                    continue  # Removed after the job was queued; analyse without it.
            paths.append(copy)
            labels.append({"kind": image["kind"], "caption": image["caption"]})
        return paths, labels
