"""Packet-based visual review through the user's authenticated Codex CLI.

Python owns media extraction and state. Codex receives images and returns a typed
observation or a request for another packet; it never owns cutting or exporting.
"""

from __future__ import annotations

import json
import hashlib
import math
import subprocess
import threading
import time
from bisect import bisect_left
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from .process import resolve_tool_command
from .web_store import Store
from .codex_runtime import CodexCallError, execute
from .candidate_registry import CandidateRegistry
from .review_progress import ReviewTracker, overlaps
from .review_prompt import review_prompt
from .usage import record_usage

MODEL = "gpt-5.6-luna"
MAX_CALLS = None  # No automatic session budget; callers may cancel at any time.
MAX_STALLED_REFINEMENTS = 3
MAX_DETAIL_WINDOW = 4.0  # Localize longer transitions before frame-level review.
SAMPLE_INTERVALS = (1 / 60, .1, .5, 1, 2, 5, 10, 15, 30, 60, 90)
MAX_REQUEST_FRAMES = 1_000_000  # Guard the eager packets() helper, not the lazy review queue.
PACKET_SIZE = 120  # Two seconds of 60fps context; not a session/analysis limit.
SEARCH_PACKET_SIZE = 60  # Smaller discovery pages retain short early encounters.
CONTINUITY_PACKET_SIZE = 24  # Two sheets / 11.5 seconds at 0.5s; avoid skipping reset sequences.
HEARTBEAT_INTERVAL = 5
MODEL_RETRY_DELAYS = (10, 30)
MODEL_CALL_TIMEOUT = 180  # A stalled provider call must not hold a job forever.


class AnalysisProgress:
    """Persist real activity separately from the worker's liveness heartbeat."""

    def __init__(self, store: Store, job_id: str):
        self.store, self.job_id = store, job_id
        self.activity: list[dict] = []
        self.round_effort = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)

    def __enter__(self):
        self.report("starting", "正在準備分析", frames=0, rounds=0)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()

    def heartbeat(self):
        while not self.stop.wait(HEARTBEAT_INTERVAL):
            self.store.patch("jobs", self.job_id, heartbeat_at=time.time())

    def report(self, phase: str, message: str, **fields):
        self.round_effort = fields.get("round_effort", self.round_effort)
        now = time.time()
        if not self.activity or self.activity[-1]["message"] != message:
            self.activity = (self.activity + [{"time": now, "message": message}])[-12:]
        self.store.patch(
            "jobs", self.job_id, phase=phase, stage=message,
            heartbeat_at=now, last_activity_at=now, activity=self.activity, **fields,
        )

    def codex_event(self, event: dict):
        kind = event.get("type")
        message = {
            "thread.started": "Codex 已啟動，等待模型回應",
            "turn.started": "Codex 已開始本輪判讀",
            "turn.completed": "Codex 已完成本輪回應",
            "turn.failed": "Codex 回報本輪失敗",
            "error": "Codex 回報連線或執行問題",
        }.get(kind)
        if kind == "analysis.retry":
            message = event["message"]
        item = event.get("item")
        if kind in {"item.started", "item.updated", "item.completed"} and isinstance(item, dict):
            # Show activity categories, never raw reasoning, commands, or model text.
            message = {
                "reasoning": "Codex 正在判讀抽樣畫面",
                "agent_message": "Codex 正在整理判讀結果",
                "command_execution": "Codex 回報工具執行活動",
                "mcp_tool_call": "Codex 回報工具執行活動",
                "web_search": "Codex 回報搜尋活動",
                "plan": "Codex 正在更新分析步驟",
            }.get(item.get("type"), "收到 Codex 活動更新")
        if message:
            if self.round_effort:
                message += f"（{self.round_effort}）"
            self.report("analyzing", message)


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


