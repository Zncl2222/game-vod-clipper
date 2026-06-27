# Game VOD Clipper

Agent-guided tooling for clipping clean boss-fight victories from long game livestream VODs.

This project combines a Python CLI with an agent skill:

- `game-vod-clipper`: downloads, probes, samples, contact-sheets, and cuts video with `yt-dlp` and FFmpeg.
- `skills/game-vod-boss-clipper/SKILL.md`: tells an AI coding agent how to inspect the VOD, find the successful boss attempt, avoid failed attempts, and validate the final clip.

The CLI handles deterministic media work. The agent handles visual judgment.

## What It Produces

A valid final clip should:

- Start at the successful boss attempt.
- Exclude earlier failed attempts, death screens, post-death loading, respawns, retry UI, and runback footage.
- Include the actual victory moment.
- Keep 5-10 seconds after victory for reward text, achievements, or reaction context.
- Store generated files under `downloads/`, `runs/`, or `clips/`.
- Avoid uploading or redistributing the user's source video.

This is intentionally agent-guided rather than fully automatic. Boss VODs often contain retries, HP resets, fast deaths, loading screens, and confusing transitions that require visual inspection.

## Repository

```text
https://github.com/Zncl2222/game-vod-clipper.git
```

## Requirements

- Python 3.11+
- `uv`
- FFmpeg on `PATH`
- Network access if downloading YouTube VODs

`yt-dlp` is installed through the Python project. FFmpeg is not bundled and should be installed from a trusted source.

## For Users

Use this section if you are installing the tool yourself.

### 1. Install `uv`

Install `uv` from the official Astral instructions:

```text
https://docs.astral.sh/uv/getting-started/installation/
```

Verify it works:

```bash
uv --version
```

### 2. Install FFmpeg

Use a trusted package manager or a source linked by the official FFmpeg website.

Recommended options:

- Linux: `sudo apt install ffmpeg` on Debian/Ubuntu, or your distro's official package manager.
- macOS: `brew install ffmpeg`.
- Windows: `winget install ffmpeg` or `winget install "FFmpeg (Essentials Build)"`.
- Manual builds: use providers linked from `https://ffmpeg.org/download.html` and verify signatures or checksums when available.

Avoid random Python packages, unofficial mirrors, and unverified binaries that claim to provide FFmpeg.

Verify FFmpeg:

```bash
ffmpeg -version
```

### 3. Clone This Repository

```bash
git clone https://github.com/Zncl2222/game-vod-clipper.git
cd game-vod-clipper
```

### 4. Install The CLI

For local development inside the repository:

```bash
uv sync
uv run game-vod-clipper check
```

For a global user-level CLI install:

```bash
uv tool install /path/to/game-vod-clipper
game-vod-clipper check
```

If you are still inside the repository and did not install globally, prefix commands with `uv run`:

```bash
uv run game-vod-clipper check
```

### 5. Install The Skill For Your Agent

The skill folder is:

```text
skills/game-vod-boss-clipper
```

The skill file is:

```text
skills/game-vod-boss-clipper/SKILL.md
```

#### Claude Code

Install the CLI globally:

```bash
uv tool install /path/to/game-vod-clipper
```

Install the skill globally:

```bash
mkdir -p ~/.claude/skills
cp -R /path/to/game-vod-clipper/skills/game-vod-boss-clipper ~/.claude/skills/
```

Then ask Claude Code:

```text
Use the game-vod-boss-clipper skill to clip the successful boss attempt from this VOD: <youtube-url-or-local-path>
```

You can also use the skill without copying it globally by opening Claude Code in this repository and explicitly telling it to read `skills/game-vod-boss-clipper/SKILL.md`.

#### OpenCode

Install the CLI globally:

```bash
uv tool install /path/to/game-vod-clipper
```

Install the skill globally:

```bash
mkdir -p ~/.agents/skills
cp -R /path/to/game-vod-clipper/skills/game-vod-boss-clipper ~/.agents/skills/
```

Then ask OpenCode:

```text
Use the game-vod-boss-clipper skill to clip the successful boss attempt from this VOD: <youtube-url-or-local-path>
```

You can also use the skill without copying it globally by opening OpenCode in this repository and explicitly telling it to read `skills/game-vod-boss-clipper/SKILL.md`.

#### OpenAI Codex

Codex does not need a native skill installation for this repository. Use the repository and skill file as task context.

Install the CLI globally:

```bash
uv tool install /path/to/game-vod-clipper
```

Then give Codex this instruction:

```text
Clone or open https://github.com/Zncl2222/game-vod-clipper.git. Read skills/game-vod-boss-clipper/SKILL.md and follow it exactly. Use the game-vod-clipper CLI to clip only the successful boss attempt from this VOD: <youtube-url-or-local-path>
```

If Codex is already running inside this repository, use:

