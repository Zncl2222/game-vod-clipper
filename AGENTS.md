# Agent Workflow

This repository is designed for Claude Code, Codex, OpenCode, and similar coding agents. Your job is to use the Python CLI plus visual inspection to clip the user's successful boss fight attempt from a YouTube game livestream VOD.

## Rules

- Do not include earlier failed attempts, death screens, loading screens after death, or runback footage before the winning attempt.
- The final clip must include the boss victory moment and 5-10 seconds after it.
- Prefer accurate re-encoded cuts over fast stream copies unless the user explicitly wants speed.
- Keep generated media under `downloads/`, `runs/`, or `clips/`.
- Do not upload or redistribute the user's source video.

## Setup

Install project-managed Python tools before using the CLI:

```bash
uv sync
```

Install FFmpeg from a trusted source and make sure `ffmpeg` is on `PATH`:

- Linux: use official distro packages such as Debian/Ubuntu `apt install ffmpeg`.
- macOS: use Homebrew `brew install ffmpeg`.
- Windows: use `winget install ffmpeg` or `winget install "FFmpeg (Essentials Build)"`.
- Source/manual builds: use sources or binary providers linked from `https://ffmpeg.org/download.html`; verify PGP signatures or SHA-256 checksums where available.

Do not install FFmpeg from random Python packages or unverified binary mirrors.

Then verify from this project:

```bash
uv run game-vod-clipper check
```

The project installs `yt-dlp` through `uv`. FFmpeg must come from a trusted system source and be available on `PATH`. `ffprobe` is not required.

If you prefer direct Python module execution after syncing, use:

```bash
uv run python -m game_vod_clipper check
```

## Recommended Process

1. Download the VOD if the user provided a YouTube URL:

```bash
uv run game-vod-clipper download "https://www.youtube.com/watch?v=..."
```

2. Probe the duration:

```bash
uv run game-vod-clipper probe "downloads/video.mp4"
```

3. Coarsely sample the full VOD or a likely range. Use wider intervals first:

```bash
uv run game-vod-clipper sample "downloads/video.mp4" --start 00:00:00 --end 03:00:00 --every 60 -o runs/coarse
uv run game-vod-clipper sheet runs/coarse -o runs/coarse.jpg
```

4. Find candidate boss fight ranges. Look for fog gates, boss intro/title cards, large boss HP bars, arena transitions, phase changes, and victory reward text.

5. Finely sample around candidates using 5-15 second intervals:

```bash
uv run game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss-candidate
uv run game-vod-clipper sheet runs/boss-candidate -o runs/boss-candidate.jpg --columns 6 --rows 5
```

6. Determine the winning attempt boundaries:

- Start after the latest death screen, respawn, loading screen, or runback that belongs to a failed attempt.
- A good start is usually just before the player enters the arena, crosses the fog wall, or triggers the winning attempt's boss title card.
- If there is a `YOU DIED`, `死亡`, fade-to-black death sequence, or respawn before the boss win, the clip start must be after that sequence.
- End at the boss defeat moment or reward text such as `Enemy Felled`, `Great Enemy Felled`, `Legend Felled`, `Remembrance`, souls/runes gained, achievement popups, or equivalent game-specific victory UI.

7. Cut the final clip. Set `--end` to the victory moment and keep `--postroll` between 5 and 10 seconds:

```bash
uv run game-vod-clipper clip "downloads/video.mp4" --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
```

8. Validate the result by sampling the produced clip's beginning and ending:

```bash
uv run game-vod-clipper sample clips/boss-win.mp4 --start 0 --end 20 --every 5 -o runs/final-start-check
uv run game-vod-clipper probe clips/boss-win.mp4
```

If the beginning contains a death screen or failed attempt context, move `--start` later and regenerate the clip. If the ending cuts off reward or celebration context, increase `--postroll` up to 10 seconds or move `--end` later.

## Time Format

The CLI accepts `SS`, `MM:SS`, and `HH:MM:SS`, including fractional seconds like `01:23:45.5`.
