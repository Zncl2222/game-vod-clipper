---
name: game-vod-boss-clipper
description: Find and clip successful boss attempts from YouTube or local game livestream VODs, including Elden Ring and Dark Souls boss wins. Use the repository CLI to sample, visually verify, and export a continuous winning attempt with 5-10 seconds after victory, excluding earlier failures and runbacks.
metadata:
  compatibility: Requires the game-vod-clipper CLI, yt-dlp through the project or uv tool install, and a trusted ffmpeg binary on PATH.
---

# Game VOD Boss Clipper

Find useful encounters, verify the successful attempt, and finish with a clip or a
clear evidence-limited result. The CLI handles media; you provide visual judgment.
In the interactive editor the host handles extraction, checkpoints and export;
return observations instead of running the CLI setup or downloading again.

## Core Rules

- Clip only one continuous successful boss attempt, with a small clean arena-entry
  lead-in when available. Do not reduce it to the last hits if the full attempt is visible.
- Do not include earlier failed attempts, `YOU DIED`, death fades, post-death loading,
  respawns, retry UI, menuing, or runback footage.
- Any death/failure inside a proposed clip invalidates its start. Move it past that
  failure AND its loading, respawn and runback, to the next attempt's clean entry.
- A collapsing/prone player together with red tint and a loading-like fade is a
  strong failure signal even without death text. Inspect its local sequence;
  do not explain it away as a combat effect without evidence of continuity.
- A boss HP bar disappearing and returning with higher health requires checking
  for retry versus a same-attempt phase change. Unresolved resets block acceptance.
- Include visible victory and 5-10 seconds after it; both must fit the source.
- Keep generated media under `downloads/`, `runs/`, or `clips/`.
- Do not upload, redistribute, or expose the source video.
- Prefer accurate re-encoded cuts; use stream copy only if the user requests speed.

## Review Progress and Stopping

