"""Durable import receipts, deliberately independent of project/job lifetimes."""

import json
import re
import time


def remember(db, project: dict, *, deleted=False, overwrite_title=True):
    video_id = project.get("youtube_video_id")
    if not video_id:
        match = re.fullmatch(r"https://www\.youtube\.com/watch\?v=([\w-]{11})", project.get("url") or "")
        video_id = match[1] if match else None
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return
    row = db.execute("SELECT data FROM youtube_history WHERE id=?", (video_id,)).fetchone()
    history = json.loads(row[0]) if row else {"id": video_id, "title": f"YouTube · {video_id}", "imports": {}}
    title = project.get("youtube_title") or project.get("title")
    if title and (overwrite_title or history["title"].startswith("YouTube · ")) and (
            not title.startswith("YouTube · ") or history["title"].startswith("YouTube · ")):
        history["title"] = title
    if project.get("youtube_channel_id"):
        history["channel_id"] = project["youtube_channel_id"]
    receipt = history["imports"].setdefault(project["id"], {"at": project.get("created"), "ready": False})
    if receipt["at"] is None and project.get("created"):
        receipt["at"] = project["created"]
    receipt["ready"] = receipt["ready"] or bool(project.get("ready"))
    if deleted:
        receipt.setdefault("deleted_at", time.time())
    encoded = json.dumps(history, ensure_ascii=False, allow_nan=False)
    if not row or row[0] != encoded:
        db.execute("INSERT INTO youtube_history VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (video_id, encoded))


def public_history(store, projects=None):
    projects = {p["id"]: p for p in (store.all("projects") if projects is None else projects)}
    result = []
    for item in store.all("youtube_history"):
        receipts = item["imports"]
        existing = [projects[key] for key in receipts if key in projects]
        latest = max(existing, key=lambda p: p.get("created", 0)) if existing else None
        dates = [r["at"] for r in receipts.values() if r.get("at") is not None]
        result.append({"id": item["id"], "title": item["title"],
                       "url": f"https://www.youtube.com/watch?v={item['id']}",
                       "channel_id": item.get("channel_id"), "import_count": len(receipts),
                       "first_imported_at": min(dates) if dates else None,
                       "last_imported_at": max(dates) if dates else None,
                       "completed": any(r["ready"] for r in receipts.values()),
                       "project_id": latest["id"] if latest else None})
    return sorted(result, key=lambda r: r["last_imported_at"] or 0, reverse=True)


def backfill_legacy(store, files, tasks):
    """Recover old channel imports even when their projects were already deleted."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for task in tasks:
            if task.get("project_id"):
                remember(db, {"id": task["project_id"], "youtube_video_id": task["video_id"],
                              "youtube_channel_id": task.get("channel", {}).get("id"),
                              "title": task.get("title"), "created": task.get("created")}, overwrite_title=False)
        for key, project_id in files.read("imports", {}).items():
            channel_id, _, video_id = key.rpartition(":")
            if isinstance(project_id, str):
                remember(db, {"id": project_id, "youtube_video_id": video_id, "youtube_channel_id": channel_id})
