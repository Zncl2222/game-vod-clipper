---
name: game-vod-boss-clipper
description: Use this skill whenever the user provides a YouTube or local game livestream VOD and wants a boss fight, boss win, successful attempt, victory clip, Elden Ring/Dark Souls boss kill, or similar gameplay moment clipped. This skill guides Claude Code, Codex, OpenCode, and similar coding agents through using the repository CLI to download, sample, visually inspect, and cut only the successful boss attempt with a small clean lead-in when available, excluding failed attempts, death screens, loading screens, respawns, and runback footage while keeping 5-10 seconds after victory.
compatibility: Requires the game-vod-clipper CLI, yt-dlp through the project or uv tool install, and a trusted ffmpeg binary on PATH.
---

# Game VOD Boss Clipper

Use this skill to turn a long game livestream VOD into a precise clip of the user's successful boss fight attempt. The Python CLI performs deterministic media operations; you provide the visual judgment.

## Core Rules

- Clip only the successful boss attempt.
- Do not include earlier failed attempts, `YOU DIED` screens, death fades, post-death loading screens, respawns, or runback footage.
- When a clean lead-in exists, preserve a little context before combat: entering the boss arena, crossing the fog gate, stepping into the boss room, the boss title/name reveal, the approach inside the arena, or a brief readying moment before the first exchange. This lead-in is valuable, but it must still be part of the same successful attempt and must not include death, loading after death, respawn, retry UI, menuing, or runback context.
- A clip is invalid if any point after the chosen start shows player death, a red death/failure overlay, a death fade, a black loading/transition caused by failure, retry UI, respawn context, or combat from an attempt that fails before the victory.
- Treat the combination of the player character collapsing or lying prone, the whole screen shifting red or heavily tinted, and any loading-like fade/cut as a high-confidence death or failure signal even when there is no explicit `YOU DIED` text. Do not dismiss it as a generic combat effect unless dense inspection clearly proves the attempt continues without reset. Fast deaths can be followed by a very short black/loading screen and immediate arena reset; sparse thumbnails can easily miss this.
- After choosing a candidate range, inspect it at frame-level or near-frame-level density before cutting. Do not rely only on 2-5 second thumbnails for the final decision; dense inspection must rule out single-frame or short death/failure records hidden between sampled thumbnails.
- If a dense inspection finds any death/failure frame inside the candidate, discard everything before and during that failure. Restart from the first clean frame after the failure, retry UI, respawn, runback, or reset context has fully ended.
- Treat a boss HP bar that disappears and later returns with higher health as a retry/death warning until inspection proves otherwise.
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

Do not conclude from the first coarse sheet too quickly. Build a short candidate list across the whole VOD before narrowing down:

- Mark every timestamp that shows a boss-like HUD, large centered enemy HP bar/name, arena combat, victory/reward UI, death/loading screen, or retry context.
- Keep earlier candidates until you have inspected them at fine resolution. A later, louder-looking fight may be a different encounter or a later retry, not necessarily the successful boss attempt.
- If the user described a visual cue such as a centered boss name/extra HP bar, prioritize candidates that match that cue even if a later combat segment looks more dramatic.

### 3. Fine Search

