"""Finite, encounter-scoped inspection passes, independent of model wording."""

from __future__ import annotations

import json


def overlaps(a: float, b: float, c: float, d: float) -> bool:
    return a <= d and c <= b


class ReviewTracker:
    """Count completed local passes, never packets or unrelated discoveries.

    A pass may cover a long range in many packets. Its queue is frozen until it
    finishes; changing a timestamp or the list of suspicions cannot renew it.
    Exhaustion preserves uncertainty rather than approving an unchecked clip.
    """

    def __init__(self, saved: dict | None = None, *, limit: int = 3):
        self.scopes = saved or {}
        self.limit = limit

    def scope(self, request: tuple, observation, records: dict) -> str:
        a, b, _ = request
        # Prefer the smallest encounter containing the requested transition.
        # The host-owned ID survives ordinary boundary corrections.
        matching = [(key, value) for key, value in records.items()
                    if overlaps(a, b, value["start"] - 2, value["end"] + 2)]
        owner = min(matching, key=lambda item: (
            not (item[1]["start"] - 2 <= (a + b) / 2 <= item[1]["end"] + 2),
            item[1]["end"] - item[1]["start"], item[0]), default=None)
        if owner:
            key, record = owner
            a, b = min(a, record["start"]), max(b, record["end"])
            # Re-labelled, almost identical hypotheses are still the same local
            # investigation. Merely inventing a fresh model alias cannot reopen it.
            if key not in self.scopes:
                key = next((old for old, value in self.scopes.items()
                            if min(b, value["end"]) - max(a, value["start"])
                            >= .8 * max(b - a, value["end"] - value["start"], .01)), key)
        else:
            # Unannotated nearby questions share a scope too. Moving a request
            # by a fraction of a second must not reset the stopping condition.
            key = next((key for key, value in self.scopes.items()
                        if key.startswith("range:") and overlaps(a, b, value["start"] - 2, value["end"] + 2)),
                       f"range:{int((a + b) / 120)}")
        if key not in self.scopes:
            self.scopes[key] = {"start": a, "end": b, "stalled": 0,
                                "active": False, "progress": False, "exhausted": False,
                                "seen": []}
        scope = self.scopes[key]
        scope["start"], scope["end"] = min(scope["start"], a), max(scope["end"], b)
        if not scope["seen"]:
            scope["seen"] = sorted(self.decisions(key, observation, records))
        return key

    def decisions(self, key: str, observation, records: dict) -> set[str]:
        scope = self.scopes[key]
        # Geometry is deliberately excluded. Fine boundary localization still
        # receives complete coverage, but jitter cannot buy unlimited new passes.
        decisions = [(c["kind"], c.get("victory") is not None)
                     for c in records.values()
                     if overlaps(scope["start"], scope["end"], c["start"], c["end"])]
        if observation and observation.start is not None and observation.victory is not None:
            if overlaps(scope["start"], scope["end"], observation.start,
                        observation.victory + observation.postroll):
                decisions.append(("preferred", observation.status))
                decisions.append(("entry", observation.entry_status))
        return {json.dumps(value) for value in decisions}

    def begin(self, key: str):
        self.scopes[key].update(active=True, progress=False)

    def stable_target(self, request: tuple, victory: float, observation, records: dict) -> bool:
        """Stop replanning an ungrounded moving boundary as a completed uncertainty.

        Required coverage is never waived for acceptance. A target that cannot
        stabilize is rejected instead of extending mandatory checks indefinitely.
        """
        key = self.scope(request, observation, records)
        scope = self.scopes[key]
        target = [request[0], request[1], victory]
        decisions = self.decisions(key, observation, records)
        verification = scope.setdefault("verification", {
            "target": target, "revisions": 0, "seen": sorted(decisions), "closed": False})
        if verification["target"] != target and not verification["closed"]:
            new_decisions = decisions - set(verification["seen"])
            verification["revisions"] = 0 if new_decisions else verification["revisions"] + 1
            verification["target"] = target
            verification["seen"] = sorted(set(verification["seen"]) | decisions)
            if verification["revisions"] >= self.limit:
                verification["closed"] = True
                scope.update(exhausted=True, reason="unstable_boundaries")
        return not verification["closed"]

    def observe(self, key: str, observation, records: dict):
        scope = self.scopes[key]
        decisions = self.decisions(key, observation, records)
        seen = set(scope["seen"])
        scope["progress"] |= bool(decisions - seen)
        scope["seen"] = sorted(seen | decisions)

    def finish(self, pending: set[str]):
        for key, scope in self.scopes.items():
            if scope["active"] and key not in pending:
                scope["stalled"] = 0 if scope["progress"] else scope["stalled"] + 1
                scope["exhausted"] |= scope["stalled"] >= self.limit
                scope.update(active=False, progress=False)

    def exhausted(self) -> list[dict]:
        return [{"scope": key, "start": value["start"], "end": value["end"],
                 "reason": value.get("reason", "no_new_decisions"),
                 "passes": value["verification"]["revisions"] if value.get("reason") == "unstable_boundaries"
                 else value["stalled"]}
                for key, value in self.scopes.items() if value["exhausted"]]
