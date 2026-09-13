# Game VOD Clipper

Agent-guided tooling for clipping clean boss-fight victories from long game livestream VODs.

This project combines a Python CLI with an agent skill:

- `game-vod-clipper`: downloads, probes, samples, contact-sheets, and cuts video with `yt-dlp` and FFmpeg.
- `skills/game-vod-boss-clipper/SKILL.md`: tells an AI coding agent how to inspect the VOD, find the successful boss attempt, avoid failed attempts, and validate the final clip.

The CLI handles deterministic media work. The agent handles visual judgment.

## Web POC — React + FastAPI

A local, single-user editing workspace is now available. It supports importing local
videos or a YouTube URL, background preview generation, thumbnail seeking, start /
victory / postroll controls, Agent JSON handoff, saved drafts, and MP4 export.
**Chat and visual analysis share the Codex CLI connection and model picker.** It reuses the CLI's
existing login, reviews sampled frames, and proposes timestamps for human review.
No separate API key is needed when Codex is signed in with ChatGPT. Manual editing
and external Agent JSON import also remain available.

From the repository root (Python 3.11+, Node 22.12+, trusted FFmpeg and ffprobe):

```bash
uv sync --extra web
npm --prefix web ci
npm --prefix web run build
uv run --extra web game-vod-web
```

Open **http://127.0.0.1:8000**. The backend serves the built React app, so only one
server is needed. Keep this terminal running while processing videos. In a remote
development container, privately forward port 8000 to your own machine.

Local import lists files already under `downloads/` and `clips/`. Put a new source
recording in `downloads/`, then open the import dialog. The browser never uploads
your source file. Preview files and task state live in `runs/web/`; exports and
their JSON receipts live in `clips/web/`. Source videos are never overwritten.
Each web export is saved as `clips/web/<project-id>/<job-id>.mp4` under the
backend workspace (`GAME_VOD_ROOT` if configured). The finished clip's
**檔案儲存位置** disclosure shows its path. **下載 MP4** saves another copy through
your browser's download location.

See [the POC guide](docs/web-poc.md) for development, the Agent JSON contract,
testing, and current limitations.

### Chat and control the editor

The desktop workspace includes a searchable media library, an import/review/export
step indicator, and **操作指南** with a walkthrough and keyboard shortcuts. Import
and help stay available in the collapsed library rail. The buttons at the top of
each sidebar collapse or expand it; visibility and expanded widths are remembered
on this browser. Collapsing a panel preserves the working draft, playback, library
search, and unsent conversation input for reopening it. The import dialog
can refresh the local source list without closing; invalid URLs and
source errors include recovery guidance. The player footer keeps draft status,
clip length, review confirmation, and export availability visible together.
The shared visual rules live in [the desktop design system](design-system/bosscut-studio/MASTER.md).

The main view keeps the video, one range timeline, previews and export together.
**AI 對話** opens an optional conversation panel; on smaller screens it opens a
full-height drawer. Numeric editing controls stay visible in the workbench;
**手動操作與草稿管理** expands manual shortcuts and save/restore actions. Account controls live behind **帳號設定**;
search progress appears below the video and in the conversation; advanced Agent import/export and media job history are collapsible.

- **一般聊天** supports ordinary conversation without attaching project metadata.
- **剪輯助理** attaches the selected project's title, duration, and current draft
  timestamps. For example, type `把勝利後收尾改成 8 秒` or `跳到 1 分 30 秒`.
  Valid commands update the local draft or seek the preview. Changes invalidate
  manual review; saving and exporting still use the workspace controls. Explicit
  requests such as `搜尋前 10 分鐘的成功挑戰` schedule a bounded visual search.
  Ordinary conversation does not start media work. Selecting a project defaults
  to editing mode; you can switch back to general chat at any time.
- The model picker uses official App Server `model/list` results. Your selection
  applies to the next message and search task. Searches require image support and
  retain their selected model when retried. There is no silent model fallback.
