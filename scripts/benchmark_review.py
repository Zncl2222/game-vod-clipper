"""Opt-in live Luna review benchmark; uses the signed-in Codex account.

Run with: uv run python scripts/benchmark_review.py VIDEO --effort xhigh
Media and state remain in an isolated runs/benchmarks directory. No round/time cap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from game_vod_clipper.codex_analysis import PACKET_SIZE, SEARCH_PACKET_SIZE, missing_ranges, run_analysis
from game_vod_clipper.candidate_registry import CandidateRegistry
from game_vod_clipper.process import resolve_tool_command
from game_vod_clipper.web_store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--effort", choices=("high", "xhigh", "max"), default="xhigh")
    parser.add_argument("--effort-policy", choices=("adaptive", "fixed"), default="adaptive")
    parser.add_argument("--resume-root", type=Path, help="Reuse this benchmark checkpoint with the current harness")
    parser.add_argument("--coarse-from", type=Path, help="New benchmark using only a previous benchmark's completed coarse observations")
    args = parser.parse_args()
    if args.resume_root and args.coarse_from:
        parser.error("--resume-root and --coarse-from are mutually exclusive")
    source = args.source.resolve(strict=True)
    probe = subprocess.run(resolve_tool_command("ffprobe") + ["-v", "error", "-show_format",
        "-show_streams", "-of", "json", str(source)], check=True, capture_output=True, text=True)
    metadata = json.loads(probe.stdout)
    duration = float(metadata["format"]["duration"])
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    parent = Path(__file__).resolve().parents[1] / "runs" / "benchmarks"
    parent.mkdir(parents=True, exist_ok=True)
    root = args.resume_root.resolve(strict=True) if args.resume_root else Path(tempfile.mkdtemp(prefix=f"luna-{args.effort}-", dir=parent))
    repo = Path(__file__).resolve().parents[1]
    fingerprint = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in [repo / "src/game_vod_clipper/codex_analysis.py",
                                repo / "src/game_vod_clipper/candidate_registry.py",
                                repo / "src/game_vod_clipper/review_prompt.py",
                                repo / "src/game_vod_clipper/review_progress.py",
                                repo / "src/game_vod_clipper/codex_runtime.py",
                                repo / "skills/game-vod-boss-clipper/SKILL.md"]}
    if args.resume_root and (root / "metrics.json").exists():
        (root / "metrics.json").rename(root / f"metrics-before-resume-{time.time_ns()}.json")
    store = Store(root)
    if args.coarse_from:
        prior = args.coarse_from.resolve(strict=True) / "runs/web/sample/codex/review/checkpoint.json"
        seed = json.loads(prior.read_text())
        coarse = [h for h in seed["history"] if h["purpose"] == "search"]
        if not coarse:
            parser.error("The source benchmark has no completed coarse observations")
        registry = CandidateRegistry("review")
        for h in coarse:
            registry.update(h["observation"].get("candidates", []))
        checkpoint = root / "runs/web/sample/codex/review/checkpoint.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text(json.dumps({"version": 4, "identity": seed["identity"],
            "history": coarse, "usage": {}, "queue": [], "registry": registry.snapshot(),
            "candidate_origin": "review"}, ensure_ascii=False))
        (root / "coarse-provenance.json").write_text(json.dumps({
            "source_checkpoint": str(prior), "source_checkpoint_sha256": hashlib.sha256(prior.read_bytes()).hexdigest(),
            "reused_rounds": len(coarse), "note": "Only discovery observations reused; refinement starts fresh."}, indent=2))
    project = {"id": "sample", "source": str(source), "duration": duration}
    job = {"id": "review", "project_id": "sample", "kind": "analyze", "status": "running",
           "analysis": {"start": 0, "end": duration, "model": "gpt-5.6-luna", "effort": args.effort,
                        "effort_policy": args.effort_policy}}
    if args.resume_root or args.coarse_from:
        job["analysis"]["resume_from"] = "review"
    store.put("projects", project)
    store.put("jobs", job)
    print(json.dumps({"benchmark": str(root), "model": "gpt-5.6-luna", "effort": args.effort,
                      "duration": duration, "fps": video.get("avg_frame_rate")}), flush=True)
    started = time.monotonic()
    error = None
    before_rounds = 0
    before_path = root / "runs/web/sample/codex/review/checkpoint.json"
    if (args.resume_root or args.coarse_from) and before_path.exists():
        before_rounds = len(json.loads(before_path.read_text()).get("history", []))
        pending_round = before_path.parent / f"round-{before_rounds + 1:04d}"
        if pending_round.exists():
            archive = before_path.parent / "interrupted"
            archive.mkdir(exist_ok=True)
            pending_round.rename(archive / f"{pending_round.name}-{time.time_ns()}")
    try:
        run_analysis(store, job, project)
        store.patch("jobs", "review", status="succeeded")
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
        store.patch("jobs", "review", status="failed", error=error)
    work = root / "runs/web/sample/codex/review"
    saved = json.loads((work / "checkpoint.json").read_text()) if (work / "checkpoint.json").exists() else {}
    history = saved.get("history", [])
    repeated = []
    for i, item in enumerate(history):
        p = item["packet"]
        if not list(missing_ranges(p["start"], p["end"], p["every"], history[:i])):
            repeated.append(i + 1)
    final = store.get("jobs", "review")
    candidates = final.get("candidates", [])
    groups = Counter((c["start"], c["end"], c["kind"]) for c in candidates)
    metrics = {"model": "gpt-5.6-luna", "effort": args.effort, "effort_policy": args.effort_policy, "duration": duration,
               "packet_size": PACKET_SIZE, "search_packet_size": SEARCH_PACKET_SIZE, "implementation_sha256": fingerprint,
               "elapsed_seconds": round(time.monotonic() - started, 2), "error": error,
               "coarse_from": str(args.coarse_from) if args.coarse_from else None,
               "resumed_after_round": before_rounds,
               "round_timing": [h.get("timing", {}) for h in history],
               "prompt_characters": [h.get("prompt_characters") for h in history],
               "image_count": [h.get("image_count") for h in history],
               "round_efforts": [h.get("effort", args.effort) for h in history],
               "rounds": len(history), "frames": sum(len(h["packet"]["timestamps"]) for h in history),
               "candidates": len(candidates), "duplicate_ranges": sum(n - 1 for n in groups.values()),
               "fully_covered_rounds": repeated, "pending_ranges": len(saved.get("queue", [])),
               "result": final.get("result"), "usage": saved.get("usage", {})}
    (root / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
