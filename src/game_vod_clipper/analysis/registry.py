"""Host-owned identities for observations; model aliases never become public IDs."""

from __future__ import annotations

import re

def same_event(a: dict, b: dict) -> bool:
    """Conservative fallback for renamed observations, not general overlap merging."""
    if a["kind"] != b["kind"] or a.get("boss", "").strip() != b.get("boss", "").strip():
        return False
    return abs(a["start"] - b["start"]) <= .05 and abs(a["end"] - b["end"]) <= .05


class CandidateRegistry:
    def __init__(self, origin: str, saved: dict | None = None):
        self.origin = origin
        self.records = (saved or {}).get("records", {})
        self.aliases = (saved or {}).get("aliases", {})
        self.retired = (saved or {}).get("retired", {})
        self.legacy_ids = (saved or {}).get("legacy_ids", {})
        self.next_id = (saved or {}).get("next_id", 1)

    def alias(self, value: str) -> str:
        value = value.split(":")[-1]
        while value.startswith(self.origin):
            value = value[len(self.origin):].lstrip("-_: ")
        return value

    def update(self, observations: list[dict]) -> None:
        # A duplicate model alias for DIFFERENT ranges must not overwrite either.
        counts: dict[str, int] = {}
        for item in observations:
            alias = self.alias(item["id"])
            counts[alias] = counts.get(alias, 0) + 1
        for item in observations:
            alias = self.alias(item["id"])
            # Temporary labels are scoped to THIS response. A later "new1"
            # means a new event, not a revision of the first response's new1.
            temporary = re.fullmatch(r"new(?:[_-]?\d+)?", alias, re.IGNORECASE) is not None
            key = None if temporary else alias if alias in self.records else self.aliases.get(alias)
            previous = self.records.get(key)
            if previous and (counts[alias] > 1 or min(previous["end"], item["end"]) <= max(previous["start"], item["start"])):
                key = None
            if key not in self.records:
                key = next((k for k, value in self.records.items() if same_event(value, item)), None)
            if key is None:
                key = f"c{self.next_id:04d}"
                self.next_id += 1
            record = {k: v for k, v in item.items() if k not in {"replaces", "aliases", "number", "review"}} | {"id": key}
            # Replacement is explicit and auditable. Different event types (e.g.
            # a death inside a fight) are retained rather than silently hidden.
            for reference in item.get("replaces", []):
                old = self.alias(reference)
                old = old if old in self.records else self.aliases.get(old)
                if old and old != key and old in self.records:
                    prior = self.records[old]
                    if prior["kind"] == item["kind"] and min(prior["end"], item["end"]) > max(prior["start"], item["start"]):
                        self.retired[old] = self.records.pop(old) | {"superseded_by": key}
                        self.aliases = {a: key if target == old else target for a, target in self.aliases.items()}
                        self.aliases[old] = key
                        self.legacy_ids = {a: key if target == old else target for a, target in self.legacy_ids.items()}
            self.records[key] = record
            if ":" in item["id"]:
                self.legacy_ids[item["id"]] = key
            if alias and counts[alias] == 1 and not temporary:
                self.aliases[alias] = key

    def public(self) -> list[dict]:
        return [value | {"id": f"{self.origin}:{key}",
                         "aliases": [old for old, target in self.legacy_ids.items() if target == key]}
                for key, value in self.records.items()]

    def superseded_ids(self) -> list[str]:
        return list(self.legacy_ids) + [f"{self.origin}:{key}" for key in self.retired]

    def snapshot(self) -> dict:
        return {"records": self.records, "aliases": self.aliases,
                "retired": self.retired, "legacy_ids": self.legacy_ids, "next_id": self.next_id}
