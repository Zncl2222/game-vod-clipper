"""Stable, project-scoped review annotations shared by the UI and chat."""

import math
from .candidate_registry import same_event


def candidate_verification(segment: dict, job: dict, duration: float) -> dict:
    """Project host validation onto an annotation without trusting worker confidence."""
    value = dict(segment, verification="unverified", warnings=list(segment.get("warnings", [])))
    if segment.get("kind") != "possible_win":
        return value
    result = job.get("result") or {}
    matches = (segment.get("victory") is not None
               and segment["start"] == result.get("start")
               and segment["victory"] == result.get("victory"))
    if matches:
        value["warnings"] += result.get("warnings", [])
        postroll = result.get("postroll", 8)
        value["postroll"] = postroll
        checks = result.get("checks") or {}
        verified = (job.get("status") == "succeeded" and result.get("status") == "candidate"
                    and result.get("review_complete") is True and not result.get("can_continue")
                    and all(checks.get(k) is True for k in
                            ("search", "entry", "outcome", "boundaries", "dense", "continuity"))
                    and all(checks.values())
                    and 5 <= postroll <= 10 and segment["victory"] + postroll <= duration)
        if verified:
            value["verification"] = "verified"
        elif result.get("status") != "candidate":
            value["verification"] = "blocked"
            if not value["warnings"]:
                value["warnings"].append("此區間未通過成功挑戰驗證，需修正或釐清後才能作為成功剪輯。")
    if value["verification"] == "unverified":
        value["warnings"].append("此為初步遭遇標註，尚未驗證完整成功嘗試；區間可能包含失敗或重試。")
    value["warnings"] = list(dict.fromkeys(value["warnings"]))
    return value


def project_candidates(project: dict, jobs: list[dict]) -> list[dict]:
    # Store returns newest first. First discovery establishes the display number;
    # resumed jobs refine the same id without moving it or creating another item.
    found = {}
    for job in reversed(jobs):
        if job.get("project_id") != project["id"] or job.get("kind") != "analyze":
            continue
        result = job.get("result") or {}
        if result.get("project_id", project["id"]) != project["id"]:
            continue
        segments = job.get("candidates", result.get("candidates", []))
        if not segments and result.get("start") is not None and result.get("victory") is not None:
            segments = [{"id": f"{job['id']}:legacy", "start": result["start"],
                "end": min(project["duration"], result["victory"] + result.get("postroll", 8)),
                "victory": result["victory"], "kind": "possible_win", "confidence": "low",
                "boss": result.get("boss", ""), "summary": result.get("summary", ""),
                "warnings": result.get("warnings", []), "evidence": result.get("evidence", [])}]
        for segment in segments:
            a, b = segment.get("start"), segment.get("end")
            if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                    and math.isfinite(a) and math.isfinite(b) and 0 <= a < b <= project["duration"]):
                found[segment["id"]] = candidate_verification(segment, job, project["duration"])
    retired = {key for job in jobs if job.get("project_id") == project["id"]
               for key in job.get("superseded_candidates", [])}
    reviews = project.get("candidate_reviews", {})
    # Collapse exact legacy duplicates for display without mutating old runs.
    # ID aliases remain available so saved review tags survive consolidation.
    consolidated = []
    for segment in found.values():
        if segment["id"] in retired:
            continue
        existing = next((c for c in consolidated if same_event(c, segment)), None)
        segment_aliases = list(dict.fromkeys([segment["id"], *segment.get("aliases", [])]))
        if existing is None:
            consolidated.append(dict(segment, aliases=segment_aliases))
        else:
            aliases = list(dict.fromkeys(existing["aliases"] + segment_aliases))
            stable_id = existing["id"]
            existing.update(segment, id=stable_id, aliases=aliases)
    for index, segment in enumerate(consolidated, 1):
        if segment["kind"] == "possible_win":
            finish = (segment["victory"] + segment.get("postroll", 8)
                      if segment.get("victory") is not None else segment["end"])
            if segment["verification"] != "blocked" and any(
                    c["kind"] == "death_retry" and c["confidence"] == "high"
                    and c["start"] <= finish and segment["start"] <= c["end"] for c in consolidated):
                segment["verification"] = "blocked"
                segment["warnings"] = list(dict.fromkeys(segment["warnings"] +
                    ["此區間與死亡／重試標註重疊，尚不能作為成功剪輯。請修正起點或釐清該標註。"]
                ))
        tags = {reviews[key] for key in segment["aliases"] if key in reviews}
        segment.update(number=index, review=reviews.get(segment["id"], next(iter(tags)) if len(tags) == 1 else "pending"))
    # Keep model output intact; human corrections are a separate, durable layer.
    for segment in consolidated:
        edits = project.get("candidate_edits", {})
        manual = edits.get(segment["id"]) or max(
            (edits[key] for key in segment["aliases"] if key in edits),
            key=lambda item: item["updated_at"], default=None)
        if manual:
            segment["ai_range"] = {key: segment.get(key) for key in ("start", "end", "victory", "postroll")}
            segment.update(start=manual["start"], victory=manual["victory"], postroll=manual["postroll"],
                           end=manual["victory"] + manual["postroll"], manual_edit=manual, verification="unverified")
    return consolidated
