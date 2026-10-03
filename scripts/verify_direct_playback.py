"""Repeatable local QA: real yt-dlp download/merge, import timings, browser fixture.

Usage: uv run --extra web python scripts/verify_direct_playback.py --source FILE --port 8012
The supplied AV1/Opus VOD is read only. All artifacts live in a new runs/ folder.
The download fixture is served locally; this does not contact or upload to YouTube.
"""

import argparse
import functools
import hashlib
import json
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from yt_dlp import YoutubeDL

from game_vod_clipper.api.server import LocalServer
from game_vod_clipper.web import create_app
from game_vod_clipper.storage.store import Store
from game_vod_clipper.web_worker import probe, run
from game_vod_clipper.youtube.downloader import BROWSER_MERGE_FORMATS, quality_format


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *map(str, args)], check=True)


def packet_hash(path, stream):
    output = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", stream,
                                      "-show_packets", "-show_entries", "packet=data_hash",
                                      "-show_data_hash", "sha256", "-of", "csv=p=0", str(path)])
    # Some containers attach side-data to the first/last audio packet. Compare
    # only packet payload hashes, not timestamps or container-specific side-data.
    hashes = [part for line in output.decode().splitlines() for part in line.split(",") if part.startswith("SHA256:")]
    return {"packets": len(hashes), "sha256": hashlib.sha256("\n".join(hashes).encode()).hexdigest()}


def prepare(workspace, source):
    started = time.monotonic()
    store = Store(workspace)
    item = {"id": source.stem, "title": source.stem, "source": str(source.relative_to(workspace)),
            "ready": False, "thumbnails": [], "created": time.time()}
    job = {"id": item["id"] + "-prepare", "project_id": item["id"], "kind": "prepare", "status": "running"}
    store.put("projects", item)
    store.put("jobs", job)
    errors = []

    def work():
        try:
            run(workspace, job["id"])
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=work)
    worker.start()
    ready_seconds = None
    while worker.is_alive():
        if ready_seconds is None and store.get("projects", item["id"]).get("ready"):
            ready_seconds = time.monotonic() - started
        worker.join(.02)
    if errors:
        raise errors[0]
    finished = time.monotonic() - started
    store.patch("jobs", job["id"], status="succeeded")
    project = store.get("projects", item["id"])
    cache = workspace / "runs" / "web" / item["id"]
    assert not (cache / "preview.mp4").exists()
    return {"project_id": item["id"], "ready_seconds": round(ready_seconds or finished, 3),
            "thumbnails_seconds": round(finished, 3), "thumbnails": len(project["thumbnails"]),
            "cache_bytes": sum(p.stat().st_size for p in cache.glob("*.jpg")), "metadata": probe(source)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Existing AV1/Opus gameplay VOD")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    original = probe(args.source)
    if (original.get("video_codec"), original.get("audio_codec")) != ("av1", "opus"):
        parser.error("This fixture requires an existing AV1/Opus source.")
    root = Path(__file__).resolve().parents[1]
    workspace = Path(tempfile.mkdtemp(prefix="direct-playback-qa-", dir=root / "runs"))
    downloads, inputs = workspace / "downloads", workspace / "inputs"
    downloads.mkdir()
    inputs.mkdir()
    print(f"QA workspace: {workspace}", flush=True)
    # Short original-quality samples: no video/audio re-encoding.
    ffmpeg("-ss", "120", "-i", args.source.resolve(), "-t", "20", "-map", "0:v:0", "-c", "copy", inputs / "video.mp4")
    ffmpeg("-ss", "120", "-i", args.source.resolve(), "-t", "20", "-map", "0:a:0", "-c", "copy", inputs / "audio.webm")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(inputs))
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{http.server_port}"
    metadata = probe(inputs / "video.mp4")
    formats = [
        {"format_id": "original-av1", "url": address + "/video.mp4", "ext": "mp4",
         "vcodec": "av01.0.12M.08", "acodec": "none", "width": metadata["width"],
         "height": metadata["height"], "fps": metadata["frame_rate"]},
        {"format_id": "original-opus", "url": address + "/audio.webm", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160},
        {"format_id": "lower-h264", "url": address + "/must-not-download.mp4", "ext": "mp4",
         "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "height": 720, "fps": 30},
    ]
    started = time.monotonic()
    try:
        with YoutubeDL({"quiet": True, "noprogress": True, "format": quality_format(), "format_sort": ["res", "fps"],
                        "merge_output_format": BROWSER_MERGE_FORMATS, "outtmpl": str(downloads / "gameplay-1440p60.%(ext)s")}) as ydl:
            ydl.process_ie_result({"id": "local-vod", "title": "Local VOD verification", "formats": formats}, download=True)
    finally:
        http.shutdown()
        http.server_close()
    merge_seconds = time.monotonic() - started
    merged = downloads / "gameplay-1440p60.webm"
    before = {"video": packet_hash(inputs / "video.mp4", "v:0"), "audio": packet_hash(inputs / "audio.webm", "a:0")}
    after = {"video": packet_hash(merged, "v:0"), "audio": packet_hash(merged, "a:0")}
    assert before == after, (before, after)
    # Exercise standard MP4 and original-resolution 4K60 playback as well.
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=60", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
           "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-threads", "2", "-c:a", "aac",
           "-movflags", "+faststart", downloads / "synthetic-4k60.mp4")
    results = [prepare(workspace, source) for source in (merged, downloads / "synthetic-4k60.mp4")]
    # Reference a full long VOD without copying gigabytes or modifying it.
    full = downloads / "full-vod.mkv"
    full.hardlink_to(args.source.resolve())
    results.append(prepare(workspace, full))
    report = {"workspace": str(workspace), "local_download_and_merge_seconds": round(merge_seconds, 3),
              "stream_payloads_identical": before == after, "stream_hashes": after, "imports": results}
    (workspace / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    print(f"Browser fixture ready: http://127.0.0.1:{args.port}", flush=True)
    app = create_app(workspace)
    LocalServer(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", timeout_graceful_shutdown=5),
                app.state.shutting_down).run()


if __name__ == "__main__":
    main()