def packets(start: float, end: float, every: float) -> list[tuple[float, float, float]]:
    if (
        not all(math.isfinite(x) for x in (start, end, every))
        or every <= 0
        or end < start
    ):
        raise ValueError("Invalid sampling request")
    count = math.floor((end - start) / every + 1e-6) + 1
    if count > MAX_REQUEST_FRAMES:
        raise ValueError("單一抽樣要求過大，請拆分範圍。")
    return [
        (
            start + offset * every,
            start + min(offset + PACKET_SIZE - 1, count - 1) * every,
            every,
        )
        for offset in range(0, count, PACKET_SIZE)
    ]


def extract_packet(
    source: Path, work: Path, request: tuple[float, float, float],
    *, on_frame: Callable[[int, int], None] | None = None,
    timeout: float = 120,
) -> tuple[list[Path], dict]:
    start, end, every = request
    if not all(math.isfinite(x) for x in request) or start < 0 or end < start or every <= 0:
        raise ValueError("Invalid sampling request")
    count = math.floor((end - start) / every + 1e-6) + 1
    if count > PACKET_SIZE:
        raise ValueError("抽樣封包超出畫面上限。")
    work.mkdir(parents=True, exist_ok=True)
    # A repeated invocation must never mistake old output for a successful seek.
    for old in work.glob("frame-*.jpg"):
        old.unlink()
    command = resolve_tool_command("ffmpeg")
    deadline = time.monotonic() + timeout
    frames: list[Path] = []

    def run(at: float, output: Path, filters: str, amount: int, duration: float | None = None):
        remaining = deadline - time.monotonic()
        detail = f"抽樣畫面擷取逾時（已完成 {len(frames)}/{count} 張），尚未進入本輪 AI 判讀。請稍後重試或縮小搜尋範圍。"
        if remaining <= 0:
            raise RuntimeError(detail)
        args = command + ["-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-threads", "2", "-ss", str(at), "-i", str(source),
            "-map", "0:v:0", "-an", "-sn", "-dn", "-filter_threads", "1"]
        if duration is not None:
            args += ["-t", str(duration)]
        args += ["-vf", filters, "-frames:v", str(amount), "-threads", "2", str(output)]
        try:
            completed = subprocess.run(args, capture_output=True, text=True,
                                       timeout=min(30, remaining) if amount == 1 else remaining,
                                       check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(detail) from None
        if completed.returncode:
            (work / "extraction-error.log").write_text(completed.stderr or "", encoding="utf-8")
            raise RuntimeError("無法擷取影片畫面，請確認來源可讀取；詳細原因已記錄於任務資料夾。")

    if every >= 5:
        # Input seeking decodes only from the preceding seek point to each target,
        # instead of decoding the entire intervening multi-minute interval.
        for i in range(count):
            frame = work / f"frame-{i + 1:03d}.jpg"
            run(start + i * every, frame, "scale=1920:-2", 1)
            if not frame.is_file() or not frame.stat().st_size:
                raise ValueError(f"來源在 {start + i * every:.2f} 秒沒有可供分析的畫面。")
            frames.append(frame)
            if on_frame:
                on_frame(len(frames), count)
    else:
        # Dense, short windows are cheaper to decode in one bounded pass.
        run(start, work / "frame-%03d.jpg",
            f"fps=1/{every}:start_time=0:round=up,scale=1920:-2", count, end - start + every)
        frames = sorted(work.glob("frame-*.jpg"))
        if len(frames) != count or any(not frame.stat().st_size for frame in frames):
            raise ValueError("抽樣畫面不完整，未送交 AI 判讀；請縮小範圍或確認來源。")
        if on_frame:
            on_frame(len(frames), count)
    manifest = {
        "start": start,
        "end": end,
        "every": every,
        "timestamps": [round(start + i * every, 4) for i in range(len(frames))],
    }
    # Exact byte duplicates carry no new visual information (e.g. a paused menu).
    # Never use perceptual similarity: small HUD/reward changes must remain visible.
    unique, first_by_hash, repeats = [], {}, {}
    for index, frame in enumerate(frames):
        digest = hashlib.sha256(frame.read_bytes()).digest()
        if digest in first_by_hash:
            representative = first_by_hash[digest]
            repeats.setdefault(str(manifest["timestamps"][representative]), []).append(manifest["timestamps"][index])
        else:
            first_by_hash[digest] = index
            unique.append((index, frame))
    if repeats:
        manifest["identical_frames"] = repeats
    manifest["unique_frames"] = len(unique)
    images = []
    # Every distinct frame remains visible in order. High-resolution anchors preserve small
    # HUD/reward text that overview grids alone can make unreadable.
    columns, cells, width, height = (
        (1, 1, 1920, 1108) if len(unique) <= 6 else (3, 12, 480, 300)
    )
    for offset in range(0, len(unique), cells):
        batch = unique[offset : offset + cells]
        sheet = Image.new(
            "RGB",
            (width * columns, height * math.ceil(len(batch) / columns)),
            "#111811",
        )
        draw = ImageDraw.Draw(sheet)
        for i, (index, frame) in enumerate(batch):
            x, y = (i % columns) * width, (i // columns) * height
            with Image.open(frame) as picture:
                tile = ImageOps.contain(picture, (width, height - 28))
                sheet.paste(tile, (x + (width - tile.width) // 2, y + 28))
            draw.text(
                (x + 8, y + 6),
                f"FRAME {index + 1:03d} | SOURCE {manifest['timestamps'][index]:.4f} sec",
                fill="white",
                font_size=17,
            )
        path = work / f"sheet-{offset // cells:02d}.jpg"
        sheet.save(path, quality=92)
        images.append(path)
    if len(unique) > 6:
        for index in sorted({unique[0][0], unique[len(unique) // 2][0], unique[-1][0]}):
            with Image.open(frames[index]) as frame:
                detail = Image.new("RGB", (frame.width, frame.height + 36), "#111811")
                detail.paste(frame, (0, 36))
                ImageDraw.Draw(detail).text((8, 6),
                    f"DETAIL | SOURCE {manifest['timestamps'][index]:.4f} sec | same frame, clearer HUD",
                    fill="white", font_size=22)
                path = work / f"detail-{index + 1:03d}.jpg"
                detail.save(path, quality=95)
                images.append(path)
    (work / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return images, manifest


def invoke_codex(
    work: Path, images: list[Path], prompt: str, timeout: float | None,
    *, on_event: Callable[[dict], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
    model: str = MODEL, effort: str | None = "medium",
) -> tuple[dict, dict]:
    deadline = time.monotonic() + timeout if timeout is not None else None
    schema = Observation.model_json_schema()
    schema["required"].append("suspicious_windows")
    schema["required"].append("candidates")
    schema["required"].append("review_complete")
    schema["required"].append("entry_status")
    schema["required"].append("outcome")
    schema["$defs"]["CandidateSegment"]["required"].append("replaces")
    schema["$defs"]["CandidateSegment"]["properties"]["replaces"].pop("default", None)
    for field in ("suspicious_windows", "candidates", "review_complete", "entry_status", "outcome"):
        schema["properties"][field].pop("default", None)
    for attempt in range(len(MODEL_RETRY_DELAYS) + 1):
        # Keep every failed attempt's diagnostics. Reuse extracted images and
        # exactly the same model/effort; connection probes and chat do not retry.
        attempt_work = work if attempt == 0 else work / f"retry-{attempt}"
        try:
            remaining = max(.001, deadline - time.monotonic()) if deadline is not None else None
            result = execute(attempt_work, images, prompt, remaining, model=model,
                             schema=schema, effort=effort, on_event=on_event, on_usage=on_usage)
        except CodexCallError as exc:
            if not exc.retryable or attempt == len(MODEL_RETRY_DELAYS):
                message = str(exc) + (f" 已重試 {attempt} 次仍未恢復。" if attempt else "")
                raise CodexCallError(message + " 已保留分析進度，可稍後接續。",
                                     kind=exc.kind, retryable=exc.retryable) from exc
            delay = MODEL_RETRY_DELAYS[attempt]
            if deadline is not None and deadline - time.monotonic() <= delay:
                raise CodexCallError(str(exc) + " 本輪等待額度已用完，已保留進度，可稍後接續。",
                                     kind=exc.kind, retryable=exc.retryable) from exc
            if on_event:
                on_event({"type": "analysis.retry", "message":
                    f"{exc} {delay} 秒後重試本輪（{attempt + 1}/{len(MODEL_RETRY_DELAYS)}），已完成的判讀會保留。"})
            time.sleep(delay)
            continue
        if attempt:
            (work / "response.json").write_text(result["reply"], encoding="utf-8")
        return json.loads(result["reply"]), result["usage"]


def run_analysis(store: Store, job: dict, project: dict):
    store.patch("jobs", job["id"], usage_tracked=True)
    with AnalysisProgress(store, job["id"]) as progress:
        _run_analysis(store, job, project, progress)


def missing_ranges(start: float, end: float, every: float, history: list[dict]):
    """Subtract observed intervals on the request grid without losing an endpoint.

    Density is a coverage guarantee, not proof of every intervening video frame.
    Integer indices avoid duplicate joins and floating-point micro-gaps.
    """
    count = math.floor((end - start) / every + 1e-6) + 1
    tolerance = .00005 if every <= 1 / 60 + .00005 else 1e-6
    intervals = []
    for item in history:
        packet = item["packet"]
        if packet["every"] > every + tolerance:
            continue
        first = max(0, math.ceil((packet["start"] - start) / every - 1e-6))
        last = min(count - 1, math.floor((packet["end"] - start) / every + 1e-6))
        if first <= last:
            intervals.append((first, last))
    cursor = 0
    for first, last in sorted(intervals):
        if first > cursor:
            yield start + cursor * every, start + (first - 1) * every
        cursor = max(cursor, last + 1)
    if cursor < count:
        yield start + cursor * every, start + (count - 1) * every


def normalized_request(start: float, end: float, every: float):
    """Use one 60fps grid; sub-frame samples add no evidence."""
    if not all(math.isfinite(x) for x in (start, end, every)) or every <= 0 or end < start:
        raise ValueError("Invalid sampling request")
    if every <= 1 / 60 + .00005:
        every = 1 / 60
        grid_start = math.ceil(start * 60 - 1e-4) / 60
        grid_end = math.floor(end * 60 + 1e-4) / 60
        start, end = (grid_start, grid_end) if grid_start <= grid_end else (start, start)
    return start, end, every


def inspection_request(start: float, end: float, every: float):
    if not all(math.isfinite(x) for x in (start, end, every)) or every <= 0 or end < start:
        raise ValueError("Invalid sampling request")
    # Keep model-requested density changes finite without altering the host's
    # existing coarse grid (also used when resuming a checkpoint).
    every = max((step for step in SAMPLE_INTERVALS if step <= every + .00005), default=1 / 60)
    # Broad requests first locate transitions at 0.5s; the model can then name
    # the short windows that actually need frame-level evidence.
    if end - start > MAX_DETAIL_WINDOW:
        every = max(.5, every)
    return normalized_request(start, end, every)


def enqueue_unseen(queue: list, history: list, request: tuple, purpose: str, scope: str | None = None):
    a, b, every = normalized_request(*request)
    # Pending denser work also covers requests; don't queue alternate tilings.
    pending = [{"packet": {"start": q[0], "end": q[1], "every": q[2]}} for q in queue]
    for start, end in missing_ranges(a, b, every, history + pending):
        queue.append([start, end, every, purpose] + ([scope] if scope is not None else []))


def next_unseen(queue: list, history: list):
    """Recheck at execution time and return only the next uncovered packet."""
    while queue:
        a, b, every, purpose, *scope = queue.pop(0)
        gaps = list(missing_ranges(a, b, every, history))
        if not gaps:
            continue
        first, last = gaps[0]
        size = CONTINUITY_PACKET_SIZE if purpose in {"dense", "continuity"} else PACKET_SIZE
        stop = min(last, first + (size - 1) * every)
        rest = first + size * every
        remainder = ([[rest, last, every, purpose, *scope]] if rest <= last + 1e-6 else [])
        queue[:0] = remainder + [[x, y, every, purpose, *scope] for x, y in gaps[1:]]
        return ((first, stop, every), purpose, *scope)
    return None


def required_reviews(last: Observation | None, start: float, end: float, duration: float):
    if last is None:
        return []
    windows = []
    if (last.start is not None and last.victory is not None
            and start <= last.start < last.victory <= end
            and last.victory + last.postroll <= duration):
        finish = min(end - 1 / 60, last.victory + last.postroll)
        # Resolve the endpoints first, then reuse the denser continuity pass for
        # the 2s requirement rather than decoding the whole fight twice.
        for at in (last.start, last.victory):
            windows.append((max(start, at - 2), min(end - 1 / 60, at + 2), .1, "boundaries"))
        windows += [(last.start, finish, 0.5, "dense"),
                    (last.start, finish, 2.0, "continuity")]
    for sample in last.suspicious_windows:
        if start <= sample.start <= sample.end < end:
            windows.append((*inspection_request(sample.start, sample.end, sample.every), "suspicious"))
    # Stable source-frame boundaries also matter for the 2s/0.5s passes. Tiny
    # model timestamp shifts must not create an endless new leading/trailing gap.
    return [(*normalized_request(a, b, 1 / 60)[:2], every, purpose)
            for a, b, every, purpose in windows]


def affects_preferred(a: float, b: float, observation: Observation | None) -> bool:
    return bool(observation and observation.start is not None and observation.victory is not None
                and overlaps(a, b, observation.start, observation.victory + observation.postroll))


def rejected_context(a: float, b: float, observation: Observation | None, registry: CandidateRegistry) -> bool:
    """Keep rejected footage visible without micro-inspecting every earlier death."""
    return not affects_preferred(a, b, observation) and any(
        c["kind"] == "death_retry" and c["confidence"] == "high"
        and c["start"] <= a <= b <= c["end"] for c in registry.records.values())


def packet_effort(selected: str | None, policy: str, purpose: str,
                  request: tuple, last: Observation | None) -> str | None:
    """Use the selected effort as a ceiling; ambiguity receives that full effort."""
    if policy != "adaptive" or selected not in {"xhigh", "max"}:
        return selected
    if (purpose in {"suspicious", "outcome"} and request[1] - request[0] <= MAX_DETAIL_WINDOW) or (
            purpose != "search" and last and any(
                w.end - w.start <= MAX_DETAIL_WINDOW and overlaps(request[0], request[1], w.start, w.end)
                for w in last.suspicious_windows)):
        return selected
    return "high"


def _run_analysis(store: Store, job: dict, project: dict, progress: AnalysisProgress):
    bounds = job["analysis"]
    model = bounds.get("model", MODEL)
    effort = bounds.get("effort", "medium")
    effort_policy = bounds.get("effort_policy", "adaptive")
    start, end = bounds["start"], bounds["end"]
    base = store.root / "runs" / "web" / project["id"] / "codex"
    work = base / job["id"]
    work.mkdir(parents=True, exist_ok=True)
    source = store.root / project["source"]
    stat = source.stat()
    identity = {"source": project["source"], "size": stat.st_size, "mtime": stat.st_mtime_ns,
                "start": start, "end": end, "model": model, "effort": effort}
    history, usage, queue = [], {}, []
    candidate_origin = job["id"]
    registry = CandidateRegistry(candidate_origin)
    last = None
    tracker = ReviewTracker(limit=MAX_STALLED_REFINEMENTS)
    legacy_refinement_closed = False
    focus_id = None
    entry_plan = {}
    closed_focus = {}
    resume = bounds.get("resume_from")
    if resume:
        saved = json.loads((base / resume / "checkpoint.json").read_text(encoding="utf-8"))
        if saved.get("version") not in {1, 2, 3, 4} or saved["identity"] != identity:
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
        while at < end - 1 / 60:
            stop = min(end - 1 / 60, at + (SEARCH_PACKET_SIZE - 1) * every)
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
            if rejected or exhausted_entry or no_outcome or tracker.scopes[key]["exhausted"]:
                closed_focus[key] = "failed_attempt" if rejected else "unresolved"
                queue.clear()
                focus_id = None
                if last:
                    last = last.model_copy(update={"start": None, "victory": None,
                                                  "status": "uncertain", "entry_status": "unknown", "outcome": None})
        if focus_id is None and "primary" not in registry.aliases:
            # Coarse confidence measures encounter visibility, not clip quality.
            # Prefer an outcome-bearing or compact plausible encounter instead of
            # letting a long, conspicuous fight monopolize all subsequent work.
            choices = [c for c in registry.records.values()
                       if c["kind"] in {"possible_win", "fight"}
                       and (c["confidence"] != "low" or len(c["evidence"]) >= 2)
                       and (key := tracker.scope((c["start"], c["end"], .5), last, registry.records)) not in closed_focus
                       and not tracker.scopes[key]["exhausted"]]
            if choices:
                focus = min(choices, key=lambda c: (
                    (c["victory"] or c["end"]) - c["start"],
                    c["victory"] is None, c["kind"] != "possible_win", c["start"]))
                focus_id = focus["id"]
                # One bounded ending pass; the worker may then request a specific
                # entry/reset check. Provisional annotations for others persist.
                queue.clear()
                outcome_at = focus["victory"] if focus["victory"] is not None else focus["end"]
                outcome = (max(start, focus["start"], outcome_at - 45),
                           min(end - 1 / 60, outcome_at + 8), .5)
                key = tracker.scope(outcome, last, registry.records)
                enqueue_unseen(queue, history, outcome, "refine", key)
                if any(len(q) > 4 and q[4] == key for q in queue):
                    tracker.begin(key)
                    if not verified_outcome(last):
                        return
        focus = registry.records.get(focus_id)
        if focus and last and last.victory is not None and not focus["start"] < last.victory <= focus["end"]:
            last = last.model_copy(update={"start": None, "victory": None,
                                          "status": "uncertain", "entry_status": "unknown", "outcome": None})
        if last and last.victory is not None and not verified_outcome(last):
            # Legacy or dialogue-only wins need an explicit actor/outcome check
            # before spending time on entry and whole-fight continuity.
            request = (max(start, last.victory - 2), min(end - 1 / 60, last.victory + 2), .1)
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
            if not plan["reviewed"] or last.entry_status != "clean":
                if any(q[3] == "entry" for q in queue):
                    queue.sort(key=lambda q: q[3] != "entry")
                    return
                # Locate the last reset/entry backwards in useful context. Tiny
                # +/-2s windows cannot find an entry when the fight is underway.
                a, b = max(plan["floor"], plan["cursor"] - 60), plan["cursor"]
                if a <= b:
                    priority = []
                    enqueue_unseen(priority, history, (a, b, 2), "entry", focus_id)
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
            target = normalized_request(last.start, last.victory + last.postroll, 1 / 60)
            victory = round(last.victory * 60) / 60
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
                            and affects_preferred(c["start"], c["end"], last)
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
        data = {"version": 4, "identity": identity, "history": history, "usage": usage, "queue": queue,
                "focus_id": focus_id,
                "entry_plan": entry_plan,
                "closed_focus": closed_focus,
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
        progress.report("analyzing", f"第 {index} 輪：{labels[purpose]}，AI 正在判讀",
                        frames=used + len(manifest["timestamps"]), round_effort=round_effort,
                        effort_policy=effort_policy)
        prompt = review_prompt(manifest=manifest, purpose=purpose, start=start, end=end,
            duration=project["duration"], last=last, records=registry.records,
            history=history, exhausted=tracker.exhausted(), focus=registry.records.get(focus_id),
            review_target=bounds.get("review_target"))
        (packet_work / "prompt.txt").write_text(prompt, encoding="utf-8")
        model_started = time.monotonic()
        data, tokens = invoke_codex(packet_work, images, prompt, MODEL_CALL_TIMEOUT,
            on_event=progress.codex_event, model=model, effort=round_effort,
            on_usage=lambda value: record_usage(store, value, kind="analysis", model=model,
                                                project_id=project["id"], job_id=job["id"]))
        model_seconds = round(time.monotonic() - model_started, 3)
        observation = validate_observation(data, start, end, project["duration"])
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
        if (last and verified_outcome(last) and last.victory is not None
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
                        failed.id = f"failure_{round(failed.end * 60)}"
                        failed.replaces = []
                if focus_id in entry_plan:
                    entry_plan[focus_id]["reviewed"] = False
                    entry_plan[focus_id].pop("unresolved", None)
                entry_recheck = (max(start, failure.end - 2), min(last.victory, failure.end + 12), .5)
        if purpose == "outcome" and not verified_outcome(observation):
            observation.status, observation.victory = "uncertain", None
            observation.review_complete = True
        sampled_times = sorted(manifest["timestamps"] + [t for h in history for t in h["packet"]["timestamps"]])
        for evidence in observation.evidence + [e for c in observation.candidates for e in c.evidence]:
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
        history.append({"packet": manifest, "observation": last.model_dump(),
                        "purpose": purpose, "scope": scope[0] if scope else None,
                        "timing": {"extract_seconds": extraction_seconds, "model_seconds": model_seconds},
                        "prompt_characters": len(prompt), "image_count": len(images)})
        history[-1]["effort"] = round_effort
        if entry_recheck:
            enqueue_unseen(queue, history, entry_recheck, "entry", focus_id)
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
                    "warnings": observation.warnings, "evidence": [e.model_dump() for e in observation.evidence]}])
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
        queue[:] = [q for q in queue if list(missing_ranges(*q[:3], history))
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
    checks.insert(0, (start, end - 1 / 60, max(1, min(30, (end - start) / 24)), "search"))
    if any(list(missing_ranges(a, b, every, history)) for a, b, every, _ in checks):
        limits.append("候選的連續性、起訖或可疑畫面尚未完成細查。")
    result = last.model_dump(exclude={"sample_requests", "suspicious_windows"}) | {
        "candidates": public_candidates(), "exhausted_reviews": exhausted,
        "closed_investigations": closed_focus,
        "model": model, "project_id": project["id"], "usage": usage, "frames": used,
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
        entry_ok = last.entry_status == "clean" and (
            focus_id not in entry_plan or entry_plan[focus_id]["reviewed"])
        result["checks"]["entry"] = entry_ok
        if not entry_ok:
            limits.append("尚未確認最後一次成功挑戰的乾淨進場，不能接受從交戰中途開始的候選。")
            result["warnings"].append(limits[-1])
    if last.victory is not None:
        result["checks"]["outcome"] = verified_outcome(last)
        if not result["checks"]["outcome"]:
            limits.append("缺少玩家存活及明確敵方敗北／獎勵證據，字幕與讀取畫面不足以接受勝利。")
            result["warnings"].append(limits[-1])
    unresolved_preferred = any(affects_preferred(w.start, w.end, last) for w in last.suspicious_windows)
    if unresolved_preferred:
        result["warnings"].append("AI 仍保留未釐清的死亡／重試訊號，不能接受為成功候選。")
    known_failure = any(c["kind"] == "death_retry" and c["confidence"] == "high"
                        and affects_preferred(c["start"], c["end"], last)
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
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.patch("jobs", job["id"], result=result, resumable=bool(queue))
    progress.report("complete", "已保留進度，可接續細查" if queue else "分析完成，結果可供檢查")
