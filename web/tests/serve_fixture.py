"""Disposable local browser-test workspace, always inside runs/."""

import subprocess
import tempfile
from pathlib import Path

import uvicorn

from game_vod_clipper.web import create_app

root = Path(__file__).resolve().parents[2]
(root / "runs").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="web-e2e-", dir=root / "runs") as folder:
    workspace = Path(folder)
    (workspace / "downloads").mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "16",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(workspace / "downloads" / "synthetic.mp4"),
        ],
        check=True,
    )
    uvicorn.run(create_app(workspace), host="127.0.0.1", port=8010)
