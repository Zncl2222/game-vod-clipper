"""Measure local video files without reading their contents or following outside links."""

import os
import stat
import time
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}


def video_storage(root: Path) -> dict:
    root = root.resolve()
    seen = set()
    incomplete = False
    categories = {}

    def unreadable(_error):
        nonlocal incomplete
        incomplete = True

    for folder, category in (("downloads", "sources"), ("clips", "exports"), ("runs", "previews")):
        total = count = 0
        base = root / folder
        if base.is_symlink():
            incomplete = True
            categories[category] = {"bytes": 0, "files": 0}
            continue
        for directory, _, files in os.walk(base, followlinks=False, onerror=unreadable) if base.exists() else []:
            for name in files:
                path = Path(directory) / name
                media_name = path.with_suffix("") if path.suffix.lower() == ".part" else path
                if media_name.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(root):
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
    return {"bytes": sum(item["bytes"] for item in categories.values()),
            "files": sum(item["files"] for item in categories.values()),
            "categories": categories, "incomplete": incomplete, "updated_at": time.time()}
