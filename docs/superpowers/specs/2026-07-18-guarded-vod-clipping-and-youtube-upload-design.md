# Guarded VOD Clipping and Private-default YouTube Upload Design

Date: 2026-07-18

Status: Awaiting written-spec review

## Summary

Evolve the current agent-guided VOD clipper into a guarded, stateful workflow that is reliable with small and medium vision models, uses bounded review traffic, preserves the existing Skill-only experience for Codex, Claude Code, and OpenCode, generates deterministic video metadata, and can upload only validated clips to the user's own YouTube channel. Uploads default to private.

The system remains local and single-user per installation. Any user may install it, supply their own Google OAuth Desktop Client, authorize their own channel in a browser, and use the same workflow without relying on a central service.

## Goals

- Preserve Skill-only operation as a first-class supported mode.
- Make every review stage explicit, bounded, resumable, and machine-readable.
- Prevent contact-sheet truncation, stale-frame mixing, and unbounded frame extraction.
- Let agents and optional model adapters submit the same observation schema.
- Keep final correctness decisions in deterministic code rather than model prose.
- Support a generic game profile plus an initial Soulslike profile.
- Fail closed when successful-attempt continuity is uncertain.
- Generate deterministic filenames and safe YouTube metadata.
- Support both confirmed and fast private-default upload flows.
- Use user-owned OAuth credentials and local secure token storage.
- Prevent accidental source-VOD uploads and duplicate clip uploads.

## Non-goals for V1

- A hosted multi-user or multi-tenant service.
- A background watcher that uploads without a per-run user action.
- Automatic public or unlisted publishing.
- A bundled shared Google OAuth client owned by this project.
- Built-in integrations for every model provider.
- A claim of universal computer-vision accuracy across all games.
- Automatic upload when clip continuity remains unresolved.
- Uploading, redistributing, or exposing the source VOD.

## Accepted Product Decisions

- Use the guarded pipeline approach rather than prompt-only patches or a fully automatic CV system.
- Keep the existing agent Skill workflow as a first-class mode.
- Use a provider-neutral review-packet and observation-JSON boundary.
- Use a generic core with versioned game profiles; ship a Soulslike profile first.
- Each installation serves one local user and one authorized YouTube identity at a time.
- Each user supplies their own Google OAuth Desktop Client configuration.
- Support two private-default upload modes:
  - Interactive preview and confirmation.
  - An explicit non-interactive private-upload command for the current run.
- Both upload modes default to private.
- Mode B always creates a private video.
- Mode A may select private, unlisted, or public only when metadata is fully verified and only in the exact metadata revision that the user previews and explicitly confirms.
- If clip correctness is uncertain, stop before cutting or uploading.
- If only game or boss metadata is uncertain, use a generic title, upload privately, and mark the receipt for metadata review.

## Current Problems Being Addressed

The current contact-sheet command reads every JPEG in a directory, applies one fixed tile, and emits only one image. Frames beyond the tile capacity are silently omitted. A three-hour coarse scan at one frame per minute produces 181 frames, while the default sheet holds only 20.

The current sampling implementation launches FFmpeg once per timestamp. The Skill's whole-range 60 FPS recommendation can therefore launch thousands of processes and generate thousands of full-resolution JPEGs.

Sampling into an existing directory overwrites matching frame names but leaves older trailing frames. The sheet command then globs every JPEG, so frames from separate sampling runs can be mixed.

Sheets do not burn a frame ID or timestamp into each cell, forcing a model to infer the mapping between visual cells, filenames, and the JSON manifest.

The clipping boundary check validates only that victory plus postroll occurs after the start. It does not independently require start to precede victory or validate all timestamps against the source duration.

The existing tests cover timecode behavior and Skill metadata, but not media extraction, sheet coverage, clipping boundaries, state transitions, or upload behavior.

## Delivery Decomposition

This document is the integration contract for four ordered implementation slices:

1. Media correctness: finite timestamps, structured probing, batch extraction, pagination, overlays, output validation, and synthetic-media tests.
2. Guarded workflow: schemas, run layout, state reducer, profiles, bounded refinement, and the revised Skill-only procedure.
3. Naming and publishing: clip manifests, deterministic metadata, configuration, OAuth, private-default upload, resumability, and idempotency.
4. Adapter boundary: the provider-neutral observation contract and adapter conformance tests.

