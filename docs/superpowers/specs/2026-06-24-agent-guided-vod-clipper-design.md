# Agent-Guided VOD Clipper Design

## Goal

Initialize a Python CLI project for Claude Code, Codex, OpenCode, and similar coding agents. The toolchain helps an agent download a user-provided YouTube VOD, inspect game livestream footage, identify a successful boss fight attempt, and cut a final clip that starts after any prior death sequence and ends 5-10 seconds after the victory moment.

## Scope

The first version is an agent-guided workflow, not a fully automatic computer vision system. Python handles deterministic media operations: dependency checks, YouTube download through `yt-dlp`, duration probing through `ffmpeg`, screenshot sampling through `ffmpeg`, optional contact sheet generation, and final clipping through `ffmpeg`. The agent remains responsible for visual judgment and timestamp selection.

## Architecture

The project uses a standard `src/` Python package managed by `uv`.

- `game_vod_clipper.cli` defines the command-line interface.
- `game_vod_clipper.media` wraps `yt-dlp` and `ffmpeg` commands.
- `game_vod_clipper.timecode` parses and formats timestamps.
- `game_vod_clipper.process` centralizes subprocess execution and tool checks.

`yt-dlp` is a project dependency. FFmpeg is not bundled through a Python package; the CLI requires a trusted `ffmpeg` binary on `PATH`. Recommended sources are official distro packages, Homebrew, Windows Package Manager, FFmpeg source releases with PGP verification, or binary providers linked from the official FFmpeg download page with checksum verification. `ffprobe` is not required in this version.

This keeps each unit small and testable. Media commands are isolated from CLI parsing, and timestamp behavior can be tested without external binaries.

## CLI Commands

- `check`: verify that `yt-dlp` is available through PATH or uv-managed dependencies and that `ffmpeg` is available on PATH.
- `download URL`: download a single YouTube VOD into `downloads/` and print the final local path.
- `probe VIDEO`: print the media duration.
- `sample VIDEO --start TIME --end TIME --every SECONDS`: export timestamped screenshots plus a JSON manifest for agent review.
- `sheet FRAME_DIR`: create a contact sheet from sampled JPG frames.
- `clip VIDEO --start TIME --end TIME --postroll SECONDS --output FILE`: cut the final victory clip. `--end` is the victory moment, and `--postroll` extends the clip by 5-10 seconds.

## Agent Workflow

`AGENTS.md` gives agents a concrete operating procedure:

1. Run `uv sync`, then `check` before media work.
2. Download the VOD or use a local video path.
3. Probe duration.
4. Coarsely sample the VOD to find candidate boss fights.
5. Finely sample candidate ranges to locate the latest death screen, boss entry, victory moment, and reward screen.
6. Set clip start after the latest prior death and before the winning boss attempt becomes meaningful.
7. Set clip end at the victory/reward moment and use a 5-10 second postroll.
8. Validate the produced clip by sampling the beginning and end.

The instructions explicitly prevent including earlier failed attempts or death screens.

## Error Handling

The CLI reports missing external tools with direct install guidance. Subprocess failures include the command output so agents can diagnose bad URLs, unsupported formats, missing codecs, or invalid paths. Timestamp validation rejects negative values and clips where the end is not after the start.

## Testing

Unit tests cover timestamp parsing and formatting with Python's standard `unittest`. External media operations are intentionally not executed in unit tests because they require large files. Local verification should run `uv run python -m unittest discover -s tests`, `uv run python -m compileall src tests`, and `uv run game-vod-clipper --help` after `uv sync`.

## Future Work

Later versions can add optional OCR and image heuristics for boss HP bars, death screens, and victory text. Those features are deliberately out of scope for this initialization so the first version remains reliable and easy for agents to operate.
