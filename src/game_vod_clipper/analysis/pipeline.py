"""Packet-based visual review orchestration and durable checkpoints."""

from __future__ import annotations

import json
import time
from bisect import bisect_left
from functools import partial

from ..codex.usage import record_usage
from ..storage.locations import media_path, project_work
from ..storage.store import Store
from .activity import AnalysisProgress
from .client import MODEL, MODEL_CALL_TIMEOUT, invoke_codex
from .extraction import extract_packet
from .game_profiles import GameProfiles
from .models import Observation
from .progress import ReviewTracker, overlaps
from .prompt import review_prompt
from .registry import CandidateRegistry
from . import sampling
from .sampling import (
    PACKET_SIZE,
    SEARCH_PACKET_SIZE,
    affects_preferred,
    missing_ranges,
    next_unseen,
    packet_effort,
    rejected_context,
)
from .validation import (failure_overlaps, localized_ending, preserve_verified_ending, validate_observation,
                         verified_encounter, verified_entry, verified_outcome)
from .verification import verification_reason

MAX_CALLS = None  # No automatic session budget; callers may cancel at any time.
MAX_STALLED_REFINEMENTS = 3


def run_analysis(store: Store, job: dict, project: dict):
    store.patch("jobs", job["id"], usage_tracked=True)
    with AnalysisProgress(store, job["id"]) as progress:
        _run_analysis(store, job, project, progress)


