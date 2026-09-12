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

from game_vod_clipper.codex_analysis import PACKET_SIZE, missing_ranges, run_analysis
from game_vod_clipper.process import resolve_tool_command
from game_vod_clipper.web_store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--effort", choices=("xhigh", "max"), default="xhigh")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    probe = subprocess.run(resolve_tool_command("ffprobe") + ["-v", "error", "-show_format",
        "-show_streams", "-of", "json", str(source)], check=True, capture_output=True, text=True)
    metadata = json.loads(probe.stdout)
    duration = float(metadata["format"]["duration"])
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    parent = Path(__file__).resolve().parents[1] / "runs" / "benchmarks"
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"luna-{args.effort}-", dir=parent))
    repo = Path(__file__).resolve().parents[1]
    fingerprint = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in [repo / "src/game_vod_clipper/codex_analysis.py",
                                repo / "src/game_vod_clipper/candidate_registry.py",
                                repo / "skills/game-vod-boss-clipper/SKILL.md"]}
    store = Store(root)
    project = {"id": "sample", "source": str(source), "duration": duration}
    job = {"id": "review", "project_id": "sample", "kind": "analyze", "status": "running",
           "analysis": {"start": 0, "end": duration, "model": "gpt-5.6-luna", "effort": args.effort}}
    store.put("projects", project)
    store.put("jobs", job)
    print(json.dumps({"benchmark": str(root), "model": "gpt-5.6-luna", "effort": args.effort,
                      "duration": duration, "fps": video.get("avg_frame_rate")}), flush=True)
    started = time.monotonic()
    error = None
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
    metrics = {"model": "gpt-5.6-luna", "effort": args.effort, "duration": duration,
               "packet_size": PACKET_SIZE, "implementation_sha256": fingerprint,
               "elapsed_seconds": round(time.monotonic() - started, 2), "error": error,
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
