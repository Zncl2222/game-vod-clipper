"""Sampling grids, coverage accounting, review queues, and effort selection."""

from __future__ import annotations

import math

from .models import Observation
from .progress import overlaps
from .registry import CandidateRegistry

MAX_DETAIL_WINDOW = 4.0  # Localize longer transitions before frame-level review.
SAMPLE_INTERVALS = (1 / 60, .1, .5, 1, 2, 5, 10, 15, 30, 60, 90)
MAX_REQUEST_FRAMES = 1_000_000  # Guard the eager packets() helper, not the lazy review queue.
PACKET_SIZE = 120  # Two seconds of 60fps context; not a session/analysis limit.
SEARCH_PACKET_SIZE = 60  # Smaller discovery pages retain short early encounters.
CONTINUITY_PACKET_SIZE = 24  # Two sheets / 11.5 seconds at 0.5s; avoid skipping reset sequences.


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
