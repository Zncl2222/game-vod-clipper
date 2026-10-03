"""Typed observations, evidence, and candidate annotations from visual review."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float
    end: float
    every: float


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    time: float
    event: str


class CandidateSegment(BaseModel):
    """A review annotation, never a claim that a clip is safe to export."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    replaces: list[str] = Field(default_factory=list, max_length=100)
    start: float
    end: float
    victory: float | None
    kind: Literal["possible_win", "fight", "death_retry", "unknown"]
    confidence: Literal["low", "medium", "high"]
    boss: str
    summary: str
    warnings: list[str]
    evidence: list[Evidence]


class Outcome(BaseModel):
    """Visible actor states, separate from ambiguous dialogue or loading screens."""
    model_config = ConfigDict(extra="forbid")
    player: Literal["active", "defeated", "unknown"]
    opponent: Literal["active", "defeated", "surrendered", "unknown"]
    signal: Literal["reward", "objective_complete", "victory_banner", "postfight", "dialogue", "loading", "none"]


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    status: Literal["candidate", "not_found", "uncertain"]
    start: float | None
    victory: float | None
    postroll: float
    boss: str
    summary: str
    warnings: list[str]
    evidence: list[Evidence]
    sample_requests: list[SampleRequest]
    suspicious_windows: list[SampleRequest] = Field(default_factory=list)
    candidates: list[CandidateSegment] = Field(default_factory=list, max_length=100)
    review_complete: bool = False
    entry_status: Literal["unknown", "clean", "mid_fight"] = "unknown"
    outcome: Outcome | None = None
