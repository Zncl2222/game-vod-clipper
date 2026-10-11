"""Validate observed ranges and require explicit evidence of a victory."""

from __future__ import annotations

from .models import EncounterIdentity, Observation, SampleRequest


def verified_outcome(value: Observation | None) -> bool:
    outcome = value.outcome if value else None
    return bool(outcome and outcome.player == "active"
                and outcome.opponent in {"defeated", "surrendered"}
                and outcome.signal in {"reward", "objective_complete", "victory_banner", "postfight"})


def verified_encounter(value: Observation | EncounterIdentity | None) -> bool:
    identity = value.encounter if isinstance(value, Observation) else value
    if isinstance(value, Observation) and value.start is not None and value.victory is not None:
        if not identity or not any(value.start <= e.time <= value.victory + value.postroll for e in identity.evidence):
            return False
    return bool(identity and identity.status == "confirmed" and identity.evidence
                and identity.signal != "none")


def verified_entry(value: Observation | None) -> bool:
    proof = value.entry_proof if value else None
    return bool(value and value.entry_status == "clean" and value.start is not None
                and proof and proof.kind in {"arena_entry", "first_combat", "boss_reveal"}
                and value.start <= proof.time <= value.start + 8)


def localized_ending(value: Observation | None) -> bool:
    proof = value.ending_proof if value else None
    return bool(verified_outcome(value) and value.victory is not None and proof and proof.phase == "onset"
                and proof.last_combat and proof.first_defeat
                and 0 < proof.first_defeat.time - proof.last_combat.time <= 5
                and abs(proof.first_defeat.time - value.victory) <= .05)


def preserve_verified_ending(previous: Observation | None, local: Observation,
                             request: tuple, purpose: str) -> bool:
    """Keep separately observed facts when a local packet cannot reobserve them.

    The caller scopes both observations to the same encounter. Contradictory
    evidence in an ending packet and any local player failure remain blocking.
    """
    if purpose not in {"entry", "refine", "dense", "continuity", "boundaries", "suspicious"} or not previous:
        return False
    if verified_encounter(previous) and (not local.encounter or local.encounter.status == "unknown"):
        local.encounter = previous.encounter
    failures = [c.model_dump() for c in local.candidates if c.kind == "death_retry" and c.confidence == "high"]
    old_entry_invalidated = any(failure_overlaps(c, previous) for c in failures)
    entry_invalidated = ((local.outcome is not None and local.outcome.player == "defeated")
                         or any(failure_overlaps(c, local) for c in failures))
    if entry_invalidated:
        local.entry_status, local.entry_proof = "unknown", None
    if (not entry_invalidated and not old_entry_invalidated and verified_entry(previous)
            and (not request[0] <= previous.start <= request[1]
                 or not local.entry_proof or local.entry_proof.kind in {"unknown", "mid_fight"})):
        if not request[0] <= previous.start <= request[1] or local.entry_status != "mid_fight":
            local.start, local.entry_status, local.entry_proof = previous.start, "clean", previous.entry_proof
    if (not localized_ending(previous) or previous.victory is None
            or request[0] <= previous.victory <= request[1]):
        return False
    if (verified_outcome(local) and local.victory is not None
            and request[0] <= local.victory <= request[1]):
        return False
    if local.outcome and local.outcome.player == "defeated":
        local.status, local.entry_status = "uncertain", "unknown"
        window = SampleRequest(start=request[0], end=request[1], every=.5)
        if window not in local.suspicious_windows:
            local.suspicious_windows.append(window)
    local.victory, local.outcome, local.ending_proof = previous.victory, previous.outcome, previous.ending_proof
    return True


def failure_overlaps(candidate: dict, value: Observation) -> bool:
    """A reset's final clean frame may also be the verified arena entry."""
    if value.start is None or value.victory is None:
        return False
    if candidate["end"] == value.start and verified_entry(value):
        return False
    return candidate["start"] <= value.victory + value.postroll and value.start <= candidate["end"]


