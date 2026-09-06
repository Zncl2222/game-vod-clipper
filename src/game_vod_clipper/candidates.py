"""Stable, project-scoped review annotations shared by the UI and chat."""

import math


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
    reviews = project.get("candidate_reviews", {})
    return [dict(segment, number=index, review=reviews.get(segment["id"], "pending"))
            for index, segment in enumerate(found.values(), 1)]
