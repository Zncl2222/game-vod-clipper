"""Local token ledger and comparable snapshots of official account quotas.

Token totals are observed usage, not a conversion to subscription allowance.
The ledger survives deleting projects or resetting their analysis history.
"""

from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from ..storage.store import Store

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens",
                "cache_write_input_tokens", "reasoning_output_tokens")


def tokens(value: dict | None) -> dict:
    value = value if isinstance(value, dict) else {}
    counts = {key: value[key] if type(value.get(key)) is int and value[key] >= 0 else 0
              for key in TOKEN_FIELDS}
    # Cached input and reasoning output are subsets, not additional tokens.
    return {**counts, "total_tokens": counts["input_tokens"] + counts["output_tokens"]}


def record_usage(store: Store, value: dict, *, kind: str, model: str,
                 project_id: str | None = None, job_id: str | None = None):
    if not isinstance(value, dict) or not any(key in value for key in TOKEN_FIELDS):
        return
    store.put("usage", {
        "id": uuid4().hex, "kind": kind, "model": model,
        "project_id": project_id, "job_id": job_id,
        "recorded_at": time.time(), "tokens": tokens(value),
    })


def backfill_usage(store: Store):
    """Import old cumulative jobs once, subtracting their continuation baseline.

    Each child adds only its own increment, including when two children resume the
    same parent. Do this before records can be deleted, and retain zero increments
    so a later migration cannot re-import an inherited total.
    """
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        jobs = {key: json.loads(data) for key, data in db.execute("SELECT id, data FROM jobs")}

        def cumulative(job):
            return tokens(job.get("usage") or (job.get("result") or {}).get("usage"))

        for key, job in jobs.items():
            if job.get("kind") != "analyze" or job.get("usage_tracked"):
                continue
            if not (job.get("usage") or (job.get("result") or {}).get("usage")):
                continue
            parent = jobs.get((job.get("analysis") or {}).get("resume_from"), {})
            current, previous = cumulative(job), cumulative(parent)
            own = tokens({field: max(0, current[field] - previous[field]) for field in TOKEN_FIELDS})
            record = {"id": f"legacy:{key}", "kind": "analysis", "model": job.get("model"),
                      "project_id": job.get("project_id"), "job_id": key, "tokens": own,
                      "recorded_at": job.get("finished_at", job.get("created")), "legacy": True}
            db.execute("INSERT OR IGNORE INTO usage VALUES (?, ?)",
                       (record["id"], json.dumps(record, ensure_ascii=False, allow_nan=False)))


def usage_summary(store: Store, project_id: str | None = None) -> dict:
    records = store.all("usage")

    def total(selected):
        return {**tokens({key: sum(row["tokens"].get(key, 0) for row in selected)
                          for key in TOKEN_FIELDS}), "records": len(selected)}

    jobs = [job for job in store.all("jobs") if job.get("kind") == "analyze"
            and (not project_id or job.get("project_id") == project_id)]
    latest = max(jobs, key=lambda job: job.get("created", 0), default=None)
    return {
        "total": total(records),
        "project": total([row for row in records if row.get("project_id") == project_id]) if project_id else None,
        "latest_analysis": {
            "id": latest["id"], "status": latest["status"],
            "tokens": total([row for row in records if row.get("job_id") == latest["id"]]),
            "quota_change": latest.get("quota_change"),
        } if latest else None,
    }


def finite(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def quota_buckets(result: dict) -> list[dict]:
    """Allow-list public counters; preserve server-provided window lengths."""
    sources = result.get("rateLimitsByLimitId")
    sources = dict(sources) if isinstance(sources, dict) else {}
    legacy = result.get("rateLimits")
    if isinstance(legacy, dict):
        sources.setdefault(legacy.get("limitId") or "codex", legacy)
    buckets = []
    for key, source in sources.items():
        if not isinstance(source, dict):
            continue
        windows = []
        for slot in ("primary", "secondary"):
            window = source.get(slot)
            if not isinstance(window, dict):
                continue
            used = window.get("usedPercent")
            if not finite(used) or used < 0:
                continue
            duration, reset = window.get("windowDurationMins"), window.get("resetsAt")
            windows.append({"id": slot, "used_percent": used,
                            "window_minutes": duration if finite(duration) and duration > 0 else None,
                            "resets_at": reset if finite(reset) and reset > 0 else None})
        if windows:
            buckets.append({"id": key, "name": source.get("limitName") or key, "windows": windows})
    return buckets


def quota_change(before: dict, after: dict) -> dict:
    """A quota-window delta is an account-wide estimate, never a task invoice."""
    if not before.get("available") or not after.get("available"):
        return {"status": "unavailable", "windows": []}
    if not before.get("account_key") or before["account_key"] != after.get("account_key"):
        return {"status": "account_changed", "windows": []}
    previous = {(bucket["id"], window["id"]): window
                for bucket in before["buckets"] for window in bucket["windows"]}
    changes = []
    for bucket in after["buckets"]:
        for window in bucket["windows"]:
            old = previous.get((bucket["id"], window["id"]))
            status, delta = "unavailable", None
            if (old and window["window_minutes"] is not None
                    and old["window_minutes"] == window["window_minutes"]
                    and old["resets_at"] is not None and window["resets_at"] is not None):
                if (old["resets_at"] != window["resets_at"]
                        or window["resets_at"] <= after["fetched_at"]
                        or window["used_percent"] < old["used_percent"]):
                    status = "reset"
                else:
                    status = "estimated"
                    delta = round(window["used_percent"] - old["used_percent"], 6)
            changes.append({"bucket_id": bucket["id"], "bucket_name": bucket["name"],
                            "window_minutes": window["window_minutes"], "status": status,
                            "percentage_points": delta})
    return {"status": "estimated" if any(w["status"] == "estimated" for w in changes) else "unavailable",
            "windows": changes}
