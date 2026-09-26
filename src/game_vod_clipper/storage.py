"""Measure local video files without reading their contents or following outside links."""

import os
import stat
import time
from pathlib import Path

from .locations import Locations

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}


def video_storage(root: Path) -> dict:
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
    return {"bytes": sum(item["bytes"] for item in categories.values()),
            "files": sum(item["files"] for item in categories.values()),
            "categories": categories, "incomplete": incomplete, "updated_at": time.time()}