Each slice must pass its own acceptance tests before the next slice depends on it. V1 defines the adapter boundary but does not need to ship a provider-specific adapter.

## Architecture

The two review modes share one deterministic core:

    Source VOD
        |
        v
    Deterministic Orchestrator
        |
        v
    Review Packet
        |-------------------------------|
        v                               v
    Skill-only Agent                Optional Adapter
    Codex / Claude / OpenCode        Provider-specific process
        |                               |
        |-------------------------------|
                        |
                        v
                Observation JSON
                        |
                        v
              State Reducer and Gates
                        |
                        v
              Validated Clip Manifest
                        |
                        v
             Naming and Upload
             private by default

An agent or adapter may describe observations. It may not advance state, select an invalid clip, bypass validation, or call the uploader directly.

## Proposed Module Boundaries

Existing low-level modules remain focused:

- cli.py: command parsing and user-facing output.
- media.py: deterministic yt-dlp, FFmpeg, and ffprobe operations.
- process.py: subprocess execution, timeout, cancellation, and redaction.
- timecode.py: finite timestamp parsing and formatting.

New responsibilities are isolated:

- schemas.py: versioned run, packet, observation, clip, draft, and receipt schemas.
- workflow.py: state machine and next-action orchestration.
- review.py: proxy generation, batch frame extraction, pagination, overlays, and manifests.
- profiles.py: generic and game-specific profile loading and validation.
- validation.py: observation reduction, continuity invariants, and final-clip gates.
- naming.py: deterministic filenames, metadata templates, adapter fallback, and limits.
- config.py: flag, environment, dotenv, and TOML configuration precedence.
- youtube_auth.py: installed-app OAuth, browser consent, channel identity, refresh, and logout.
- youtube_upload.py: resumable private-default uploads and processing-status checks.
- publish_store.py: local idempotency, upload-session, and receipt state.

YouTube and model-provider dependencies are optional extras. Installing the base clipper must not install or require them.

## Compatibility and Skill-only Operation

The commands download, probe, sample, sheet, and clip remain available.

The repository Skill remains self-contained enough for Codex, Claude Code, and OpenCode to complete the workflow without a model SDK or provider API key. The Skill becomes a concise state-machine procedure with exact commands, allowed observation values, and stop conditions.

The high-level workflow writes the current task to disk and prints it through a next command. An agent does not need to remember candidates or prior decisions from conversation context.

Suggested high-level interface:

    game-vod-clipper workflow start SOURCE [--profile PROFILE]
    game-vod-clipper workflow status RUN
    game-vod-clipper workflow next RUN
    game-vod-clipper workflow observe RUN --input OBSERVATIONS.json
    game-vod-clipper workflow cut RUN
    game-vod-clipper workflow validate RUN

The same observation file can be produced manually, by a coding agent following the Skill, or by an optional provider adapter.

## Run Layout

Every workflow receives a unique run ID. Reusing another run's review directory is forbidden.

    runs/<run-id>/
      run.json
      source.json
      proxy/
        review.mp4
      discover/
        frames/
        samples.json
        sheets/
        sheets.json
      refine/
        <round-id>/
      observations/
      validation/
      clip.json
      youtube-draft.json
      upload-receipt.json

Final media remains under clips/. Downloaded source media remains under downloads/. Review media remains under runs/.

Manifests, rather than directory globs, are the source of truth for frame ordering and coverage.

## Workflow States

The primary state path is:

    INGESTED
      -> DISCOVERING
      -> CANDIDATES_FOUND
      -> REFINING
      -> BOUNDARIES_VERIFIED
      -> CUT
      -> FINAL_VALIDATED
      -> METADATA_DRAFTED
      -> UPLOADING
      -> UPLOADED

Every stage has one operational status:

    pending | running | passed | blocked_review | failed

blocked_review is used when more semantic evidence or user input could resolve the run. failed is used for invalid configuration, permanent media errors, authorization failures, rejected uploads, or broken invariants.

## Ingest and Review Proxy

For a local source, the workflow probes media with structured ffprobe JSON and creates a review proxy no larger than 480p. The check command treats ffprobe as a required trusted companion to FFmpeg for guarded workflows.

