"""Validate observed ranges and require explicit evidence of a victory."""

from __future__ import annotations

from .models import Observation


def verified_outcome(value: Observation | None) -> bool:
    outcome = value.outcome if value else None
    return bool(outcome and outcome.player == "active"
                and outcome.opponent in {"defeated", "surrendered"}
                and outcome.signal in {"reward", "objective_complete", "victory_banner", "postfight"})


def validate_observation(
    data: dict, start: float, end: float, duration: float
) -> Observation:
    value = Observation.model_validate(data)
    if value.outcome and value.outcome.player == "defeated":
        value.status, value.victory, value.entry_status = "uncertain", None, "unknown"
        value.warnings.append("結局顯示玩家倒下，不能以字幕或讀取畫面判定勝利。")
    if value.status == "candidate" and (value.start is None or value.victory is None):
        # A common worker error is calling a plausible encounter a "candidate"
        # before its outcome is located. Preserve the useful observations, but
        # conservatively downgrade; never fill in or approve a missing endpoint.
        value.status = "uncertain"
        value.warnings.append("尚未定位完整成功挑戰的起點與勝利，保留為待確認遭遇。")
    if not 5 <= value.postroll <= 10:
        raise ValueError("模型傳回的收尾秒數超出 5–10 秒。")
    if any(not start <= e.time <= end for e in value.evidence):
        raise ValueError("模型引用了分析範圍外的時間點。")
    for candidate in value.candidates:
        if (not start <= candidate.start < candidate.end <= end
                or (candidate.victory is not None and not candidate.start < candidate.victory <= candidate.end)
                or any(not start <= e.time <= end for e in candidate.evidence)):
            raise ValueError("候選標註時間超出分析範圍。")
    if value.status == "candidate" and (
        value.start is None
        or value.victory is None
        or not start <= value.start < value.victory <= end
        or value.victory + value.postroll > duration
    ):
        raise ValueError("模型傳回的剪輯範圍無效。")
    return value
