"""Measure local video files without reading their contents or following outside links."""

import os
import hashlib
import stat
import time
from pathlib import Path

from .locations import Locations, media_path, project_work, record_path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}


def video_inventory(store, uploads=(), upload_tasks=()) -> dict:
    """Offer only exact, regular media files; never accept a client-supplied path."""
    root = store.root
    locations = Locations(root)
    candidates = {}
    incomplete = False

    def unreadable(_error):
        nonlocal incomplete
        incomplete = True

    for kind, category in (("sources", "sources"), ("exports", "exports"), ("cache", "previews")):
        for base in dict.fromkeys((locations.folder(kind), locations.default(kind))):
            if base.is_symlink() or base.resolve() != base:
                incomplete = True
                continue
            for directory, _, names in os.walk(base, followlinks=False, onerror=unreadable):
                for name in names:
                    candidates.setdefault(Path(directory) / name, category)
    # Keep access to exact registered files after changing storage locations or
    # deleting projects. This does not authorize scanning their parent folders.
    for item in store.all("retained_media"):
        candidates.setdefault(media_path(root, item["path"]), item["category"])
    projects, jobs = store.all("projects"), store.all("jobs")
    sources, workspaces, exports = {}, [], {}
    for project in projects:
        if project.get("source"):
            path = media_path(root, project["source"])
            candidates.setdefault(path, "sources")
            sources.setdefault(path.resolve(), []).append(project["title"])
        work = project_work(root, project)
        candidates.setdefault(work / "preview.mp4", "previews")
        workspaces.append((work.resolve(), project["title"]))
    for job in jobs:
        if job["kind"] == "export" and job.get("output"):
            path = media_path(root, job["output"])
            candidates.setdefault(path, "exports")
            exports[path.resolve()] = job
    working = any(job["status"] in {"queued", "running"} for job in jobs)
    uploading = {u["export_id"] for u in uploads if u["id"] in upload_tasks or u["status"] in
                 {"queued", "uploading", "processing", "adding_to_playlist"}}
    rows = []
    for path, category in candidates.items():
        name = path.with_suffix("") if path.suffix.lower() == ".part" else path
        if name.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            if path.is_symlink() or path.resolve() != path:
                continue
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                continue
            related = sources.get(path, [])
            preview_users = [title for work, title in workspaces if path.is_relative_to(work)]
            job = exports.get(path)
            reason = ""
            if related:
                reason = "原片仍由專案使用，請先刪除相關專案：" + "、".join(related)
            elif preview_users:
                reason = "專案仍使用此暫存，請先刪除相關專案：" + "、".join(preview_users)
            elif path.stem in uploading or job and job["id"] in uploading:
                reason = "成品正在上傳，請先暫停上傳。"
            elif working:
                reason = "請等下載、分析與匯出任務結束或停止後，再清理影片。"
            elif job and job["status"] != "succeeded":
                reason = "此檔案仍有未完成的匯出紀錄，請先刪除相關專案。"
            identity = f"{path}:{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"
            rows.append({"id": hashlib.sha256(identity.encode()).hexdigest(), "path": record_path(root, path),
                         "name": path.name, "category": category, "bytes": info.st_size, "blocked": reason,
                         "project_id": job["project_id"] if job else None, "job_id": job["id"] if job else None})
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError):
            incomplete = True
    return {"items": sorted(rows, key=lambda row: (-row["bytes"], row["path"])), "incomplete": incomplete}


def video_storage(root: Path, store=None) -> dict:
    locations = Locations(root)
    seen = set()
    incomplete = False
    categories = {}

    def unreadable(_error):
        nonlocal incomplete
        incomplete = True

    for kind, category in (("sources", "sources"), ("exports", "exports"), ("cache", "previews")):
        total = count = 0
        # Files made before a location changed stay in the earlier default folder.
        for base in dict.fromkeys((locations.folder(kind), locations.default(kind))):
            if base.is_symlink():
                incomplete = True
                continue
            inside = base.resolve()
            for directory, _, files in os.walk(base, followlinks=False, onerror=unreadable) if base.exists() else []:
                for name in files:
                    path = Path(directory) / name
                    media_name = path.with_suffix("") if path.suffix.lower() == ".part" else path
                    if media_name.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        if not resolved.is_relative_to(inside):
                            continue
                        info = resolved.stat()
                        identity = (info.st_dev, info.st_ino)
                        if not stat.S_ISREG(info.st_mode) or identity in seen:
                            continue
                        seen.add(identity)
                        total += info.st_size
                        count += 1
                    except FileNotFoundError:
                        # Downloads may be renamed or removed while this snapshot is read.
                        continue
                    except (OSError, RuntimeError):
                        incomplete = True
        categories[category] = {"bytes": total, "files": count}
    if store is not None:
        # Earlier custom folders are not recursively scanned. Count only exact
        # paths registered by projects/jobs or retained after project deletion.
        extra = [(media_path(root, item["path"]), item["category"]) for item in store.all("retained_media")]
        for project in store.all("projects"):
            if project.get("source"):
                extra.append((media_path(root, project["source"]), "sources"))
            extra.append((project_work(root, project) / "preview.mp4", "previews"))
        extra.extend((media_path(root, job["output"]), "exports") for job in store.all("jobs")
                     if job["kind"] == "export" and job.get("output"))
        for path, category in extra:
            try:
                if path.is_symlink() or path.resolve() != path:
                    continue
                info = path.stat()
                identity = (info.st_dev, info.st_ino)
                if stat.S_ISREG(info.st_mode) and identity not in seen:
                    seen.add(identity)
                    categories[category]["bytes"] += info.st_size
                    categories[category]["files"] += 1
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError):
                incomplete = True
    return {"bytes": sum(item["bytes"] for item in categories.values()),
            "files": sum(item["files"] for item in categories.values()),
            "categories": categories, "incomplete": incomplete, "updated_at": time.time()}