- **一鍵搜尋成功挑戰** and typed search instructions both use `/api/codex/chat`
  and the same validated task queue. Progress, cancellation, results, and candidate
  application appear in conversation task cards. Follow-up questions receive the
  latest project search result; explicit cancellation can also be requested in chat.
- Chat supports follow-up questions, **新對話**, and **停止回應**. Recent messages
  remain in the current browser tab's session storage; the last 24 messages within
  a 24,000-character budget are included in each request. Messages are sent to the
  selected model under the connected account. Chat does not save transcripts in
  the project store. Switching accounts clears the current transcript.
- Replies proposing editor commands are validated against the source duration.
  A reply cannot overwrite a draft edited during generation or target a different
  project after switching. No command can mark footage as reviewed or export it.

The chat endpoint sends newline-delimited status and final-response events;
responses appear when the model has completed its structured answer. Chat calls
have a 120-second limit. Stopping a reply cancels its subprocess; an already queued
search is cancelled through its task card or an explicit chat request. Chat and
visual review use the same `codex_runtime.py` executor with isolated invocations.
The legacy analyze endpoint remains a compatibility wrapper around the same queue.

Run the lightweight tests without the video fixtures:

```bash
python -m unittest discover -s tests -p test_codex_connection.py -v
python -m unittest discover -s tests -p test_codex_chat.py -v
python -m unittest discover -s tests -p test_ai_dispatch.py -v
PYTHONPATH=tests python -m unittest test_codex_analysis.CodexStreamingTest -v
cd web
npm run test:chat
```

The chat UI suite uses mocked API responses and metadata, with one browser worker;
it never loads the existing FFmpeg fixture or calls a real AI model.

### Visual clip workspace

AI publishes multiple **候選片段** during analysis, including when its overall result
is uncertain. The full-video overview shows numbered ranges for possible victories,
fights, deaths/retries and unclear events. Click a marker to seek, then use
**預覽 #N**, **上一段** / **下一段** to check the source footage. Overlapping segments
occupy separate rows; the colored bars show their actual time spans.

Each segment retains its ID and display number when a continued analysis refines
its boundaries. **待核對／保留／排除** tags are saved to the project and survive reloads.
Chat understands references such as **查看 #2**, using the same stored candidates.
Selecting or tagging an annotation does not change or approve the export draft.
For a possible victory with a known victory time, **將 #N 放入剪輯草稿** loads an
unreviewed draft with 5–8 seconds of postroll, depending on the remaining footage.
Annotations with an unknown victory remain previewable without inventing a win.
Stopped or incomplete analysis keeps the annotations already found; an empty
result does not manufacture candidates. Older single-result jobs with usable
timestamps also appear as provisional annotations.

Candidate identities are assigned by the host, not generated job prefixes. Updates
reuse the same encounter, and explicit replacement retires old hypotheses. Exact
legacy duplicates are consolidated for both the UI and chat without deleting old
analysis artifacts or review tags. Long candidate overviews scroll within the panel.
Sampling requests are deduplicated against both completed and queued coverage, and
checked again immediately before execution. Refinement uses fixed density levels
and completes a requested pass before opening another. After three extra passes
without a new encounter, victory/failure decision or meaningful boundary change,
the host stops expanding exploration, finishes required checks and returns
**uncertain** with playable candidates. This stopping state survives continuation;
it does not approve export. Completed results explicitly report search coverage
and a completion reason, and do not offer continuation when no work remains.

The editor keeps layout **A**'s unified **剪輯與原片對照** workbench beneath the
source preview, beside a full-height AI conversation. One time ruler aligns the current selection,
AI candidates, and optional exploration/evidence tracks. The workbench scrolls
independently, so inspecting more candidates keeps the source video visible.
The workbench starts at a compact 260px. Drag its upper divider to resize it, use
the adjacent **＋ / −** buttons, or focus the divider and use Up/Down (Shift for
larger steps), Home/End. Double-click or use reset to restore the default height.
The browser remembers the preferred height and bounds it to the available window
while preserving space for the source and export controls. Sidebar widths remain
independently resizable. On phones, the workbench uses natural scrolling height.
Export stays visible below the workbench. **劇院模式** temporarily
hides the library and chat to enlarge the preview while keeping the timeline
editable; **返回工作區** or Escape restores the layout. The same video element
retains its playback position, speed and volume. Mobile previews use the available
width at 16:9 instead of a small fixed height.