For a YouTube source, the workflow first retrieves a whitelisted metadata subset, then downloads a review representation no larger than 480p. Once boundaries are verified, it obtains only the required high-quality section with sufficient lead-in and postroll margin, or cuts from an already available high-quality local source.

Source descriptions, comments, and other uncontrolled metadata are not inserted into model prompts. Only explicitly whitelisted fields such as source ID, source title, upload date, channel name, and duration may enter a manifest. Whitelisted strings are still treated as untrusted data and passed in structured fields, never concatenated into model instructions.

A remote adapter receives review packets only. It never receives the complete source video. Remote adapter use requires explicit user configuration.

## Sampling Budget

### Discover

- Cover the complete source timeline.
- Extract at most 120 full-frame review images.
- Compute the interval as max(30 seconds, duration divided by 119).
- Include both the first and final timeline positions, de-duplicate coincident positions, and still enforce the 120-frame maximum.
- Extract frames in a bounded batch operation rather than one FFmpeg process per image.
- Produce sheets with at most 16 cells each.
- Render frame ID and precise timestamp inside every cell.
- Produce sheets.json mapping page and cell to frame ID and source seconds.
- Fail if manifest coverage and rendered coverage are not both 100 percent.

### Refine

- Sample candidate ranges every two to five seconds.
- Cap a refinement packet at 160 frames.
- Split longer ranges into adjacent bounded packets rather than exceeding the cap.
- Use overview frames for scene context and separate targeted ROI crops when a profile defines a boss HUD or victory-text region.

### Suspicious windows

- Cheap continuous signals may flag black frames, scene changes, red-dominant flashes, boss-HP disappearance, and profile-specific OCR matches.
- These signals increase recall only; none can prove success.
- Inspect approximately four seconds before and after a suspicious event at 0.25 to 0.5 second intervals.
- Native frame-level extraction is allowed only in a target window no longer than two seconds.
- Permit at most two semantic refinement rounds for the same unresolved question.
- If continuity is still uncertain, set blocked_review.

## Game Profiles

Every profile has an ID, semantic version, supported games, optional languages, ROI definitions, cue definitions, and phase-transition exceptions.

The generic profile supplies:

- The shared observation vocabulary.
- General arena, boss-bar, death, loading, respawn, runback, victory, reward, and uncertainty rules.
- Conservative validation behavior.

The initial Soulslike profile adds:

- Boss-bar and centered-title regions.
- Death and victory cue vocabulary.
- Boss-name aliases.
- Reward and rune/soul cues.
- Known legitimate multi-phase transitions.

Profiles may improve recall and naming. They may not weaken the global rules that exclude failure context or require victory and postroll.

The selected profile ID and version are recorded in run.json and clip.json.

## Observation Contract

Agent and adapter output uses a versioned schema. A representative record is:

    {
      "schema_version": 1,
      "run_id": "run-...",
      "stage": "REFINE",
      "packet_id": "refine-02",
      "frame_id": "f0042",
      "signals": ["BOSS_ACTIVE", "BOSS_HP_LOW"],
      "game_candidate": "Elden Ring",
      "boss_candidate": "Malenia",
      "evidence": ["VISIBLE_BOSS_BAR"],
      "uncertain": false
    }

Allowed signal values include:

- ARENA_ENTRY
- BOSS_ACTIVE
- BOSS_HP_HIGH
- BOSS_HP_MID
- BOSS_HP_LOW
- PLAYER_DEATH
- LOADING
- RESPAWN
- RUNBACK
- HP_RESET
- VICTORY
- REWARD
- UNCERTAIN
- OTHER

Unknown fields may be retained for forward compatibility, but unknown enum values do not affect state and trigger schema feedback.

Model-reported confidence may route another review pass. It cannot satisfy a hard validation rule.

## Deterministic Validation

The reducer accepts only a continuous successful-attempt path:

    optional ARENA_ENTRY
      -> one or more BOSS_ACTIVE observations
      -> VICTORY or REWARD

From selected start through victory, the following invalidate the candidate:

- PLAYER_DEATH
- Failure-caused loading
- RESPAWN
- RUNBACK
- An unexplained HP_RESET
- Unresolved UNCERTAIN evidence
- Combat from an earlier attempt that later fails

The chosen start must follow the latest resolved failure context and should retain a clean same-attempt arena entry when available.

