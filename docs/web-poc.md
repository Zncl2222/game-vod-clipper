# BossCut web POC

This POC implements the first React + FastAPI + Python milestone: import → prepare
preview → adjust → review → export. It is a local single-user application, not a
hosted service. Codex CLI can propose successful-attempt timestamps using
the model selected in the AI sidebar. Publishing is not implemented, and every proposed clip still requires
human review before export.

## Run

Run from this source checkout:

```bash
uv sync --extra web
uv run game-vod-clipper check
ffprobe -version
npm --prefix web ci
npm --prefix web run build
uv run --extra web game-vod-web
```

Open `http://127.0.0.1:8000`. FFmpeg and ffprobe must come from trusted OS packages
or official FFmpeg-linked providers, as required by the repository Skill.

For frontend development, keep the backend running and use another terminal:

```bash
npm --prefix web run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to port 8000. The compiled
frontend is located relative to this checkout; distributing a standalone wheel
with bundled frontend assets is not part of the POC.

The server binds to loopback. For containers, privately forward port 8000. If your
trusted development proxy uses a different hostname, set `GAME_VOD_ALLOWED_HOSTS`
to the exact comma-separated hostnames (no scheme, port, or wildcard). This does
not add authentication: do not expose this POC or its forwarded port publicly.
`GAME_VOD_ROOT` optionally selects a different local workspace containing
`downloads/`, `runs/`, and `clips/`. Run one server process per workspace; do not
use multiple Uvicorn workers or a second server on the same state database.

## Workflow

1. Place a video under `downloads/`, or choose an existing video in `clips/`.
   The import picker lists up to 200 supported local files. Supported extensions:
   MP4, MKV, MOV, WebM, M4V. Paths and symlinks outside those roots are rejected.
2. Alternatively enter a single HTTPS YouTube video URL. Downloads stay under
   `downloads/web/<project-id>/`. Use sources you are authorized to process and
   that the platform permits you to obtain. Public availability is not permission
   to download. Live, login-required, and restricted videos are outside POC scope.
   No browser cookies are imported. Network failures are reported with a retry
   option or the option to use a local recording.
3. A separate Python process makes an H.264/AAC preview at up to 720p / 30 FPS and
   up to 24 thumbnails. Source inputs must be 10 seconds to 6 hours long. YouTube
   acquisition additionally has a 40 GB limit. Full-length preview preparation
   can take considerable time; the progress bar indicates pipeline stages, not
   a measured time-to-completion estimate.
4. Seek with the video player or thumbnails. Adjust start, victory, and 5–10
   seconds of postroll. `I` sets start; `O` sets victory; left/right arrows step
   by one **preview** frame (1/30 second) when focus is outside a control.
   Thumbnail positions are approximate navigation aids, not visual validation.
5. Play the complete candidate and inspect suspicious transitions at sufficient
   density according to the Skill. Confirm it is one successful attempt with no
   failed attempts, death, loading, retry, respawn, or runback context. The checkbox
   records human confirmation, not an automated proof. Any boundary edit or Agent
   import clears confirmation. Invalid or source-truncated postroll is rejected.
6. Save the draft or export. Local changes are also temporarily retained in this
   browser; **Save draft** commits them to the shared SQLite project. Conflicting
   revisions return an error; reload to obtain the latest saved revision.
7. Export re-encodes from the original using the existing CLI media function.
   Each job holds an immutable draft snapshot. The output's video presence and
   duration are verified; no automated visual correctness check is claimed.
   Download the result from processing history. Its JSON receipt records the
   source, exact timestamps, revision, and limits of validation.

## Agent / Skill handoff

The original CLI and Skill remain usable. In an imported project, open **任務 JSON**
to obtain `project_id`, source path, duration, current draft, and Skill instructions.
Give this local metadata to your existing Agent and have it follow
`skills/game-vod-boss-clipper/SKILL.md`. This manual JSON handoff does not itself
invoke a model. The AI sidebar described below dispatches chat and visual search
through the shared Codex CLI executor.

Import an Agent JSON result using **匯入 Agent 結果**:

```json
{
  "project_id": "copy-the-current-project-id-here",
  "start": 83.25,
  "victory": 248.5,
  "postroll": 8
}
```

All timestamps are source-relative seconds. A nested `draft` object with these
three values is also accepted. Project identity, finite numbers, ordering, and
postroll are checked. A different source or out-of-range result is rejected.
Imported boundaries remain unreviewed until the user checks the actual video.

The Agent can also use `PUT /api/projects/{id}/draft` with the current `revision`,
`origin: "agent"`, and `reviewed: false`. FastAPI's schema is at `/docs`.

## Codex CLI integration

Install Codex CLI in the same environment/container as FastAPI and authenticate:

```bash
codex login
codex login status
```

This integration was checked with `codex-cli 0.153.4`. It requires support for
`exec --ignore-user-config`, `--image`, `--json`, and `--output-schema`. Older CLI
versions may need updating. Chat and search use the sidebar model picker. Search
jobs pin the selected model and its advertised reasoning effort, including retries.
Image support is checked before queueing; actual invocation still determines model
access, which is not inferred from a successful login. Unsupported models or expired login fail visibly; there is no
silent fallback. The CLI's credentials are not copied into the database, sent to
the browser, or printed. ChatGPT login uses the applicable Codex plan allowance;
API-key login follows its applicable billing instead.

After preparing a video, select the source-relative start/end in the AI sidebar
and click **一鍵搜尋成功挑戰**, or type an explicit search request with a range.
Both inputs use `/api/codex/chat` and the same validated queue; task progress and
results appear in the conversation. You can ask about the latest result, cancel
the search, or manually apply a candidate from the video workspace. The default
range is the entire video, including VODs longer than 30 minutes.
Only that selected range is searched; the application never claims a whole-VOD
search when a smaller interval was selected.

The host extracts timestamp-labelled images from the source and paginates contact
sheets. Each packet has at most 48 frames; packets of up to six frames retain 960px
individual views. Codex receives the complete repository Skill as visual judgment
instructions, packet times, and earlier observations. It runs with read-only
sandboxing and is instructed not to invoke tools. Media operations remain in
Python; the model may request more sampling via its structured response.

Invocation uses the current CLI authentication with `--ignore-user-config`, avoiding
inherited model/provider settings and user-configured integrations, and uses
`--ephemeral` plus `--output-schema`. It does not modify the user's Codex settings.
CLI-level project/platform instructions and account policies may still apply.

The initial coarse pass covers the selected range before refinement packets.
Sparse sampling (intervals of at least five seconds) seeks to each target before
extracting one frame; dense short windows use one sequential pass. Input decoding
and JPEG encoding use two threads, with one filter thread. Each completed sparse
frame updates the job progress. Sparse seeks have a 30-second per-frame limit
within the packet budget; timeouts retain progress and report a readable error.
See [FFmpeg input seeking](https://ffmpeg.org/ffmpeg.html#Main-options) for the
accurate-seek behavior. This reduces unnecessary decoding, but performance still
depends on keyframe spacing, storage speed, and machine load.
Each pass allows 240 CLI invocations, 12,000 extracted frames and two hours of
scheduling time. Extraction packets allow up to 180 seconds and CLI calls up to
300 seconds, within the remaining pass budget. These are workload limits, not
monetary or token caps. The selected model and its reasoning effort stay pinned.

After discovery, the host requires whole-candidate checks at 2-second and then
0.5-second intervals, including postroll, for short and long candidates alike.
Start and victory each receive a +/-2-second window at 60 samples/second. The model
can request arbitrary additional ranges and reports suspicious death/reset windows;
those windows receive 60 samples/second regardless of the requested interval.
These samples may repeat source frames when the source FPS is lower. This is not
full-VOD frame-level validation and visual judgment can still miss events.

A changed start or victory replans mandatory checks. Invalid requests, pending
packets, incomplete density coverage and unresolved suspicious windows cannot
produce an accepted candidate. Evidence must reference actual sampled timestamps.
Per-round atomic checkpoints retain the queue, observations, usage and source
identity. Stopping, a failed call or reaching the pass budget allows **接續細查**;
completed observations are reused, while the interrupted packet is retried. A
source or model-setting change invalidates the checkpoint. Legacy jobs without
checkpoints restart when retried. A completed uncertain result with no pending
checks requires a new search or additional user context.

The video dock shows real stages and sampling density without moving the playhead.
The timeline displays sampled coverage (which is not proof of success), evidence,
compact candidate switches, and start/victory/end handles. Quick review buttons
play the opening, victory or postroll and stop at that preview boundary. New
candidates may select an untouched, unreviewed initial draft but never interrupt
playback or replace edits made during the search. Export still requires manual
review. A not-found result means no win was identified in the samples, not proof
that the source has no wins.

**Data flow:** full source video stays local, but selected sampled images, the
Skill prompt, and observations are sent through Codex to OpenAI. Local cancellation
stops further worker activity; requests already sent may count toward usage.
No entire source video is attached and no content is published. Local analysis
artifacts (frames, sheets, schema, model events, diagnostics, result) live under
`runs/web/<project-id>/codex/<job-id>/` and currently require manual cleanup.

Official references: [non-interactive Codex](https://learn.chatgpt.com/docs/non-interactive-mode),
[authentication](https://learn.chatgpt.com/docs/auth), and
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

## Architecture and persistence

```text
React + TypeScript
        │ HTTP commands / SSE state updates / range-based preview playback