The player has playback, frame, sound, and speed controls; source seeking uses the
workbench filmstrip. Start/victory inputs and the independent 5–10-second postroll
control sit directly in the workbench. **快速核對與 AI 草稿** opens the opening/victory/ending
preview shortcuts. Search and **清除全部** remain beside review/export controls;
the AI conversation also offers search and stop/continue.

The current draft's solid frame is the export range. Text labels distinguish
**開始**, **勝利**, and **結束**; the actual end is victory plus the chosen postroll.
Hatching belongs only to that retained ending. The adjacent AI track uses numbered
reference cards and a light dashed draft guide on the same source-time scale;
it does not repeat the filled selection or postroll hatching. Selecting a card
previews it; applying it to the draft is explicit. The selected candidate reports
the overlapping duration or no overlap. Trimming and zooming update the guide
without changing the AI candidate. With no candidates, the filmstrip still shows
the selection. Numeric controls sit below these two adjacent tracks.
The **證據** button reveals aligned exploration coverage, the active sampling range,
and evidence markers. Completed clips have their own list and player below the editor.

Open **證據**, then use **重置 AI 查看進度** to stop the current analysis and
clear viewed ranges and continuation checkpoints. Candidates, review tags, the
current draft (including unsaved edits), source and exports remain available. The
next search starts fresh within the selected range instead of continuing the old
run. You can change the search range or model before starting it. This also clears
old AI conversation context so previous replies cannot restore a stopped search.

**清除全部** (accessible name: **重置分析結果**) stops this video's analysis and removes its candidates, evidence,
checkpoints, sampled images, analysis logs and current draft. It preserves the source,
preview, thumbnails, export files and export jobs, as well as other projects.
A new search starts from scratch. Draft revisions and an analysis generation
invalidate stale browser drafts, old continuations and late AI editor/search actions;
old editing context is excluded from new conversation requests after reset.

An untouched, unreviewed initial draft selects the latest candidate automatically;
while a search is running, edits made since it started are preserved. Otherwise,
select a candidate switch to load its range into the editor. Automatic candidate
selection does not pause or seek the video. Saved/reviewed drafts are
not automatically replaced on opening a project.

Drag the start and victory handles to adjust the range. Changing victory preserves
the independently selected 5–10-second post-victory ending.
Use **＋ / −** or the zoom slider to enlarge a long VOD down to a five-second
visible window. **目前剪輯** fits the draft (also the initial view); **全片** resets
the view. Use the compact pan slider or left/right buttons without changing the draft.
Ctrl/⌘ + wheel over a track zooms around the pointed timestamp; ordinary wheel
scrolling remains available. Candidates, draft, and AI coverage share the same
visible time range. The pan slider also supports arrow keys, Home and End, and touch.
The handles also support arrow keys (Shift for one-second steps). Preview uses the
existing source preview and stops at the selected end; no new encode is needed.
Existing exported MP4s have inline players in the same workspace. Candidates remain
unreviewed drafts until the user checks the footage and explicitly exports.

The chat panel has separate **AI 模型** and **思考強度** fields above the composer.
Effort choices use readable labels and the selected model's supported values;
switching to a model that does not support the current effort uses its default.

### Connect your AI account first

Install the official Codex CLI in the same environment as the backend. The
**帳號設定** button in the right-hand conversation panel opens the
**AI 帳號與連線** controls, even with an empty media library:

1. Choose **使用 ChatGPT 登入** and complete the device-code flow on OpenAI's
   official page. For a backend running on the same computer as your browser,
   **瀏覽器登入（後端在本機）** supports the browser callback flow instead.
2. Check the connected account and billing mode. ChatGPT sign-in uses the plan's
   Codex entitlement; an existing API-key login uses separately billed API usage.
   This app does not silently switch accounts, models, or billing modes.