def _run_analysis(store: Store, job: dict, project: dict, progress: AnalysisProgress):
    bounds = job["analysis"]
    model = bounds.get("model", MODEL)
    effort = bounds.get("effort", "medium")
    effort_policy = bounds.get("effort_policy", "adaptive")
    verification_model = bounds.get("verification_model")
    verification_effort = bounds.get("verification_effort", "medium")
    start, end = bounds["start"], bounds["end"]
    frame_rate = project.get("frame_rate") or 60
    frame_step = 1 / frame_rate
    normalized_request = partial(sampling.normalized_request, frame_rate=frame_rate)
    inspection_request = partial(sampling.inspection_request, frame_rate=frame_rate)
    enqueue_unseen = partial(sampling.enqueue_unseen, frame_rate=frame_rate)
    required_reviews = partial(sampling.required_reviews, frame_rate=frame_rate)
    base = project_work(store.root, project) / "codex"
    work = base / job["id"]
    work.mkdir(parents=True, exist_ok=True)
    source = media_path(store.root, project["source"])
    stat = source.stat()
    identity = {"source": project["source"], "size": stat.st_size, "mtime": stat.st_mtime_ns,
                "start": start, "end": end, "model": model, "effort": effort,
                "review_revision": 10, "frame_rate": frame_rate, "effort_policy": effort_policy,
                "verification_model": verification_model, "verification_effort": verification_effort}
    profile = bounds.get("profile")
    if profile:
        identity["profile"] = profile["id"]
    references, reference_labels = GameProfiles(store.root).materialize(profile, work)
    history, usage, queue = [], {}, []
    candidate_origin = job["id"]
    registry = CandidateRegistry(candidate_origin)
    last = None
    tracker = ReviewTracker(limit=MAX_STALLED_REFINEMENTS)
    legacy_refinement_closed = False
    focus_id = None
    entry_plan = {}
    closed_focus = {}
    verification_reviews, model_usage = [], {}
    resume = bounds.get("resume_from")
    if resume:
        saved = json.loads((base / resume / "checkpoint.json").read_text(encoding="utf-8"))
        if saved.get("version") not in {1, 2, 3, 4, 5} or saved["identity"] != identity:
            raise ValueError("來源或分析設定已變更，請重新搜尋。")
        history, usage, queue = saved["history"], saved["usage"], saved["queue"]
        candidate_origin = saved.get("candidate_origin", resume)
        registry = CandidateRegistry(candidate_origin, saved.get("registry"))
        if "registry" not in saved:
            registry.update(list(saved.get("candidates", {}).values()))
        last = Observation.model_validate(history[-1]["observation"]) if history else None
        convergence = saved.get("convergence", {})
        tracker = ReviewTracker(convergence.get("scopes"), limit=MAX_STALLED_REFINEMENTS)
        legacy_refinement_closed = convergence.get("refinement_closed", False)
        focus_id = saved.get("focus_id")
        entry_plan = saved.get("entry_plan", {})
        closed_focus = saved.get("closed_focus", {})
        verification_reviews, model_usage = saved.get("verification_reviews", []), saved.get("model_usage", {})
        pending, queue = queue, []
        for q in pending:
            request = inspection_request(*q[:3]) if q[3] in {"refine", "suspicious"} else tuple(q[:3])
            scope = None
            if q[3] in {"refine", "suspicious"}:
                scope = q[4] if len(q) > 4 else tracker.scope(request, last, registry.records)
                if tracker.scopes[scope]["exhausted"]:
                    continue
                if not tracker.scopes[scope]["active"]:
                    tracker.begin(scope)
            enqueue_unseen(queue, history, request, q[3], scope)
    else:
        # Scan the entire selected VOD before accepting an encounter. A long scan
        # is queued lazily in bounded chunks, not silently truncated to 30 minutes.
        every = max(1, min(30, (end - start) / 24))
        at = start
        while at < end - frame_step:
            stop = min(end - frame_step, at + (SEARCH_PACKET_SIZE - 1) * every)
            queue.append([at, stop, every, "search"])
            at += SEARCH_PACKET_SIZE * every
    used = sum(len(h["packet"]["timestamps"]) for h in history)
    limits = []
    labels = {"search": "全片搜尋", "refine": "追加判讀", "continuity": "確認整場挑戰",
              "dense": "密集檢查連續性", "entry": "定位最後一次成功挑戰的進場", "outcome": "核對勝負雙方與結局證據", "boundaries": "確認起點與勝利", "suspicious": "複查死亡與重試訊號"}

    def schedule_required():
        nonlocal focus_id, last
        # Search all coarse pages first. Then complete the preferred attempt
        # before unrelated optional work, even while that work is still queued.
        queue[:] = [q for q in queue if q[3] not in {"continuity", "dense", "boundaries"}]
        if any(q[3] == "search" for q in queue):
            return
        focus = registry.records.get(focus_id)
        if focus:
            checked_outcome = any(h.get("scope") == focus_id and h["purpose"] in {"refine", "suspicious", "outcome"}
                                  for h in history)
            rejected = focus["kind"] == "death_retry" and focus["confidence"] == "high"
            exhausted_entry = entry_plan.get(focus_id, {}).get("unresolved", False)
            no_outcome = last and last.review_complete and last.victory is None and checked_outcome
            key = tracker.scope((focus["start"], focus["end"], .5), last, registry.records)
            ordinary = bool(last and last.encounter and last.encounter.status == "ordinary")
            ending_passes = [h for h in history if h.get("scope") == focus_id and h["purpose"] == "refine"]
            if (no_outcome and not rejected and not ordinary and not exhausted_entry
                    and ending_passes and len(ending_passes) < MAX_STALLED_REFINEMENTS):
                # A coarse page may mistake a later cinematic for the end of
                # combat. Inspect at most two earlier adjacent ending windows
                # before rejecting the encounter, without reopening the VOD.
                before = min(h["packet"]["start"] for h in ending_passes)
                priority = []
                request = (max(start, focus["start"] - 30, before - 58), before, .5)
                if request[0] < request[1]:
                    enqueue_unseen(priority, history, request, "refine", focus_id)
                if priority and not tracker.scopes[key]["exhausted"]:
                    queue[:0] = priority
                    tracker.begin(key)
                    return
            if rejected or ordinary or exhausted_entry or no_outcome or tracker.scopes[key]["exhausted"]:
                closed_focus[key] = "failed_attempt" if rejected else "unresolved"
                queue.clear()
                focus_id = None
                if last:
                    last = last.model_copy(update={"start": None, "victory": None,
                                                  "status": "uncertain", "entry_status": "unknown", "outcome": None,
                                                  "encounter": None, "entry_proof": None, "ending_proof": None})
        if focus_id is None and "primary" not in registry.aliases:
            # Coarse confidence measures encounter visibility, not clip quality.
            # Prefer an outcome-bearing or compact plausible encounter instead of
            # letting a long, conspicuous fight monopolize all subsequent work.
            choices = [c for c in registry.records.values()
                       if c["kind"] in {"possible_win", "fight"}
                       and (not c.get("encounter") or c["encounter"]["status"] != "ordinary")
                       and (c["confidence"] != "low" or len(c["evidence"]) >= 2)
                       and (key := tracker.scope((c["start"], c["end"], .5), last, registry.records)) not in closed_focus
                       and not tracker.scopes[key]["exhausted"]]
            if choices:
                focus = min(choices, key=lambda c: (
                    not (c.get("encounter") and c["encounter"]["status"] == "confirmed"),
                    c["kind"] != "possible_win", c["victory"] is None,
                    (c["victory"] or c["end"]) - c["start"], c["start"]))
                focus_id = focus["id"]
                # One bounded ending pass; the worker may then request a specific
                # entry/reset check. Provisional annotations for others persist.
                queue.clear()
                outcome_at = focus["victory"] if focus["victory"] is not None else focus["end"]
                hint = focus.get("ending_window")
                coarse_step = max((h["packet"]["every"] for h in history if h["purpose"] == "search"), default=30)
                ending_start = hint["start"] if hint else outcome_at - max(10, coarse_step)
                ending_end = hint["end"] if hint else outcome_at + (0 if focus["victory"] is not None else coarse_step)
                # One bounded packet includes the intervening ending and clean
                # follow-through. A long hint is localized near its final frame.
                outcome = (max(start, ending_start - 2, ending_end - 50),
                           min(end - frame_step, ending_end + 8), .5)
                key = tracker.scope(outcome, last, registry.records)
                enqueue_unseen(queue, history, outcome, "refine", key)
                if any(len(q) > 4 and q[4] == key for q in queue):
                    tracker.begin(key)
                    # Coarse post-fight evidence establishes a hypothesis, not
                    # the defeat's onset. Always inspect its ending before entry
                    # work can purge this queued localization pass.
                    if last:
                        last = last.model_copy(update={"status": "uncertain", "start": focus["start"],
                            "victory": focus["victory"], "boss": focus["boss"], "outcome": None,
                            "entry_status": "unknown", "entry_proof": None, "encounter": None,
                            "review_complete": False, "ending_proof": None})
                    return
        focus = registry.records.get(focus_id)
        if focus and last and localized_ending(last) and last.start is None and last.victory is not None:
            # A localized win with an unknown entrance is actionable. The
            # candidate's start is only the backward-search context, never a
            # clean opening; mandatory entry review must still establish it.
            last = last.model_copy(update={"start": focus["start"], "status": "uncertain",
                                           "entry_status": "unknown", "entry_proof": None})
        if focus and last and localized_ending(last) and last.victory is not None:
            # Coarse annotations often end at the last combat frame. A local
            # ending check can establish the victory in the following gap.
            ending_limit = (focus.get("ending_window") or {}).get("end", focus["end"] + 30) + 8
            ending_floor = min(focus["start"], (focus.get("ending_window") or {}).get("start", focus["start"] - 30))
            if (last.start is not None and start <= last.start < last.victory
                    and ending_floor <= last.victory <= min(end, ending_limit)):
                focus["start"] = min(focus["start"], last.start)
                focus["end"] = max(focus["end"], last.victory + last.postroll)
        if focus and last and last.victory is not None and not focus["start"] < last.victory <= focus["end"]:
            last = last.model_copy(update={"start": None, "victory": None,
                                          "status": "uncertain", "entry_status": "unknown", "outcome": None,
                                          "encounter": None, "entry_proof": None, "ending_proof": None})
        if last and last.victory is not None and not localized_ending(last):
            # Legacy or dialogue-only wins need an explicit actor/outcome check
            # before spending time on entry and whole-fight continuity.
            request = (max(start, last.victory - 2), min(end - frame_step, last.victory + 2), .1)
            priority = []
            enqueue_unseen(priority, history, request, "outcome", focus_id)
            if priority:
                queue[:0] = priority
                return
            last = last.model_copy(update={"status": "uncertain", "victory": None,
                                          "entry_status": "unknown"})
            queue.clear()
            return
        if focus and last and last.victory is not None and last.start is not None:
            plan = entry_plan.setdefault(focus_id, {
                "floor": max(start, min(focus["start"], last.start) - 30),
                "cursor": last.victory, "reviewed": False})
            if not plan["reviewed"] or not verified_entry(last):
                if any(q[3] == "entry" for q in queue):
                    queue.sort(key=lambda q: q[3] != "entry")
                    return
                if not plan["reviewed"] and verified_entry(last):
                    # Coverage from an ending/continuity packet is not an entry
                    # judgement. Reuse its evidence but ask once about the actual
                    # arena transition, even if all these frames were sampled.
                    priority = []
                    entry_history = [h for h in history if h["purpose"] == "entry"]
                    enqueue_unseen(priority, entry_history,
                        (max(start, last.start - 12), min(last.victory, last.start + 6), .5), "entry",
                        tracker.scope((last.start, last.victory, .5), last, registry.records))
                    if priority:
                        queue[:0] = priority
                        return
                # Locate the last reset/entry backwards in useful context. Tiny
                # +/-2s windows cannot find an entry when the fight is underway.
                while plan["cursor"] >= plan["floor"]:
                    a, b = max(plan["floor"], plan["cursor"] - 60), plan["cursor"]
                    priority = []
                    enqueue_unseen(priority, history, (a, b, 2), "entry",
                                   tracker.scope((a, b, 2), last, registry.records))
                    plan["cursor"] = a - 2
                    if priority:
                        queue[:0] = priority
                        return
                # The available entry context is exhausted; never validate a
                # mid-fight opening merely because native boundary scans ended.
                plan["unresolved"] = True
                queue.clear()
                return
        if (last and last.start is not None and last.victory is not None
                and start <= last.start < last.victory <= end
                and last.victory + last.postroll <= project["duration"]):
            target = normalized_request(last.start, last.victory + last.postroll, frame_step)
            victory = round(last.victory * frame_rate) / frame_rate
            if not tracker.stable_target(target, victory, last, registry.records):
                return
        for a, b, every, purpose in required_reviews(last, start, end, project["duration"]):
            if purpose == "suspicious":
                continue  # Scoped passes below own these, including exhaustion.
            gaps = list(missing_ranges(a, b, every, history))
            if gaps:
                a, b = gaps[0]
                priority = []
                enqueue_unseen(priority, history, (a, min(b, a + (PACKET_SIZE - 1) * every), every), purpose)
                queue[:0] = priority
                return
        # A useful verified attempt is the completion target. Other encounters
        # stay in the registry for review; their optional work cannot keep a
        # finished preferred clip trapped in a whole-VOD investigation.
        if (last and last.status == "candidate" and last.start is not None
                and last.victory is not None
                and not any(affects_preferred(w.start, w.end, last) for w in last.suspicious_windows)
                and not any(c["kind"] == "death_retry" and c["confidence"] == "high"
                            and failure_overlaps(c, last)
                            for c in registry.records.values())):
            queue[:] = [q for q in queue if affects_preferred(q[0], q[1], last)]

    def public_candidates():
        candidates = registry.public()
        for candidate in candidates:
            key = candidate["id"].split(":")[-1]
            scope = tracker.scopes.get(key, {})
            if scope.get("exhausted"):
                candidate["warnings"] = list(dict.fromkeys(candidate["warnings"] +
                    ["此遭遇的追加檢查未帶來新判斷，已結束細查；未解疑點保留供人工核對。"]
                ))
        return candidates

    def checkpoint():
        data = {"version": 5, "identity": identity, "history": history, "usage": usage, "queue": queue,
                "focus_id": focus_id,
                "entry_plan": entry_plan,
                "closed_focus": closed_focus,
                "verification_reviews": verification_reviews, "model_usage": model_usage,
                "convergence": {"scopes": tracker.scopes,
                                "refinement_closed": legacy_refinement_closed},
                "registry": registry.snapshot(), "candidate_origin": candidate_origin,
                "candidates": {c["id"]: c for c in public_candidates()}}
        temporary = work / "checkpoint.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(work / "checkpoint.json")
        store.patch("jobs", job["id"], resumable=True, candidates=public_candidates(),
                    exhausted_reviews=tracker.exhausted(),
                    superseded_candidates=registry.superseded_ids())

    schedule_required()
    checkpoint()
    calls = 0
    while MAX_CALLS is None or calls < MAX_CALLS:
        selected = next_unseen(queue, history)
        if selected is None:
            schedule_required()
            selected = next_unseen(queue, history)
        if selected is None:
            break
        calls += 1
        request, purpose, *scope = selected
        # Persist the in-flight packet too, so cancellation retries exactly this work.
        queue.insert(0, [*request, purpose, *scope])
        checkpoint()
        index = len(history) + 1
        progress.report("extracting", f"第 {index} 輪：{labels[purpose]}",
                        review_stage=purpose, current_round=index, rounds=len(history), frames=used,
                        sample_start=request[0], sample_end=request[1], sample_every=request[2],
                        pending_packets=len(queue))
        packet_work = work / f"round-{index:04d}"
        packet_work.mkdir(parents=True, exist_ok=True)
        extraction_started = time.monotonic()
        images, manifest = extract_packet(source, packet_work, request,
            timeout=180,
            on_frame=lambda done, total: progress.report("extracting",
                f"第 {index} 輪：{labels[purpose]}，已擷取 {done}/{total} 張", frames=used + done))
        extraction_seconds = round(time.monotonic() - extraction_started, 3)
        round_effort = packet_effort(effort, effort_policy, purpose, request, last)
        decision = verification_reason(purpose, request, last, None, verification_reviews) if focus_id else None
        round_model = verification_model if verification_model and decision else model
        if round_model != model:
            round_effort = verification_effort
            verification_reviews.append({"role": decision[0], "reason": decision[1], "model": round_model,
                                         "request": request, "round": index})
            checkpoint()
        progress.report("analyzing", f"第 {index} 輪：{labels[purpose]}，AI 正在判讀",
                        frames=used + len(manifest["timestamps"]), round_effort=round_effort,
                        round_model=round_model, verification_reviews=verification_reviews,
                        effort_policy=effort_policy)
        if round_model != model:
            progress.report("analyzing", f"局部 Sol 複查：{decision[1]}（最多三次）")
        prompt = review_prompt(manifest=manifest, purpose=purpose, start=start, end=end,
            duration=project["duration"], last=last, records=registry.records,
            history=history, exhausted=tracker.exhausted(), focus=registry.records.get(focus_id),
            review_target=bounds.get("review_target"),
            profile=profile and {"title": profile["title"], "notes": profile["notes"], "images": reference_labels})
        (packet_work / "prompt.txt").write_text(prompt, encoding="utf-8")
        model_started = time.monotonic()
        data, tokens = invoke_codex(packet_work, references + images, prompt, MODEL_CALL_TIMEOUT,
            on_event=progress.codex_event, model=round_model, effort=round_effort,
            on_usage=lambda value: record_usage(store, value, kind="analysis", model=round_model,
                                                project_id=project["id"], job_id=job["id"]))
        model_seconds = round(time.monotonic() - model_started, 3)
        observation = validate_observation(data, start, end, project["duration"], frame_rate)
        model_calls = [{"model": round_model, "effort": round_effort, "usage": tokens, "seconds": model_seconds}]
        decision = verification_reason(purpose, request, last, observation, verification_reviews)
        if verification_model and round_model == model and decision:
            verification_reviews.append({"role": decision[0], "reason": decision[1], "model": verification_model,
                                         "request": request, "round": index})
            checkpoint()
            progress.report("analyzing", f"局部 Sol 複查：{decision[1]}（最多三次）",
                            round_model=verification_model, round_effort=verification_effort,
                            verification_reviews=verification_reviews)
            verify_work = packet_work / "verification"
            verify_work.mkdir(exist_ok=True)
            verify_prompt = prompt + "\nCRITICAL RECHECK: " + decision[1] + (
                "\nIndependently inspect these SAME images. Correct the local hypothesis below; "
                "retain only visually supported facts. A transformation with continuing player control "
                "is not a death/reset. Checkpoint/runback is not arena entry.\nLOCAL HYPOTHESIS:\n") + json.dumps(data, ensure_ascii=False)
            (verify_work / "prompt.txt").write_text(verify_prompt, encoding="utf-8")
            at = time.monotonic()
            data, verify_tokens = invoke_codex(verify_work, references + images, verify_prompt, MODEL_CALL_TIMEOUT,
                on_event=progress.codex_event, model=verification_model, effort=verification_effort,
                on_usage=lambda value: record_usage(store, value, kind="analysis", model=verification_model,
                                                    project_id=project["id"], job_id=job["id"]))
            elapsed = round(time.monotonic() - at, 3)
            model_seconds += elapsed
            model_calls.append({"model": verification_model, "effort": verification_effort,
                                "usage": verify_tokens, "seconds": elapsed})
            tokens = {key: sum(call["usage"].get(key, 0) for call in model_calls)
                      for key in set(tokens) | set(verify_tokens)}
            observation = validate_observation(data, start, end, project["duration"], frame_rate)
        # Omitting a suspicion while looking elsewhere is not a resolution.
        # Nearby follow-through may explain a knockdown, but a distant victory
        # packet or another coarse page cannot erase a local failure signal.
        if last:
            for window in last.suspicious_windows:
                follow_through = any(request[0] <= e.time <= request[1]
                                     and window.start - 2 <= e.time <= window.end + 2
                                     for e in observation.evidence)
                local_check = ((overlaps(request[0], request[1], window.start, window.end) or follow_through)
                               and request[2] <= max(.5, window.every))
                if not local_check and window not in observation.suspicious_windows:
                    observation.suspicious_windows.append(window)
        entry_recheck = None
        # An earlier failed attempt invalidates the opening, not an independently
        # observed later victory. Keep those facts separate even when the worker
        # wrongly replaces its winning-encounter annotation with the earlier loss.
        earlier_failures = [c for c in observation.candidates
                            if c.kind == "death_retry" and c.confidence == "high"]
        if (last and localized_ending(last) and last.victory is not None
                and request[1] < last.victory - 2 and earlier_failures
                and purpose in {"entry", "dense", "continuity", "boundaries", "suspicious"}):
            failure = max(earlier_failures, key=lambda c: c.end)
            if (last.start is not None and last.start <= failure.end < last.victory
                    and failure.end <= request[1] + .05):
                observation.start = failure.end  # Tentative; never a clean entry yet.
                observation.victory, observation.outcome = last.victory, last.outcome
                observation.boss = last.boss
                observation.status, observation.entry_status = "uncertain", "unknown"
                observation.review_complete = False
                observation.summary = "已確認較早嘗試失敗；保留另有直接證據的勝利，重新定位最後一次重試後的起點。"
                for failed in earlier_failures:
                    if failed.id == focus_id or failed.replaces:
                        failed.id = f"failure_{round(failed.end * frame_rate)}"
                        failed.replaces = []
                if focus_id in entry_plan:
                    entry_plan[focus_id]["reviewed"] = False
                    entry_plan[focus_id].pop("unresolved", None)
                entry_recheck = (max(start, failure.end - 2), min(last.victory, failure.end + 12), .5)
        preserve_verified_ending(last, observation, request, purpose)
        if (purpose == "entry" and verified_entry(observation)
                and (not verified_entry(last) or not entry_plan.get(focus_id, {}).get("reviewed"))
                and not request[0] <= observation.entry_proof.time <= request[1]):
            observation.entry_status, observation.entry_proof = "unknown", None
            observation.warnings.append("本輪未觀察到新的進場證據，繼續向前定位競技場入口。")
        if (purpose == "outcome" and not localized_ending(observation)) or (
                purpose == "refine" and focus_id and observation.ending_proof
                and observation.ending_proof.phase == "already_over"):
            observation.status, observation.victory = "uncertain", None
            observation.review_complete = True
        sampled_times = sorted(manifest["timestamps"] + [t for h in history for t in h["packet"]["timestamps"]])
        identities = [observation.encounter] + [c.encounter for c in observation.candidates]
        evidence_items = (observation.evidence + [e for c in observation.candidates for e in c.evidence]
                          + [e for identity in identities if identity for e in identity.evidence]
                          + ([observation.entry_proof] if observation.entry_proof else []))
        if observation.ending_proof:
            evidence_items += [e for e in (observation.ending_proof.last_combat, observation.ending_proof.first_defeat) if e]
        for evidence in evidence_items:
            at = bisect_left(sampled_times, evidence.time)
            if not any(abs(t - evidence.time) <= 0.05 for t in sampled_times[max(0, at - 1):at + 1]):
                raise ValueError("模型引用的證據時間不符合實際抽樣畫面，請重試。")
        last = observation
        if purpose == "entry" and focus_id in entry_plan and not entry_recheck:
            entry_plan[focus_id]["reviewed"] = True
        queue.pop(0)
        used += len(manifest["timestamps"])
        for key, value in tokens.items():
            if isinstance(value, int):
                usage[key] = usage.get(key, 0) + value
        for call in model_calls:
            totals = model_usage.setdefault(call["model"], {})
            for key, value in call["usage"].items():
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
        history.append({"packet": manifest, "observation": last.model_dump(),
                        "purpose": purpose, "scope": scope[0] if scope else None,
                        "timing": {"extract_seconds": extraction_seconds, "model_seconds": model_seconds},
                        "prompt_characters": len(prompt), "image_count": len(images)})
        history[-1]["effort"] = round_effort
        history[-1]["model_calls"] = model_calls
        if entry_recheck:
            enqueue_unseen(queue, history, entry_recheck, "entry", tracker.scope(entry_recheck, last, registry.records))
        registry.update([candidate.model_dump() for candidate in observation.candidates])
        # Backward-compatible observations still produce a useful provisional range.
        # Preserve it even if a later packet has no winner or the execution stops.
        if (not observation.candidates and (not registry.records or "primary" in registry.aliases)
                and observation.start is not None and observation.victory is not None):
            if start <= observation.start < observation.victory <= end:
                registry.update([{"id": "primary", "start": observation.start,
                    "end": min(end, observation.victory + observation.postroll),
                    "victory": observation.victory, "kind": "possible_win",
                    "confidence": "medium" if observation.status == "candidate" else "low",
                    "boss": observation.boss, "summary": observation.summary,
                    "warnings": observation.warnings, "evidence": [e.model_dump() for e in observation.evidence],
                    "encounter": observation.encounter.model_dump() if observation.encounter else None}])
        if scope:
            tracker.observe(scope[0], observation, registry.records)
        # Resolved suspicions can discard their remaining packets. Unresolved
        # ones finish the existing pass before accepting any additional ranges.
        queue[:] = [q for q in queue if q[3] != "suspicious" or any(
            overlaps(q[0], q[1], w.start, w.end) for w in last.suspicious_windows)]
        if last.review_complete:
            queue[:] = [q for q in queue if q[3] != "refine"]
        # Priority checks can cover an optional pass while it waits. Close that
        # pass now, so stale queued work cannot suppress a newly requested check.
        queue[:] = [q for q in queue if list(missing_ranges(*q[:3],
                    [h for h in history if h["purpose"] == "entry"] if q[3] == "entry" else history))
                    and (q[3] not in {"refine", "suspicious"}
                         or not rejected_context(q[0], q[1], last, registry))]
        tracker.finish({q[4] for q in queue if len(q) > 4})
        pending_scopes = {key for key, value in tracker.scopes.items() if value["active"]}
        samples = ([] if last.review_complete or legacy_refinement_closed else last.sample_requests) + last.suspicious_windows
        for sample in samples:
            if not start <= sample.start <= sample.end < end or sample.every <= 0:
                limits.append("模型提出無效的追加抽樣範圍，尚需釐清。")
                continue
            focus = registry.records.get(focus_id)
            if focus and not overlaps(sample.start, sample.end, focus["start"] - 30, focus["end"] + 10):
                continue
            every = sample.every
            try:
                request = inspection_request(sample.start, sample.end, every)
                key = tracker.scope(request, last, registry.records)
                if (key in pending_scopes or tracker.scopes[key]["exhausted"]
                        or rejected_context(sample.start, sample.end, last, registry)):
                    continue
                before = len(queue)
                enqueue_unseen(queue, history, request,
                               "suspicious" if sample in last.suspicious_windows else "refine", key)
                if len(queue) > before and not tracker.scopes[key]["active"]:
                    tracker.begin(key)
            except ValueError:
                limits.append("追加抽樣要求過大，請指定較小的可疑區段繼續檢查。")
                continue
        schedule_required()
        checkpoint()
        coverage = [{"start": h["packet"]["start"], "end": h["packet"]["end"],
                     "every": h["packet"]["every"]} for h in history]
        store.patch("jobs", job["id"], model=model, usage=usage, frames=used, rounds=len(history),
                    used_models=list(model_usage), model_usage=model_usage, verification_reviews=verification_reviews,
                    coverage=coverage, evidence=[e.model_dump() for e in last.evidence],
                    pending_packets=len(queue))
        progress.report("validating", f"第 {index} 輪完成，{'接續檢查其他畫面' if queue else '正在整理結果'}")
    checkpoint()
    store.patch("jobs", job["id"], pending_packets=len(queue))
    if queue:
        limits.append("仍有畫面未完成判讀，請接續細查；目前範圍不能作為完成候選。")
    exhausted = tracker.exhausted()
    refinement_closed = legacy_refinement_closed or bool(exhausted)
    if legacy_refinement_closed or any(affects_preferred(w["start"], w["end"], last) for w in exhausted):
        limits.append("此候選的細查未帶來新判斷或起訖持續變動，已結束細查；未解疑點需人工核對或提供新線索。")
    if last is None:
        raise RuntimeError("沒有取得 Codex 分析結果。")
    checks = required_reviews(last, start, end, project["duration"])
    # A failure in a different encounter cannot invalidate a verified preferred
    # attempt. Its unresolved evidence remains visible in the review report.
    checks = [w for w in checks if w[3] != "suspicious" or last.start is None
              or last.victory is None or affects_preferred(w[0], w[1], last)]
    checks.insert(0, (start, end - frame_step, max(1, min(30, (end - start) / 24)), "search"))
    if any(list(missing_ranges(a, b, every, history)) for a, b, every, _ in checks):
        limits.append("候選的連續性、起訖或可疑畫面尚未完成細查。")
    result = last.model_dump(exclude={"sample_requests", "suspicious_windows"}) | {
        "candidates": public_candidates(), "exhausted_reviews": exhausted,
        "closed_investigations": closed_focus,
        "model": model, "project_id": project["id"], "usage": usage, "frames": used,
        "used_models": list(model_usage), "model_usage": model_usage, "verification_reviews": verification_reviews,
        "rounds": len(history), "reviewed": False, "can_continue": bool(queue),
        "review_complete": not queue,
        "completion_reason": "pending_review" if queue else "evidence_exhausted" if refinement_closed else "review_complete",
        "coverage": [{"start": h["packet"]["start"], "end": h["packet"]["end"],
                      "every": h["packet"]["every"]} for h in history],
        "checks": {purpose: not any(list(missing_ranges(a, b, every, history))
                    for a, b, every, name in checks if name == purpose)
                   for purpose in {w[3] for w in checks}},
        "warnings": list(dict.fromkeys(last.warnings + limits +
            ["已依抽樣密度檢查；抽樣間仍可能遺漏畫面，請完整預覽成功挑戰後再匯出。"])),
    }
    if focus_id in entry_plan or (last.start is not None and last.victory is not None):
        entry_ok = verified_entry(last) and (
            focus_id not in entry_plan or entry_plan[focus_id]["reviewed"])
        result["checks"]["entry"] = entry_ok
        if not entry_ok:
            limits.append("尚未確認最後一次成功挑戰的乾淨進場，不能接受從交戰中途開始的候選。")
            result["warnings"].append(limits[-1])
    if last.victory is not None:
        result["checks"]["ending"] = localized_ending(last) and last.victory + last.postroll <= end
        if not result["checks"]["ending"]:
            limits.append("尚未定位首次敗北及完整收尾；較晚的戰後狀態不能作為勝利時間，收尾必須位於已分析範圍。")
            result["warnings"].append(limits[-1])
        result["checks"]["encounter"] = verified_encounter(last)
        if not result["checks"]["encounter"]:
            limits.append("未確認這段是首領或決鬥；一般敵人擊殺不能作為成功首領候選。")
            result["warnings"].append(limits[-1])
        result["checks"]["outcome"] = verified_outcome(last)
        if not result["checks"]["outcome"]:
            limits.append("缺少玩家存活及明確敵方敗北／獎勵證據，字幕與讀取畫面不足以接受勝利。")
            result["warnings"].append(limits[-1])
    unresolved_preferred = any(affects_preferred(w.start, w.end, last) for w in last.suspicious_windows)
    if unresolved_preferred:
        result["warnings"].append("AI 仍保留未釐清的死亡／重試訊號，不能接受為成功候選。")
    known_failure = any(c["kind"] == "death_retry" and c["confidence"] == "high"
                        and failure_overlaps(c, last)
                        for c in registry.records.values())
    if last.start is not None and last.victory is not None:
        result["checks"]["failure_free"] = not (unresolved_preferred or known_failure)
    if known_failure:
        result["warnings"].append("此候選仍與已標註的死亡／重試片段重疊，需修正起點或釐清該標註，不能接受為成功候選。")
    if exhausted:
        result["warnings"].append(f"{len(exhausted)} 個區段的追加檢查未帶來新判斷，已結束細查並保留待確認結果。")
    if last.suspicious_windows:
        result["unresolved_windows"] = [w.model_dump() for w in last.suspicious_windows]
    if limits or unresolved_preferred or known_failure or (exhausted and last.status != "candidate"):
        result["status"] = "uncertain"
    if result["status"] == "candidate" and all(result["checks"].values()):
        focus = registry.records.get(focus_id) or registry.records.get(registry.aliases.get("primary"))
        if focus and focus["kind"] in {"possible_win", "fight"}:
            focus.update(start=result["start"], victory=result["victory"],
                         end=result["victory"] + result["postroll"], kind="possible_win",
                         encounter=last.encounter.model_dump())
            result["candidates"] = public_candidates()
            checkpoint()
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.patch("jobs", job["id"], result=result, resumable=bool(queue))
    progress.report("complete", "已保留進度，可接續細查" if queue else "分析完成，結果可供檢查")