The victory timestamp must be strictly after the start. Postroll defaults to eight seconds and must be between five and ten seconds. Victory plus postroll must not exceed source duration; if the source does not contain at least five seconds after victory, the run cannot satisfy final validation.

The final re-encoded clip is sampled and checked again. It is not FINAL_VALIDATED until its opening, internal continuity, victory evidence, output duration, streams, and postroll pass.

## Uncertainty Policy

Clip uncertainty and metadata uncertainty are different:

- If death, retry, continuity, winning-attempt start, or victory remains uncertain, stop before cutting or uploading.
- If the clip is FINAL_VALIDATED but only game or boss identity is uncertain, create generic metadata, set needs_metadata_review to true, and allow a private upload.

This distinction is enforced in schema and state transitions rather than left to prompt interpretation.

## Clip Manifest

clip.json includes:

- schema version and run ID.
- Clip path, SHA-256, byte size, duration, and media streams.
- Source ID and private local source reference.
- Attempt start, victory timestamp, final end, and postroll.
- Verified game and boss facts with evidence provenance.
- Outcome fixed to victory.
- Selected profile ID and version.
- Validation checks and final validation status.
- Reviewing source: skill agent, adapter ID, or user.

The uploader accepts clip.json, not an arbitrary video path. It rejects manifests that are not FINAL_VALIDATED, do not match the current file hash, or point outside clips/.

## Naming

Local filenames and YouTube titles are separate.

The deterministic local filename format is:

    {game_slug}__{boss_slug}__win__{source_id}__{sha8}.mp4

If the game or boss is unknown:

    boss-win__{source_id}__{start_ms}-{end_ms}__{sha8}.mp4

YouTube metadata is built from a user-owned channel profile. A naming adapter, if configured, receives only allowed verified facts, locale, and style settings.

It must not infer or claim:

- No-hit or no-damage play.
- First attempt.
- Difficulty.
- Build, weapon, platform, or challenge rules.
- A translated boss proper name not present in a verified alias map.

The adapter returns only title and short summary. Description boilerplate and tags are deterministic.

Invalid adapter JSON receives at most one schema retry. After that, deterministic templates are used.

If game or boss identity is unresolved, the safe title is:

    Boss Victory | {source_date_or_id}

The draft is marked needs_metadata_review.

Title, description, and tags are validated against current YouTube API constraints. User-authored values are never silently truncated or modified.

## Configuration

Precedence is:

    command-line flags
      > process environment or dotenv
      > user config TOML
      > built-in defaults

Dotenv may contain paths and non-sensitive preferences. It must not contain access tokens, refresh tokens, authorization codes, or resumable session URLs.

Example non-sensitive values:

    GVC_YOUTUBE_CLIENT_SECRETS=/secure/path/client_secret.json
    GVC_CHANNEL_PROFILE=/secure/path/channel-profile.toml

The channel profile contains:

- Expected channel ID and display title.
- Locale and metadata templates.
- Default category and tags.
- Audience choice.
- Synthetic-media declaration.
- notifySubscribers preference.
- Rights acknowledgement.

Audience, synthetic-media declaration, category, and rights acknowledgement are required before non-interactive upload. They are never inferred from game type. The built-in notifySubscribers default is false; the selected value is still shown in Mode A and recorded in every draft.

## OAuth and Channel Identity

Each user creates and supplies a Google OAuth Desktop Client and enables the YouTube Data API for their own project.

Commands:

    game-vod-clipper youtube-auth login
    game-vod-clipper youtube-auth status
    game-vod-clipper youtube-auth logout

Login uses installed-app browser authorization with PKCE and the minimum youtube.upload scope for V1.

The refresh token is stored in the operating-system keyring. Access tokens remain in memory. Client configuration stays outside the repository.

Status displays channel ID, channel title, granted scopes, and credential health. It never prints tokens.

Logout revokes authorization when possible and removes the local keyring entry.

The authorized channel identity must match the target channel in the upload draft.

V1 does not change privacy after upload. Updating an existing video's privacy requires a broader scope than youtube.upload. Users change an already uploaded video's visibility through YouTube Studio. A future CLI post-upload publishing feature requires a separate design, broader consent, and an explicit publish action.

## YouTube Draft

youtube-draft.json includes:

- Schema version.
- clip.json path and clip SHA-256.
- Target channel ID and title.
- Title, description, tags, category, and language.
- privacyStatus, defaulting to private.
- Audience and synthetic-media declarations.
- notifySubscribers.
- Rights acknowledgement.
- needs_metadata_review.
- Canonical metadata hash.
- Approval mode and approval timestamp when applicable.

Changing clip bytes, channel, privacy, audience, or any metadata invalidates an existing approval hash.

## Private-default Upload Modes

### Mode A: interactive confirmation

    game-vod-clipper youtube prepare RUN
    game-vod-clipper youtube upload DRAFT --confirm METADATA_HASH

Prepare displays the channel, file hash, title, description, tags, selected visibility, audience, disclosure, rights acknowledgement, and subscriber-notification choice. The user may edit supported fields, regenerate the hash, and then confirm the exact revision. Upload remains blocked until audience, synthetic-media declaration, category, and rights acknowledgement are explicit.

Mode A exposes private, unlisted, and public as explicit visibility choices to meet YouTube's required upload controls. Private is always preselected. Choosing unlisted or public changes the metadata hash and requires confirmation of that exact revision. If needs_metadata_review is true, visibility is locked to private. An unverified API project may still force the uploaded video to private; the receipt records the actual value returned by YouTube.

### Mode B: explicit fast private upload

    game-vod-clipper workflow finish RUN --upload-private

The upload-private flag must be present in the current command. It cannot be enabled only by dotenv or a persistent background setting.

Mode B uses deterministic channel-profile metadata. It stops if final validation, channel matching, audience, synthetic-media declaration, category, rights acknowledgement, credential health, or file hash checks fail.

Metadata uncertainty alone permits the generic private title and sets needs_metadata_review. Mode B does not accept a privacy override.

Both modes default to privacyStatus private and record the actual privacy returned by YouTube. Mode B is always private; only Mode A can explicitly choose another initial visibility.

## Upload State and Idempotency

A user-local SQLite state store tracks upload jobs. It lives in the operating system's per-user application-state directory with owner-only permissions, not inside the repository or a portable run directory. Its unique artifact key is:

    channel_id + clip_sha256

Metadata hash identifies an approved revision but does not make the same binary a new artifact.

Behavior:

- If the artifact is already uploaded, return the existing video ID and receipt.
- If an upload is in progress, query and resume its existing session.
- Do not call videos.insert again after an ambiguous interruption.
- If an upload session expires and completion cannot be determined, stop for review rather than risk duplication.
- Re-uploading identical bytes requires allow-reupload and a new explicit approval.
- Concurrent attempts are serialized with a database uniqueness constraint and lock.

The secure upload state may hold a resumable session URI while required. Logs and portable receipts never contain it.

upload-receipt.json includes:

- Schema version, run ID, and clip hash.
- YouTube video ID and watch URL.
- Target channel.
- Actual privacy.
- Metadata hash.
- Upload and processing status.
- needs_metadata_review.
- Failure or rejection reason when applicable.

## Error Handling

### Media

- Reject non-finite or out-of-range timestamps.
- Require start to be strictly before victory.
- Require postroll between five and ten seconds.
- Probe duration and streams before extraction or clipping.
- Verify every expected frame exists and is non-empty.
- Write media to a temporary path, validate it, then atomically rename it.
- Do not overwrite a completed artifact without an explicit replace action.
- Apply process timeouts and surface cancellation cleanly.

### Observations

- Reject mismatched run, stage, packet, or frame IDs.
- Reject invalid schema or unknown required enum values.
- Permit one adapter schema retry.
- Persist all accepted observations and reducer decisions.
- Move unresolved semantic questions to blocked_review after two refinement rounds.

### OAuth and API

- On 401, refresh once; if it fails, require login.
- Classify 403 errors; quota and permission failures do not receive tight retries.
- Treat invalid 400-series metadata as a permanent draft error.
- Redact Authorization headers, OAuth codes, tokens, and session URIs.

### Resumable upload

- Treat HTTP 308 as an expected incomplete state.
- Query the committed byte range before resuming.
- Retry network errors and documented retryable 5xx responses with exponential backoff, full jitter, and Retry-After support.
- Treat an expired or ambiguous session as blocked_review when duplicate risk exists.
- Poll processing status conservatively and persist rejection reasons.
- Do not report success until a video ID exists and the receipt reflects YouTube's response.