3. Choose **測試 AI 文字回應**. This sends one fixed short message to
   `gpt-5.6-luna`, shows the actual reply, and stops after 60 seconds. It does not
   import, read, sample, download, or encode video. Opening the page only checks
   sign-in status; it does not automatically request an AI response.

Account status, sign-in, and cancellation use the official **Codex App Server**
JSON-RPC interface over local stdio. Codex owns OAuth and credential refresh;
BossCut does not read/copy `auth.json`, ask for session cookies, or store tokens
in browser storage. It shares the backend user's Codex login, so reconnecting also
changes that CLI's account. Existing CLI authentication continues to work.
Device-code login may require enabling device-code authorization in ChatGPT
security settings. A remote container should use device-code login, or complete
`codex login` in that backend environment with the appropriate port forwarding.

The short response check uses official `codex exec` with a clean configuration,
read-only sandbox, disabled shell/integrations, and an ephemeral conversation.
Temporary response files under `runs/web/ai-check/` are deleted after the check.
Login state is not proof of model access: permissions, network errors, or exhausted
usage can still prevent a response. App Server is an evolving interface; this
integration was verified with Codex CLI **0.153.4**. Keep this app a private,
single-user local service; it is not a multi-user hosted account gateway.

Official references: [App Server](https://learn.chatgpt.com/docs/app-server),
[authentication and billing modes](https://learn.chatgpt.com/docs/auth), and
[noninteractive mode](https://developers.openai.com/codex/noninteractive).

When ready, import a video and use **一鍵搜尋成功挑戰** below the player.
The default search covers the full VOD; the conversation panel allows a narrower
range. After coarse discovery, Python schedules whole-candidate inspection at
2-second then 0.5-second intervals, plus 60 samples/second around boundaries and
model-identified suspicious transitions. Detail windows over 12 seconds first
receive 0.5-second localization; the model then identifies short transitions for
frame-level review. The model can request additional ranges at fixed density levels.
Analysis and chat have no application-imposed model response timeout. Analysis
continues without fixed session time, call-count or total-frame budgets until the
review completes, exhausts useful refinement, fails, or you cancel it. The
no-progress guard counts completed extra passes, not packets of a long scan, and
does not skip mandatory coverage. Select reasoning effort beside the model;
the available choices come from that model's Codex capabilities. Unfinished results
remain uncertain. **接續細查** reuses completed observations
and continues the saved queue with the original model. Source changes invalidate
the checkpoint. Sampled images are sent to OpenAI; the source stays local.
Dense sampling improves the evidence but does not guarantee no missed frames or
CLI-equivalent judgment. Preview and manual review remain required before export.

Run only the lightweight connection tests with:

```bash
python -m unittest discover -s tests -p test_codex_connection.py -v
```

The general web/media test suites generate and process video; they are not part
of this connection-only check.

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
- Deno 2.3+ or Node.js 22+ on the backend's `PATH` for YouTube downloads
- Network access if downloading YouTube VODs

`yt-dlp` and its EJS challenge scripts are installed through the Python project.
Both the CLI and web worker automatically select Deno or Node.js. The development
container already includes Node.js 22. FFmpeg is not bundled and should be
installed from a trusted source.

If YouTube import reports `No supported JavaScript runtime` or HTTP 403, update
the project dependencies with `uv sync --extra web`, restart the backend, and retry
the failed job. This installs the updated yt-dlp and EJS scripts and enables the runtime explicitly,
including in the web worker, which ignores personal yt-dlp configuration.
See the [official yt-dlp EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
If 403 persists, the runtime fix alone is insufficient; check that the source is
public and the livestream has ended, or import your local recording. The web POC
does not support ongoing livestreams or login-required videos.

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

`sheet` prints every page plus `runs/coarse.json`, an ordered page/frame manifest.
More than 20 frames (the default 5×4 layout) produce `coarse-page-001.jpg`, etc.
Inspect all listed pages and use `runs/coarse/samples.json` for source timestamps;
only opening the first page does not complete the search. Reuse these observations
for continuity validation instead of resampling the exported clip in full.

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