```text
Read skills/game-vod-boss-clipper/SKILL.md and follow it exactly. Clip only the successful boss attempt from this VOD: <youtube-url-or-local-path>
```

## For Agents

Use this section if you are an AI coding agent receiving a VOD clipping task. The user should only need to give you the repository URL and the VOD.

### Agent Bootstrap

Repository:

```text
https://github.com/Zncl2222/game-vod-clipper.git
```

Primary skill file:

```text
skills/game-vod-boss-clipper/SKILL.md
```

Your job:

1. Clone or open the repository.
2. Read `skills/game-vod-boss-clipper/SKILL.md` before doing media work.
3. Install or use the CLI with `uv sync` and `uv run game-vod-clipper ...`, or install it globally with `uv tool install`.
4. Verify FFmpeg with `game-vod-clipper check` or `uv run game-vod-clipper check`.
5. Download or use the provided VOD.
6. Sample, inspect, and cut only the successful boss attempt.
7. Validate the final clip before reporting success.

### Minimal Agent Prompt

Users can give this prompt to Claude Code, Codex, OpenCode, or Copilot:

```text
Use this repository for the task: https://github.com/Zncl2222/game-vod-clipper.git

Read skills/game-vod-boss-clipper/SKILL.md and follow it exactly. Install the CLI if needed. Clip only the successful boss attempt from this VOD: <youtube-url-or-local-path>

Do not include earlier failed attempts, death screens, loading after death, respawns, retry UI, or runback footage. Include the boss victory moment and 5-10 seconds after it. Validate the final clip before reporting the result.
```

### Agent Install Commands

If the repository is not already available:

```bash
git clone https://github.com/Zncl2222/game-vod-clipper.git
cd game-vod-clipper
uv sync
uv run game-vod-clipper check
```

If the user wants a global CLI:

```bash
uv tool install /path/to/game-vod-clipper
game-vod-clipper check
```

If FFmpeg is missing, stop and tell the user to install FFmpeg from a trusted source. Do not install FFmpeg from random Python packages or unverified binary mirrors.

## CLI Quick Start

Download a YouTube VOD:

```bash
game-vod-clipper download "https://www.youtube.com/watch?v=..."
```

Probe a local or downloaded video:

```bash
game-vod-clipper probe "downloads/video.mp4"
```

Sample a broad range:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 00:00:00 --end 03:00:00 --every 60 -o runs/coarse
game-vod-clipper sheet runs/coarse -o runs/coarse.jpg
```

Sample a candidate range more closely:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss-candidate
game-vod-clipper sheet runs/boss-candidate -o runs/boss-candidate.jpg --columns 6 --rows 5
```

Cut the final clip. Set `--end` to the victory moment; `--postroll` keeps the seconds after victory.

```bash
game-vod-clipper clip "downloads/video.mp4" --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
```

Validate the result:

```bash
game-vod-clipper sample clips/boss-win.mp4 --start 0 --end 20 --every 5 -o runs/final-start-check
game-vod-clipper probe clips/boss-win.mp4
```

When using the local checkout instead of a global CLI install, prefix commands with `uv run`:

```bash
uv run game-vod-clipper check
```

## CLI Commands

```text
game-vod-clipper check
game-vod-clipper download URL [-o downloads]
game-vod-clipper probe VIDEO
game-vod-clipper sample VIDEO --start TIME --end TIME [--every SECONDS] [-o runs/samples]
game-vod-clipper sheet FRAME_DIR -o SHEET.jpg [--columns N] [--rows N] [--width PX]
game-vod-clipper clip VIDEO --start TIME --end TIME [--postroll SECONDS] -o OUT.mp4 [--copy]
```

Time values accept `SS`, `MM:SS`, `HH:MM:SS`, and fractional values such as `01:23:45.5`.

## Non-Negotiable Clipping Rules

- Do not include earlier failed attempts.
- Do not include `YOU DIED` screens, red failure overlays, death fades, post-death loading, retry UI, respawns, or runbacks.
- Treat a boss HP bar disappearing and later returning with higher health as a likely retry/reset until inspection proves otherwise.
- Treat player collapse plus red tint plus fade/loading as a high-confidence failure signal, even without explicit death text.
- Do not rely only on sparse thumbnails for final validation.
- Include the victory moment and 5-10 seconds after it.
- Prefer accurate re-encoded cuts. Use `--copy` only when speed is more important than exact frame accuracy.

## Output Locations

Generated media should stay in these directories:

- `downloads/` for downloaded source videos and metadata.
- `runs/` for sampled frames, manifests, and contact sheets.
- `clips/` for final clips.

Do not upload or redistribute source videos from users.

## Development

Run tests:

```bash
uv run python -m unittest discover -s tests
```

Compile-check the package and tests:

```bash
uv run python -m compileall src tests
```

Show CLI help:

```bash
uv run game-vod-clipper --help
```

## License

MIT. See `LICENSE`.
