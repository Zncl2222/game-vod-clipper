---
name: game-vod-boss-clipper
description: Use this skill whenever the user provides a YouTube or local game livestream VOD and wants a boss fight, boss win, successful attempt, victory clip, Elden Ring/Dark Souls boss kill, or similar gameplay moment clipped. This skill guides Claude Code, Codex, OpenCode, and similar coding agents through using the repository CLI to download, sample, visually inspect, and cut only the successful boss attempt, excluding failed attempts, death screens, loading screens, and runback footage while keeping 5-10 seconds after victory.
compatibility: Requires the game-vod-clipper CLI, yt-dlp through the project or uv tool install, and a trusted ffmpeg binary on PATH.
---

# Game VOD Boss Clipper

Use this skill to turn a long game livestream VOD into a precise clip of the user's successful boss fight attempt. The Python CLI performs deterministic media operations; you provide the visual judgment.

## Core Rules

- Clip only the successful boss attempt.
- Do not include earlier failed attempts, `YOU DIED` screens, death fades, post-death loading screens, respawns, or runback footage.
- Include the boss victory moment and 5-10 seconds after it.
- Keep generated media under `downloads/`, `runs/`, or `clips/`.
- Do not upload, redistribute, or expose the source video.
- Prefer accurate re-encoded cuts. Use stream copy only when the user explicitly asks for speed.

## Setup

If the CLI is installed globally, use `game-vod-clipper` directly. If you are working from this repository without a global install, use `uv run game-vod-clipper` from the repository root.

For source checkouts, install project-managed Python tools:

```bash
uv sync
```

Install FFmpeg from a trusted source and make sure `ffmpeg` is on `PATH`:

- Linux: use official distro packages such as Debian/Ubuntu `apt install ffmpeg`.
- macOS: use Homebrew `brew install ffmpeg`.
- Windows: use `winget install ffmpeg` or `winget install "FFmpeg (Essentials Build)"`.
- Source/manual builds: use sources or binary providers linked from `https://ffmpeg.org/download.html`; verify PGP signatures or SHA-256 checksums where available.

Do not install FFmpeg from random Python packages or unverified binary mirrors.

Verify tools:

```bash
game-vod-clipper check
```

If this fails because `ffmpeg` is missing, stop and report that FFmpeg must be installed from a trusted source before media work can proceed.

## Workflow

### 1. Get The Video

If the user provided a YouTube URL, download it:

```bash
game-vod-clipper download "https://www.youtube.com/watch?v=..."
```

If the user provided a local file, use that path directly.

Probe the duration:

```bash
game-vod-clipper probe "downloads/video.mp4"
```

### 2. Coarse Search

Sample wide ranges first. Start with 30-90 second intervals depending on VOD length:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 00:00:00 --end 03:00:00 --every 60 -o runs/coarse
game-vod-clipper sheet runs/coarse -o runs/coarse.jpg
```

Look for fog gates, boss title cards, arena transitions, large boss HP bars, phase changes, reward text, achievements, rune/soul gains, and celebration behavior.

### 3. Fine Search

For each candidate boss range, sample at 5-15 second intervals:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss-candidate
game-vod-clipper sheet runs/boss-candidate -o runs/boss-candidate.jpg --columns 6 --rows 5
```

If a candidate contains a death screen before the victory, keep moving forward until you find the winning attempt's real start.

### 4. Pick Clip Boundaries

Choose the start after the latest prior failure context:

- Good starts: just before entering the arena, crossing fog, boss title card, or first meaningful action in the winning attempt.
- Bad starts: death screen, respawn, loading after death, elevator/runback, menuing before retry, or previous failed attempt combat.

Choose the end at the victory moment:

- Examples: `Enemy Felled`, `Great Enemy Felled`, `Legend Felled`, `Remembrance`, souls/runes gained, achievement popup, boss death animation completion, or equivalent victory UI.
- Use `--postroll` between 5 and 10 seconds so the final clip preserves reward and reaction context.

### 5. Cut The Clip

Set `--end` to the victory moment. The CLI adds postroll:

```bash
game-vod-clipper clip "downloads/video.mp4" --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
```

### 6. Validate The Result

Check the beginning and ending before reporting success:

```bash
game-vod-clipper sample clips/boss-win.mp4 --start 0 --end 20 --every 5 -o runs/final-start-check
game-vod-clipper probe clips/boss-win.mp4
```

Also inspect the final seconds by sampling near the clip duration. If the beginning includes failure context, move `--start` later and regenerate. If the ending cuts off reward or reaction context, increase `--postroll` up to 10 seconds or move `--end` later.

## Output Report

When done, report:

- Final clip path.
- Source video path.
- Start timestamp, victory timestamp, and postroll used.
- Brief validation result: no prior death/runback included, victory and postroll included.
- Any blockers, especially missing trusted FFmpeg installation.

## Time Format

The CLI accepts `SS`, `MM:SS`, and `HH:MM:SS`, including fractional values such as `01:23:45.5`.