For each candidate boss range, sample at 5-15 second intervals:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss-candidate
game-vod-clipper sheet runs/boss-candidate -o runs/boss-candidate.jpg --columns 6 --rows 5
```

For each fine sheet, track the boss HP bar over time instead of only looking for the final victory frame:

- Do not rely on only the candidate's first and last frames. For any candidate longer than 60 seconds, sample the whole candidate at 2-5 second intervals before cutting.
- If any sampled frame shows the player dying, lying collapsed/prone while the screen is red-tinted, a red failure overlay, a fade to black, loading, retry/respawn UI, or a sudden return to an earlier arena state, the candidate contains a failed attempt. Move the start to after that failure context and inspect again.
- If a boss HP bar disappears and later reappears with more health, full health, or a clearly higher amount than the previous fine samples, treat it as a likely death/retry, phase reset, or cut to a different attempt.
- When HP increases unexpectedly, sample the gap at 1-3 second intervals and inspect for death text, player collapse, fade to black, loading, respawn, menuing, runback, or a new arena entry.
- Do not include frames before an HP reset in the final clip unless the reset is clearly an intentional phase transition within the same successful attempt.
- If multiple attempts are present, keep moving forward attempt by attempt and choose the start of the last attempt that leads continuously to the victory.
- If a candidate contains a death screen before the victory, keep moving forward until you find the winning attempt's real start.
- Before accepting a candidate range, inspect the whole proposed range at frame-level or near-frame-level density. For 60 FPS footage, use about `--every 0.0167` when feasible, or split the range into smaller chunks and inspect high-density sheets. If full frame-level extraction is too large, use the densest practical interval plus targeted frame-level inspection around every red flash, HP depletion, black frame, cut, knockdown, UI change, or boss HP disappearance.
- Any red failure overlay, player collapse, prone player body combined with red tint, death/failure subtitle, loading transition, retry UI, or respawn context found during dense inspection invalidates the current start timestamp even if sparse thumbnails missed it.

### 4. Pick Clip Boundaries

Choose the start after the latest prior failure context, with a small clean lead-in when possible:

- Best starts: a few seconds before the winning attempt's first meaningful combat action, while the player is cleanly entering the boss arena, crossing fog, stepping into the boss room, approaching the boss inside the arena, or seeing the boss title/name reveal.
- Good fallback starts: the first clean frame after death/loading/respawn/runback context has fully ended, even if that means starting close to the first exchange.
- Bad starts: death screen, respawn, loading after death, elevator/runback, menuing before retry, or previous failed attempt combat.
- Also bad starts: travel back to the arena after a death, objective markers/distance prompts that clearly indicate runback, post-death tutorial or retry UI, or any clip lead-in that begins before the failed attempt has fully cleared.
- Also bad starts: any combat before a boss HP reset that indicates a failed attempt. If the boss HP later jumps upward, move the start to after the reset and after any respawn/runback context.
- If death or failure appears anywhere inside a draft clip, the start is wrong even if the clip eventually reaches victory. Regenerate from the first clean frame of the attempt after that failure.
- Do not over-trim to the final phase or last hits if a safe same-attempt lead-in is available. The goal is a complete successful boss fight clip, not just the kill shot.

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

Before reporting success, validate continuity inside the clip:

- The opening should show a clean lead-in or clean first combat moment from the successful attempt. It must not show death, loading after death, respawn, retry UI, menuing, or runback context.
- Sample the full clip densely, not just the opening and ending. Use frame-level or near-frame-level inspection when feasible; otherwise use the densest practical interval and targeted frame-level checks around every suspicious transition, red flash, HP depletion, boss HP disappearance, black frame, UI change, player collapse/prone frame, or knockdown.
- A 2-5 second continuity sheet is only a coarse validation aid. It is not sufficient by itself when the clip contains fast deaths, red overlays, rapid failures, or multiple attempts.
- If a red/death-looking segment is followed by black/loading frames and then gameplay resumes in the same arena, assume it may be a death and retry, not a victory transition. Inspect the exact sequence at 1 second or denser intervals, then move the start to the first clean gameplay frame after the loading/retry context.
- If the user points out that a segment is death or loading context, trust that correction and mark the current clip invalid. Regenerate from after the corrected failure context instead of defending the previous interpretation.
- If the boss HP suddenly increases inside the clip, regenerate from after that reset unless visual inspection proves it is a same-attempt phase transition.
- If any sampled frame inside the clip shows player death or failure context, the clip is invalid. Move the start after the failure and regenerate.
- Confirm the clip contains one continuous successful attempt from start to victory, not several retries stitched together by a broad timestamp range.

## Output Report

When done, report:

- Final clip path.
- Source video path.
- Start timestamp, victory timestamp, and postroll used.
- Brief validation result: clean lead-in included when available, no prior death/loading/respawn/runback included, no death/failure context inside the clip, no unexplained boss HP reset inside the clip, victory and postroll included.
- Any blockers, especially missing trusted FFmpeg installation.

## Time Format

The CLI accepts `SS`, `MM:SS`, and `HH:MM:SS`, including fractional values such as `01:23:45.5`.
