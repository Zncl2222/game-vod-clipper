"""Real deletion QA against isolated synthetic media, no Google/network required."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import uvicorn

from game_vod_clipper.web import create_app


root = Path(__file__).resolve().parents[2]
(root / "runs").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="storage-ui-", dir=root / "runs") as folder:
    workspace = Path(folder)
    source = workspace / "downloads" / "qa-original.mp4"
    source.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-t", "16", "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", str(source)], check=True)
    clip = workspace / "clips" / "web" / "qa" / "qa-clip.mp4"
    clip.parent.mkdir(parents=True)
    shutil.copyfile(source, clip)
    orphan = workspace / "runs" / "web" / "old" / "preview.mp4"
    orphan.parent.mkdir(parents=True)
    shutil.copyfile(source, orphan)
    for name in ("qa-orphan-a.mp4", "qa-orphan-b.mp4"):
        shutil.copyfile(source, source.parent / name)
    app = create_app(workspace)
    app.state.store.put("projects", dict(id="qa", title="清理測試直播", source="downloads/qa-original.mp4",
        url="https://www.youtube.com/watch?v=abcdefghijk", created=1780000000, ready=True, playback="source",
        duration=16, width=640, height=360, frame_rate=30, thumbnails=[],
        draft=dict(start=0, victory=8, postroll=8, reviewed=False, revision=0)))
    app.state.store.put("jobs", dict(id="qa-clip", project_id="qa", kind="export", status="succeeded",
        output="clips/web/qa/qa-clip.mp4", created=1780000010,
        draft=dict(start=0, victory=8, postroll=8, reviewed=False, revision=0)))
    print(f"Disposable storage QA workspace: {workspace}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8012)