FastAPI (one local process)
        ├── SQLite projects, versioned drafts, jobs
        └── one media worker process at a time
                ├── yt-dlp source acquisition
                ├── FFmpeg preview and batch thumbnail extraction
                ├── Shared Codex runtime (chat + explicitly requested visual review)
                └── existing Python clip_video() + output verification
```

The API keeps long media work out of request handlers. Up to eight active jobs
can be queued; execution is sequential to bound CPU and memory pressure. Closing a
browser does not cancel a job. Explicit cancellation kills the worker process tree
(POSIX process group; Windows uses taskkill). Stopping the server cancels workers.
After an unclean restart, unfinished jobs become interrupted and can be retried.
Retry starts the stage's work again; it does not resume FFmpeg mid-encode. If the
entire API is forcibly killed by the OS, its worker may survive: stop remaining
workers before restarting that workspace. Multi-process supervision is future work.

The web pipeline uses a bounded batch extraction path, not the existing CLI's
per-frame extraction/contact-sheet path. The older CLI contact-sheet pagination
and sampling limitations are not changed by this POC.

Generated content:

- `downloads/web/<project-id>/`: downloaded sources.
- `runs/web/state.sqlite3`: projects, draft revisions, jobs.
- `runs/web/<project-id>/`: preview video and thumbnails.
- `runs/web/<job-id>.log`: local processing diagnostics.
- `clips/web/<project-id>/<job-id>.mp4` and `.json`: exports and receipts.

There is no source-video serving endpoint or public share/upload feature. Preview
and export endpoints are for the local workspace user. Nothing is automatically
deleted: long sources and failed/cancelled partial outputs use disk space. Storage
quotas, cleanup UI, authentication, multi-user isolation, and crash-safe distributed
workers are required before considering a hosted service.

## Validation

Backend tests generate disposable synthetic media inside `runs/`, exercising real
FFmpeg preparation/export, range requests, persistence, invalid boundaries,
review-required export, immutable revisions, URL/path restrictions, and job recovery.

```bash
uv run --extra web --extra test python -m unittest discover -s tests -v
npm --prefix web run build
cd web
npx playwright install --with-deps chromium
npm run test:e2e
```

The browser test creates its own isolated workspace inside `runs/`, starts port
8010, and checks import, playback, boundary edits, confirmation reset, export,
download, reload persistence, and mobile overflow. It writes screenshots and an
export sample to `runs/web-poc-*`. Test media is synthetic, not a validated boss win.
Real YouTube acquisition and model judgment are not covered by these offline tests.
Codex adapter tests mock model responses by default. A separate opt-in test sends
only generated color-bar images to the real CLI and verifies it does not invent a
Boss victory. This consumes the signed-in account's applicable model usage:

```bash
GAME_VOD_LIVE_CODEX_TEST=1 uv run --extra web --extra test python -m unittest discover -s tests -p test_codex_analysis.py -k test_live_codex -v
```


### Compact review and per-video reset

The default editor shows the video, one zoomable range track and export in the
same view. Analysis details, numeric controls, exports and the conversation are
collapsed. Browser tests assert that the video and range/export controls fit without
scrolling at desktop 1440×900 and mobile 390×844.

`POST /api/projects/{project_id}/reset-analysis` joins cancellation of the selected
project's analysis workers, removes only their `codex/` artifacts and job logs, then
atomically deletes analysis job records and resets the draft. It increments draft
revision and `analysis_generation`. Source, preview, thumbnails, exports and other
projects survive. A shared lock with search scheduling plus generation validation
prevents an in-flight search request from resurrecting cleared work. The browser
remounts the editor, invalidates cached drafts and excludes old editing context.
Reset does not start a new analysis; the user can change the request and search again.
