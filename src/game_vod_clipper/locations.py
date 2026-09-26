"""Where BossCut keeps source videos, finished clips and preview files.

Each location defaults to a folder in the workspace root and can be moved to
any folder the user chooses. Media records store a path relative to the root
while the file lives inside it and an absolute path otherwise, so changing a
location only affects new files: earlier projects keep pointing at theirs.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_FOLDERS = {"sources": "downloads", "exports": "clips", "cache": "runs"}


class LocationError(ValueError):
    pass


def media_path(root: Path, value: str) -> Path:
    """Resolve a stored media path; older records are relative to the root."""
    path = Path(value)
    return path if path.is_absolute() else root / path


def record_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def export_path(root: Path, job: dict) -> Path:
    """The export's MP4, only if it has the layout the media worker writes."""
    default = Path(DEFAULT_FOLDERS["exports"]) / "web" / job["project_id"] / f"{job['id']}.mp4"
    path = media_path(root, job.get("output") or str(default))
    if (path.name != f"{job['id']}.mp4" or path.parent.name != job["project_id"]
            or path.parent.parent.name != "web"):
        raise LocationError("成品檔案位置異常。")
    return path


def project_work(root: Path, project: dict) -> Path:
    """Preview, thumbnails and analysis frames; projects keep the folder they started in."""
    work = project.get("work")
    return media_path(root, work) if work else root / "runs" / "web" / project["id"]


class Locations:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = self.root / "runs" / "web"
        self.path = self.state / "locations.json"

    def custom(self) -> dict[str, str]:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            # Written atomically; an unreadable file falls back to the defaults.
            return {}
        if not isinstance(saved, dict):
            return {}
        return {kind: value for kind, value in saved.items()
                if kind in DEFAULT_FOLDERS and isinstance(value, str) and Path(value).is_absolute()}

    def default(self, kind: str) -> Path:
        return self.root / DEFAULT_FOLDERS[kind]

    def folder(self, kind: str) -> Path:
        value = self.custom().get(kind)
        return Path(value) if value else self.default(kind)

    def project_folder(self, kind: str, project_id: str) -> Path:
        return self.folder(kind) / "web" / project_id

    def status(self) -> dict:
        custom = self.custom()
        return {kind: {"path": str(self.folder(kind)), "default": str(self.default(kind)), "custom": kind in custom}
                for kind in DEFAULT_FOLDERS}

    def update(self, changes: dict[str, str | None]) -> dict:
        """Set folders by kind; None or an empty string restores the default."""
        saved = self.custom()
        for kind, value in changes.items():
            if kind not in DEFAULT_FOLDERS:
                raise LocationError("未知的儲存位置。")
            if value:
                saved[kind] = str(self.validate(value))
            else:
                saved.pop(kind, None)
        self.state.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.state, delete=False) as file:
            json.dump(saved, file, ensure_ascii=False, indent=2)
        os.replace(file.name, self.path)
        return self.status()

    def validate(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise LocationError("請輸入完整的資料夾路徑，例如 D:\\Videos\\BossCut。")
        path = path.resolve()
        if path.parent == path:
            raise LocationError("請選擇磁碟底下的資料夾，不要直接使用磁碟根目錄。")
        if path.is_relative_to(self.state):
            raise LocationError("這是 BossCut 的內部資料夾，請選擇其他位置。")
        if path.exists() and not path.is_dir():
            raise LocationError("這個路徑是檔案，請選擇資料夾。")
        try:
            path.mkdir(parents=True, exist_ok=True)
            tempfile.TemporaryFile(dir=path).close()
        except OSError:
            raise LocationError("無法寫入這個資料夾，請確認路徑存在且有寫入權限。") from None
        return path