def validate_observation(
    data: dict, start: float, end: float, duration: float, frame_rate: float = 60
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
    candidates = []
    for candidate in value.candidates:
        # An isolated event at a labelled frame is useful evidence, not a range
        # that should abort an otherwise valid full-VOD analysis.
        if start <= candidate.start == candidate.end < end:
            candidate.end = min(end, candidate.start + 1 / frame_rate)
            candidate.victory = None
            if candidate.kind != "death_retry":
                candidate.kind, candidate.confidence = "unknown", "low"
            candidate.warnings.append("單點事件保留為待確認標註，不能作為完整挑戰。")
        if (not start <= candidate.start <= end or not start <= candidate.end <= end
                or any(not start <= e.time <= end for e in candidate.evidence)):
            raise ValueError("候選標註時間超出分析範圍。")
        if (candidate.start >= candidate.end
                or (candidate.victory is not None and not candidate.start < candidate.victory <= candidate.end)):
            if candidate.kind == "death_retry":
                raise ValueError("死亡／重試標註範圍無效，需重新確認。")
            proof, identity, window = value.ending_proof, candidate.encounter, candidate.ending_window
            combat = proof.last_combat if proof and proof.phase == "unresolved" else None
            anchors = [e for e in identity.evidence if start <= e.time <= combat.time] if combat and identity else []
            if (combat and window and identity and identity.status == "confirmed" and identity.signal != "none"
                    and anchors and candidate.boss == value.boss
                    and start <= window.start <= combat.time < window.end <= end
                    and window.every > 0
                    and any(abs(e.time - combat.time) <= .05 for e in candidate.evidence)
                    and (not value.outcome or value.outcome.player != "defeated")):
                # Discard the malformed range, but keep independently labelled
                # boss/combat facts as a NEW, unverified ending investigation.
                # Full-source coarse samples are at most 30 seconds apart; do
                # not chase a much later cinematic/map instead of this gap.
                candidate.id = f"recovered_{round(combat.time * frame_rate)}"
                candidate.replaces = []
                candidate.start = min(e.time for e in anchors)
                candidate.end = min(window.end, combat.time + 30)
                candidate.victory, candidate.confidence = None, "low"
                candidate.kind = "possible_win" if candidate.kind == "possible_win" else "fight"
                candidate.evidence = [anchors[0], combat]
                candidate.ending_window = SampleRequest(start=combat.time, end=candidate.end, every=2)
                candidate.warnings.append("原候選範圍矛盾；僅保留首領與最後交戰證據，結局與進場尚未驗證。")
                value.warnings.append("候選範圍矛盾；已保留有畫面證據的待查結局，不能視為成功挑戰。")
            else:
                value.warnings.append("已略過範圍矛盾的候選標註；此標註不能作為完整挑戰。")
                continue
        if candidate.ending_window and (not start <= candidate.ending_window.start < candidate.ending_window.end <= end
                                       or candidate.ending_window.every <= 0):
            raise ValueError("候選結局檢查範圍無效。")
        candidates.append(candidate)
    value.candidates = candidates
    identities = [value.encounter] + [c.encounter for c in value.candidates]
    if any(not start <= e.time <= end for identity in identities if identity for e in identity.evidence):
        raise ValueError("首領身份證據超出分析範圍。")
    if value.entry_proof and not start <= value.entry_proof.time <= end:
        raise ValueError("進場證據超出分析範圍。")
    if value.ending_proof and any(not start <= e.time <= end for e in
                                (value.ending_proof.last_combat, value.ending_proof.first_defeat) if e):
        raise ValueError("勝利轉折證據超出分析範圍。")
    if value.entry_status == "clean" and not verified_entry(value):
        value.entry_status = "unknown"
        value.warnings.append("尚未提供競技場進場或首次戰鬥證據；重生點不能當作成功挑戰起點。")
    if value.status == "candidate" and (
        value.start is None
        or value.victory is None
        or not start <= value.start < value.victory <= end
        or value.victory + value.postroll > duration
    ):
        raise ValueError("模型傳回的剪輯範圍無效。")
    return value
