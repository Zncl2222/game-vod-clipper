# Game VOD Clipper

Python CLI for Claude Code, Codex, OpenCode, and similar agents to clip successful boss fights from game livestream VODs.

The first version is intentionally agent-guided: the script handles `yt-dlp` and `ffmpeg` operations, while the agent visually inspects sampled frames to choose the correct winning boss attempt.

## Requirements

- Python 3.11+
- `uv`
- `ffmpeg` on `PATH`

`yt-dlp` is installed as a project dependency through `uv`. FFmpeg is intentionally not bundled through a Python package; install it from a trusted OS package manager or from a build source linked by the official FFmpeg download page. `ffprobe` is not required for the first version.

## Safe FFmpeg Sources

Prefer these sources:

- Linux: distro packages such as Debian/Ubuntu `apt install ffmpeg` from official repositories.
- macOS: Homebrew `brew install ffmpeg`.
- Windows: `winget install ffmpeg` or `winget install "FFmpeg (Essentials Build)"`.
- Source builds: download source from `https://ffmpeg.org/download.html` and verify the PGP signature.
- Manual Windows binaries: use Gyan builds linked from `https://ffmpeg.org/download.html` and verify the `.sha256` checksum.

Avoid installing FFmpeg from random Python packages or unverified binary mirrors.

## Install

```bash
uv sync
uv run game-vod-clipper check
```

## Quick Start

```bash
uv run game-vod-clipper check
uv run game-vod-clipper download "https://www.youtube.com/watch?v=..."
uv run game-vod-clipper probe "downloads/video.mp4"
uv run game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss
uv run game-vod-clipper sheet runs/boss -o runs/boss.jpg
uv run game-vod-clipper clip "downloads/video.mp4" --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
```

## Skill Usage

The agent workflow lives in `skills/game-vod-boss-clipper/SKILL.md`. Claude Code, Codex, OpenCode, and similar tools should load or follow that skill when a user asks to clip a successful boss fight from a YouTube or local game VOD.

`AGENTS.md` is intentionally short and delegates to the skill. If a tool does not support repository skills directly, read the skill file and follow it as procedural instructions.

The important rule is that the final clip must start after the latest failed attempt or death sequence and keep 5-10 seconds after the boss victory moment.

## Commands

- `check`: verify required external tools.
- `download URL`: download a single YouTube VOD.
- `probe VIDEO`: print the duration.
- `sample VIDEO --start TIME --end TIME --every SECONDS`: extract timestamped JPG frames and `samples.json`.
- `sheet FRAME_DIR -o SHEET.jpg`: create a contact sheet from sampled frames.
- `clip VIDEO --start TIME --end TIME --postroll SECONDS -o OUT.mp4`: create the final clip.

## Development

```bash
uv run python -m unittest discover -s tests
uv run python -m compileall src tests
uv run game-vod-clipper --help
```