Keep one review ledger under `runs/` (or use the editor's checkpoint). Record the
source and requested bounds, viewed pages/packets with interval and timestamps,
encounters with stable IDs, unresolved questions, and pending checks. Extracting a
page does not mean it has been viewed: open every page before recording it as seen.
Read existing coverage before extracting anything else. Reuse it after resuming.

Every additional inspection must answer a named missing fact: which encounter,
whether the enemy was defeated, whether a reset occurred, or where the attempt
starts/ends. Record the question and the observed answer. Ordinary combat frames,
reworded summaries, and timestamp jitter alone are not new findings.

Use a finite progression: coarse search, candidate localization, whole-attempt
continuity, then short targeted detail checks. Use intervals such as 30/60/90,
5/10/15, 2, 0.5 seconds, then 0.1 seconds or native frames for a specific transition.
Do not repeatedly shave tiny amounts off an interval or split already seen frames
into new packets. Do not request an entire fight or VOD at native frame density.
For detail windows longer than 12 seconds, first localize the event at 0.5 seconds,
then inspect the relevant short transition. At native density there are no extra
frames to discover by sampling more densely.

Complete each requested refinement pass before opening another. If three completed
extra passes change no encounter, victory/failure decision, or meaningful boundary,
stop adding exploratory work. Finish the pending pass and required checks, retain
useful candidates, and conclude uncertain. Do not impose a whole-VOD round cap that
silently leaves the end unsearched; coarse and required checks are useful progress.

Finish when all of these hold:

1. Every coarse page in the requested range has been viewed. Every plausible
   encounter has a disposition: verified winner, failed/non-target, or uncertain
   with the specific missing evidence. A missing range remains incomplete.
2. The chosen attempt has whole-range continuity coverage and its opening,
   victory/postroll and suspicious transitions have been checked. If evidence
   cannot resolve a question after local detail and surrounding context, mark it
   uncertain; do not search unrelated combat to force a winner.
3. No useful unseen check remains. Report the outcome and end the turn. Do not
   restart discovery, reopen unchanged pages, or rerun completed validation.

In the editor, set `review_complete=true` and `sample_requests=[]` when evidence is
sufficient or exhausted. Keep unresolved `suspicious_windows` and warnings; the
host still completes coarse coverage and required checks. Completion is separate
from accepting a win. Report actual sampling coverage, never claim every source
frame was watched unless it was. If interrupted, report the remaining ranges.

## Provisional Review Annotations

Publish plausible timestamped encounters as they appear, even before verification.
Include approximate start/end, kind (possible win, fight, death/retry, unknown),
confidence, observed evidence and what needs checking. Keep victory unknown when
unseen. Never invent segments to meet a count.

Track encounters, not sampling packets. Update the same encounter's existing ID
when boundaries or interpretation change. In the editor copy host-assigned short
IDs exactly; use a new temporary label only for a new encounter. Return only new
or changed annotations and explicitly identify superseded hypotheses. Keep other
encounters and death/retry evidence visible. These are playable review ranges;
uncertain annotations are not accepted winning clips.

## Setup and Source

Use `game-vod-clipper` if installed, or `uv run game-vod-clipper` from this checkout.
For a checkout run `uv sync` once if dependencies are missing. Use FFmpeg from a
trusted source: official distro packages, Homebrew, winget, or providers linked
from https://ffmpeg.org/download.html with available signature/checksum validation.
Do not install random Python FFmpeg binaries or unverified mirrors.

```bash
game-vod-clipper check
```

If trusted FFmpeg is missing, stop and report the setup blocker. Otherwise reuse an
existing source or download the provided YouTube URL once, then probe its duration:

```bash
game-vod-clipper download "https://www.youtube.com/watch?v=..."
game-vod-clipper probe "downloads/video.mp4"
```

A provided local file is used directly. Restrict discovery to the user's requested
range, or the whole source if no range was given. Do not seek exactly at EOF.

## 1. Coarse Search

Sample the requested range at 30-90 second intervals (short clips need a smaller
interval). Substitute actual source bounds in these examples:

```bash
game-vod-clipper sample "downloads/video.mp4" --start 00:00:00 --end 02:59:59 --every 60 -o runs/coarse
game-vod-clipper sheet runs/coarse -o runs/coarse.jpg
```

`sheet` prints ALL page paths plus a JSON manifest. When more than one page is
needed it writes `coarse-page-001.jpg`, etc.; `coarse.json` lists every page and
its ordered frames. Open every listed page exactly once. Use `samples.json` to map
cells back to source timestamps. Check the viewed page/frame counts against the
manifest before marking this range covered. Never look at only the first page of
a long VOD. An unreadable cell calls for its existing full-resolution frame first,
not another extraction of the same time.

Collect boss HUD/name, fog gates, arena fights, reward/achievement UI, deaths and
retries across the whole range. Preserve earlier plausible encounters instead of
choosing only the latest or loudest fight. Prioritize cues described by the user.

## 2. Resolve Useful Encounters

For each plausible encounter, inspect its fight ending and surrounding context at
5-15 second intervals; then focus on its victory/reset and successful-attempt start.
This is more useful than repeatedly sampling ordinary middle-of-fight action.

```bash
game-vod-clipper sample "downloads/video.mp4" --start 01:20:00 --end 01:35:00 --every 10 -o runs/boss-candidate
game-vod-clipper sheet runs/boss-candidate -o runs/boss-candidate.jpg --columns 6 --rows 5
```

A victory can be shown by defeat text, enemy death/surrender plus rewards,
achievement or other clear game-specific outcome. Read small reward counters,
boss labels and subtitles at full resolution. Distinguish the player from the
enemy. A missing HP bar, ordinary damage numbers or a nearby NPC alone is not a win.

Track HP and attempt continuity across the range. Localize any reset, collapse,
red failure overlay, black/loading frame or cut; inspect the suspicious sequence
and its context at native density if needed. Separate failed attempts from the
one leading to victory. Keep uncertain cases with an explanation instead of
revisiting them indefinitely. Select the verified winner matching the user's
request; preserve other useful encounters in the report/editor.

## 3. Verify Boundaries and Continuity

Choose the winning attempt's clean arena entry, fog crossing, boss reveal or brief
readying moment before combat. Exclude all earlier failure/runback context. If the
candidate begins mid-fight, inspect earlier context once to find the real start.
If the available source begins mid-fight, disclose that limitation.

Inspect the whole proposed attempt including postroll at 2-second intervals, then
fill missing coverage at 0.5 seconds. Inspect short windows around the start and
victory (roughly two seconds on either side) and each suspicious transition at
native or near-native frame density (about `--every 0.0167` for 60 FPS footage).
A completed denser pass covers the coarser requirement; reuse those observations.
This is sampling, not proof that every source frame is clean. Unresolved failure
signals prevent accepting the candidate even when coverage is complete.

If a failure changes the start, retain already viewed coverage and inspect only
new boundaries/gaps. Trust user corrections about death/loading and invalidate the
old clip. Do not repeat a whole successful-attempt review because the start moved.

## 4. Cut The Clip

Only export a verified continuous win; the interactive editor also requires its
existing user review step. Set `--end` to the victory moment; the CLI adds postroll:

```bash
game-vod-clipper clip "downloads/video.mp4" --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
```

## 5. Validate The Result

Probe the output duration and inspect its opening and ending, mapping output times
back to the already reviewed source range. Confirm clean entry, visible victory
and 5-10 seconds of postroll. Reuse source continuity evidence for this re-encoded
continuous range; do not extract and review the entire fight a second time.

```bash
game-vod-clipper probe clips/boss-win.mp4
game-vod-clipper sample clips/boss-win.mp4 --start 0 --end 15 --every 5 -o runs/final-start-check
```

Use the actual output duration to sample the last seconds as well. If a concrete
boundary or encoding defect appears, fix that defect and recheck only the affected
part. If the same issue remains after two corrections, report the blocker and
retain the artifacts instead of looping through export and validation.

## Output Report

Return the result and stop:

- Verified clip: output/source paths, start, victory, postroll and validation result.
- Useful candidates: timestamp ranges, observed event, confidence and unresolved
  question; rejected failures should not be presented as successful clips.
- Coverage: requested range, viewed pages/packets, sampling intervals and any gaps.
- Outcome: completed with verified win, completed with no win found in the sampled
  evidence, completed uncertain, or interrupted/blocked with the remaining work.

Do not claim an uncertain range is safe to export, a coarse search found every
possible event, or sampled coverage is full frame-by-frame viewing.

Times accepted by the CLI: `SS`, `MM:SS`, `HH:MM:SS`, including fractions such as
`01:23:45.5`.
