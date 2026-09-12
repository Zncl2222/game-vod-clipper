"""Stable, project-scoped review annotations shared by the UI and chat."""

import math
from .candidate_registry import same_event


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
                found[segment["id"]] = segment
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
        tags = {reviews[key] for key in segment["aliases"] if key in reviews}
        segment.update(number=index, review=reviews.get(segment["id"], next(iter(tags)) if len(tags) == 1 else "pending"))
    return consolidated