## Security and Privacy

- Never accept raw YouTube passwords or login cookies as authentication.
- Never store OAuth credentials in repository files.
- Never pass the complete source video to an adapter.
- Never upload a source path from downloads/.
- Never upload a clip without a matching FINAL_VALIDATED manifest.
- Treat downloaded metadata as untrusted input and whitelist prompt fields.
- Keep generated media under downloads/, runs/, or clips/.
- Redact sensitive request material in errors and debug logs.
- Require an explicit per-run upload action.

## Testing

### Unit tests

- Finite timecode parsing and formatting.
- Source-duration and start/victory/postroll boundaries.
- Versioned schema validation.
- State transitions and blocked-review behavior.
- Generic and Soulslike profile loading and merge rules.
- Observation enum handling.
- Deterministic filenames and metadata fallback.
- YouTube title, description, and tag limits.
- Canonical metadata and approval hashes.
- Path and source-upload rejection.
- Configuration precedence and secret-field rejection.

### FFmpeg integration tests

Use tiny synthetic audio/video fixtures generated with FFmpeg:

- Twenty-five frames with a sixteen-cell sheet produce two pages.
- Every page cell contains a frame ID and timestamp.
- Sheet coverage equals manifest coverage.
- Reusing a populated output directory cannot mix old frames.
- Batch extraction respects frame budgets.
- Missing-audio input remains supported.
- EOF, invalid ranges, postroll, and output duration are validated.
- Failed writes do not leave a completed-looking clip.

### Reducer and Skill tests

- A valid continuous winning attempt reaches FINAL_VALIDATED.
- Death, loading, runback, HP reset, and unresolved uncertainty block it.
- Metadata-only uncertainty permits a generic private draft.
- No model SDK or provider key is required for a Skill-only run.
- Skill commands and schema examples remain synchronized with CLI help and schema versions.

### Adapter contract tests

- Invalid JSON and unknown enums.
- Hallucinated frame IDs.
- Mismatched run and packet IDs.
- One retry followed by deterministic fallback or blocked review.
- No adapter can advance workflow state directly.

### YouTube tests

Use a fake HTTP transport; unit and integration tests never upload real media:

- OAuth redaction and credential refresh.
- Authorized-channel mismatch.
- Mode A approval hash.
- Mode B explicit private gate.
- Duplicate and concurrent upload prevention.
- Resume after 308 and retryable 5xx.
- 401, 403, permanent 400, and expired-session behavior.
- API-forced private response.
- Processing failure and rejection receipt.
- Refusal to upload downloads/ or a non-validated artifact.

## Acceptance Criteria

- A long VOD produces complete, paginated, timestamped review coverage without silent truncation.
- The default discover stage never exceeds 120 frames.
- Whole-fight frame-level extraction is impossible through the guarded workflow.
- Reused run directories cannot contaminate a new review packet.
- An agent can complete the workflow by reading only the repository Skill and using the CLI.
- An optional adapter can replace only the observation step through the same JSON schema.
- No failed or uncertain attempt can become a validated clip.
- Metadata-only uncertainty can produce a clearly flagged generic private upload.
- Both upload modes default to private, and Mode B cannot override private.
- Mode A exposes private, unlisted, and public, and requires a new exact confirmation when visibility changes.
- No upload occurs from dotenv configuration alone.
- The same clip bytes are not uploaded twice to the same channel by default.
- Tokens and resumable session data do not appear in logs or receipts.
- Existing low-level CLI commands remain available.

## External Constraints and References

- YouTube API clients must let users control title, description, and privacy:
  https://developers.google.com/youtube/terms/required-minimum-functionality
- YouTube write actions require clear user initiation and final user control:
  https://developers.google.com/youtube/terms/developer-policies
- videos.insert accepts youtube.upload and supports private metadata at upload:
  https://developers.google.com/youtube/v3/docs/videos/insert
- videos.update requires broader scopes than youtube.upload:
  https://developers.google.com/youtube/v3/docs/videos/update
- Resumable upload status and retry behavior:
  https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- Installed-app OAuth guidance:
  https://developers.google.com/youtube/v3/guides/auth/installed-apps

These external rules are time-sensitive and must be rechecked against official documentation during implementation and release.
