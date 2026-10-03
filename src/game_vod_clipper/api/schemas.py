"""Validated HTTP request bodies."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..codex.connection import MODEL
from ..youtube.downloader import DownloadQuality


class ImportRequest(BaseModel):
    kind: Literal["local", "youtube"]
    source: str = Field(min_length=1, max_length=2000)
    download_quality: DownloadQuality = "best"


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)


class DeleteStoredVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeleteStoredVideos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def valid_ids(cls, values):
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in values):
            raise ValueError("影片檔案編號無效。")
        return list(dict.fromkeys(values))


def plain_text(value: str):
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("不能包含控制字元。")
    return value


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=2000)
    _text = field_validator("title", "notes")(plain_text)


class CaptionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    caption: str = Field(default="", max_length=1000)
    _text = field_validator("caption")(plain_text)


class LocationUpdate(BaseModel):
    """Only the locations sent are changed; null or an empty path restores the default."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sources: str | None = Field(default=None, max_length=1000)
    exports: str | None = Field(default=None, max_length=1000)
    cache: str | None = Field(default=None, max_length=1000)
    _text = field_validator("sources", "exports", "cache")(lambda value: value and plain_text(value))


class ProfileChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "default" follows the default profile; null uses no references.
    profile_id: str | None = Field(max_length=40)


class Draft(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    title: str | None = Field(default=None, max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    start: float = Field(ge=0)
    victory: float = Field(gt=0)
    postroll: float = Field(ge=5, le=10)
    reviewed: bool = False
    revision: int = Field(ge=0)
    origin: Literal["manual", "agent"] = "manual"
    candidate_id: str | None = Field(default=None, min_length=1, max_length=200)
    candidate_revision: int | None = Field(default=None, ge=0)
    manually_adjusted: bool | None = None


ExportQuality = Literal["max", "high", "balanced", "fast"]


class ExportRequest(BaseModel):
    revision: int = Field(ge=0)
    source_job_id: str | None = Field(default=None, min_length=1, max_length=100)
    quality: ExportQuality = "high"


class CandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=200)
    review: Literal["pending", "keep", "reject"]
    analysis_generation: int = Field(ge=0)


class CandidateEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    candidate_id: str = Field(min_length=1, max_length=200)
    analysis_generation: int = Field(ge=0)
    revision: int = Field(ge=0)
    start: float = Field(ge=0)
    victory: float = Field(gt=0)
    postroll: float = Field(ge=5, le=10)


class CodexLoginRequest(BaseModel):
    method: Literal["chatgpt", "chatgptDeviceCode"] = "chatgptDeviceCode"


class AnalysisRequest(BaseModel):
    effort: str | None = Field(default=None, max_length=40)
    effort_policy: Literal["adaptive", "fixed"] = "adaptive"
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    model: str = Field(default=MODEL, min_length=1, max_length=120)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=100)
    analysis_generation: int | None = Field(default=None, ge=0)
