# Game VOD Clipper · BossCut Studio

**English** | [繁體中文](README.zh-TW.md)

Find complete boss-fight victories in game livestream VODs, review the start and victory timestamps, and export clean MP4 clips.

The project provides three ways to work:

- **Web workspace**: import videos, find candidates with AI, adjust the timeline, manage clips, and upload finished clips to YouTube.
- **Python CLI**: download, sample, create contact sheets, and cut videos with yt-dlp and FFmpeg.
- **Agent Skill**: guide a coding agent through visual inspection, excluding failed attempts, and validating the final clip.

This is a local, single-user tool. AI candidates still need review; manual editing does not require an AI account.

## Quick start

### Docker Compose

Install Docker with Compose, then run:

```bash
git clone https://github.com/Zncl2222/game-vod-clipper.git
cd game-vod-clipper
docker compose up -d --build --wait
```

Open **http://127.0.0.1:8000**. The image includes the frontend, backend, FFmpeg, yt-dlp, Node.js, and Codex CLI.
The service runs in the background and stores data in Docker volumes. Use `docker compose stop` to stop it.

For local video imports, storage mounts, backups, and updates, see [Docker deployment](docs/guides/deployment.md) (Traditional Chinese).

### Run locally

Requires Python 3.11+, uv, Node.js 22.12+, npm, and FFmpeg/ffprobe from a trusted source.
Run from the repository root:

```bash
uv sync --frozen --extra web
npm --prefix web ci
npm --prefix web run build
uv run --extra web game-vod-clipper check
uv run --extra web game-vod-web
```

Open **http://127.0.0.1:8000** and keep the backend running while processing videos.
AI features also require Codex CLI to be installed and connected in the backend environment; the Docker image already includes it.
For command-line use only, see [CLI and agents](docs/guides/cli.md) (Traditional Chinese).

## Workflow

1. Place a local recording in `downloads/` and import it, or paste the URL of a completed YouTube livestream.
2. Locate the winning attempt manually, or connect an AI account in account settings and start a victory search.
3. Preview candidates and adjust the start, victory timestamp, and postroll. Confirm that the range contains one complete successful attempt.
4. Export an MP4. Download it, save an edited version as a new clip, or confirm an upload to your own YouTube channel.

Clips must exclude earlier failed attempts, death screens, loading screens, respawns, and runbacks. Include the victory moment and **5–10 seconds afterward**.
Do not rely only on sparse thumbnails for final validation. Do not upload or redistribute the user's source VOD.

## Documentation

English is the default README language; a [Traditional Chinese version](README.zh-TW.md) is also available.
The detailed guides below are currently in **Traditional Chinese**. Commands, API names, and the Agent Skill retain their original format.

| Task | Guide |
| --- | --- |
| Import, search with AI, review candidates, export, and manage storage | [User guide](docs/guides/usage.md) |
| Run a persistent service, mount local videos, back up, and update | [Docker deployment](docs/guides/deployment.md) |
| Connect a channel, import livestreams in batches, and upload clips | [YouTube workflow](docs/guides/youtube.md) |
| Use the command line or delegate clipping to an agent | [CLI and agents](docs/guides/cli.md) |
| Set up development, navigate the code, maintain the UI, and run tests | [Development guide](docs/guides/development.md) |

## Repository layout

```text
src/game_vod_clipper/           Python CLI, API, and background workers
web/                           React frontend and browser tests
tests/                         Python tests
skills/game-vod-boss-clipper/   Agent clipping workflow
docs/guides/                   Maintained user and developer guides
scripts/                       Validation, benchmarks, and storage migration
downloads/                     Source videos (ignored by Git)
runs/                          State, analysis, and temporary files (ignored by Git)
clips/                         Exported clips (ignored by Git)
```

The web app supports custom storage locations. Changes apply to new files only; existing projects are not moved automatically.

## License

[MIT License](LICENSE).
