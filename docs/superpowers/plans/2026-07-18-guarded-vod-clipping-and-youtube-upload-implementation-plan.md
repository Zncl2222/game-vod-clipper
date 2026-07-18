# Guarded VOD Clipping and YouTube Upload Implementation Plan

Date: 2026-07-18

Status: Ready for implementation

Design reference:

    docs/superpowers/specs/2026-07-18-guarded-vod-clipping-and-youtube-upload-design.md

## Objective

Implement the approved guarded workflow in four ordered slices:

1. Correct and bound the deterministic media operations.
2. Add the stateful review workflow, game profiles, reducer, and Skill-only path.
3. Add deterministic naming, local OAuth, private-default YouTube upload, and idempotent resumability.
4. Formalize the provider-neutral adapter boundary without shipping a provider-specific adapter.

The implementation must preserve the current low-level CLI commands and must never require a model SDK or YouTube dependency for base clipping.

## Execution Rules

- Complete tasks in order; later tasks rely on manifests and gates created earlier.
- For each task, add or update the focused tests first and confirm they fail for the intended reason.
- Implement the smallest behavior needed to pass the focused tests.
- Run the focused test module, then the full base suite before committing.
- Commit only files belonging to the current task.
- Never inspect, modify, delete, or upload existing user media under downloads/, runs/, or clips/.
- FFmpeg integration tests use newly generated files in a temporary directory.
- YouTube tests use fake OAuth and HTTP transports. They never authorize a real account or upload real media.
- Do not add a provider-specific vision-model adapter in V1.
- Recheck the official YouTube API documentation before implementing Tasks 13 through 16.

## Technical Choices

- Continue using Python 3.11+, argparse, unittest, dataclasses, enum, json, sqlite3, pathlib, hashlib, tomllib, and tempfile.
- Use ffprobe JSON instead of parsing FFmpeg diagnostic text.
- Use one bounded FFmpeg decode per review packet instead of one process per image.
- Use Pillow for portable, manifest-driven sheet composition and ASCII frame/timestamp labels.
- Use canonical JSON with sorted keys and compact separators for hashes.
- Use TOML for user and channel profiles.
- Snapshot an immutable ReviewBudgetPolicy and maintain separate revisioned ReviewBudgetUsage. Economy limits are 24 one-page tasks, 384 cells, 28 adapter calls, 32 MiB of remote images, and protected final capacity of four pages, 64 cells, eight calls, and 8 MiB.
- Parse dotenv with a strict application-owned literal KEY=VALUE parser; do not add dotenv expansion behavior to the base installation.
- Keep YouTube libraries in an optional youtube dependency extra.
- Use the official Google OAuth and YouTube client libraries, OS keyring storage, and a user-local application-state directory.
- Hide optional imports behind clear dependency errors so base commands remain usable.
- Abstract OAuth and YouTube request execution behind protocols so all tests can use fakes.

## Standard Verification Commands

Focused unit test:

    PYTHONPATH=src python3 -m unittest tests.test_module -v

Full base suite:

    PYTHONPATH=src python3 -m unittest discover -s tests -v

Compile check:

    python3 -m compileall -q src tests

CLI smoke checks:

    PYTHONPATH=src python3 -m game_vod_clipper --help
    PYTHONPATH=src python3 -m game_vod_clipper check

When optional YouTube dependencies have been added:

    uv run --extra youtube python -m unittest discover -s tests -v

The implementation environment may set a task-specific writable UV cache when its default cache is read-only.

---

## Slice 1: Media Correctness and Bounded Review Artifacts

### Task 1: Make time and probe data finite and structured

Files:

- Modify src/game_vod_clipper/timecode.py
- Modify src/game_vod_clipper/media.py
- Modify src/game_vod_clipper/process.py
- Modify src/game_vod_clipper/cli.py
- Modify tests/test_timecode.py
- Create tests/test_media_probe.py
- Create tests/test_cli_check.py

Tests first:

1. Add test_parse_rejects_non_finite_values for inf, +inf, -inf, and nan spellings.
2. Add test_format_rejects_non_finite_values.
3. Mock command execution and assert probe_media invokes ffprobe with JSON output.
4. Assert the parsed media result includes duration, video streams, optional audio streams, dimensions, frame-rate text, and format name.
5. Assert invalid, empty, or non-finite ffprobe fields raise a focused MediaProbeError.
6. Assert check requires yt-dlp, ffmpeg, and ffprobe for guarded workflows.
7. Assert CLI errors remain concise and return a non-zero status.

Implementation:

1. Replace NaN-only guards with math.isfinite checks throughout timecode parsing and formatting.
2. Add a frozen MediaInfo dataclass and stream dataclasses.
3. Add probe_media using ffprobe -v error -show_format -show_streams -of json.
4. Keep probe_duration as a compatibility wrapper over probe_media.
5. Add explicit probe and malformed-media exception types.
6. Resolve ffprobe from PATH with the same trusted-tool guidance as FFmpeg.
7. Keep the existing probe command's formatted-duration output unchanged.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_timecode tests.test_media_probe tests.test_cli_check -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    fix: validate finite media metadata and require ffprobe

### Task 2: Add safe subprocess and atomic artifact primitives

Files:

- Modify src/game_vod_clipper/process.py
- Create src/game_vod_clipper/artifacts.py
- Modify src/game_vod_clipper/media.py
- Create tests/test_process.py
- Create tests/test_artifacts.py

Tests first:

1. Assert run_command accepts a finite positive timeout.
2. Assert subprocess timeout becomes a ProcessTimeoutError without leaking sensitive arguments.
3. Assert the redactor removes Authorization headers, access tokens, refresh tokens, OAuth codes, and resumable-session URLs.
4. Assert atomic output uses a temporary sibling with the final media suffix.
5. Assert successful validation uses os.replace and failed validation removes only the temporary file.
6. Assert existing completed output is refused unless replace is explicit.
7. Assert generated workflow paths are restricted to downloads/, runs/, or clips/.
8. Assert absolute or parent-traversing yt-dlp output templates are rejected in guarded mode.
9. Assert existing symlinks and symlinked parents cannot escape an approved artifact root.

Implementation:

1. Add timeout and redaction hooks to run_command.
2. Preserve argv-list subprocess execution and never enable shell execution.
3. Add atomic_output_path and finalize_atomic_output helpers.
4. Add validate_generated_path and validate_safe_output_template.
5. Resolve existing path components without following an artifact path outside its approved root, and recheck the parent immediately before atomic replacement.
6. Apply atomic output to media operations as they are migrated in later tasks.
7. Keep low-level external-path compatibility behind an explicit allow-external-output option; guarded workflows never set it.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_process tests.test_artifacts -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: add safe process and atomic artifact primitives

### Task 3: Replace per-frame process spawning with bounded batch sampling

Files:

- Create src/game_vod_clipper/schemas.py
- Create src/game_vod_clipper/review.py
- Modify src/game_vod_clipper/media.py
- Modify src/game_vod_clipper/cli.py
- Create tests/test_review_sampling.py
- Create tests/media_factory.py

Tests first:

1. Test a schedule that includes the first and last decodable video PTS, de-duplicates positions, and never treats the raw container-duration boundary as an expected frame.
2. Test discover scheduling at 10 seconds, 3 hours, and a multi-hour duration.
3. Assert one packet launches one bounded FFmpeg extraction command rather than one command per frame.
4. Assert a non-empty frame directory is rejected.
5. Assert missing or zero-byte expected frames fail the operation.
6. Assert samples.json contains schema version, source identity, packet identity, exact frame order, timestamps, and relative paths.
7. Assert no stale JPEG outside the manifest can enter the packet.
8. Use short generated 1 FPS, variable-frame-rate, and audio-longer-than-video fixtures to verify batch extraction count, monotonic actual PTS, and EOF coverage.

Implementation:

1. Add versioned SampleFrame and SampleManifest dataclasses with strict read and write validators; each frame records planned target seconds and actual decoded PTS.
2. Add atomic canonical JSON writes.
3. Add build_discover_schedule with max 120 frames and complete first/last decodable-frame coverage.
4. Add build_uniform_schedule for bounded refine and suspicious windows.
5. Decode each uniform packet in one FFmpeg process and map sequential outputs to planned or reported PTS values.
6. Use fixed-width frame IDs that remain lexically sortable.
7. Make extract_frames a compatibility wrapper that writes the new manifest.
8. Add max-frames and explicit replace flags to the low-level sample CLI.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_review_sampling -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: batch bounded review-frame extraction

### Task 4: Generate complete paginated and labeled contact sheets

Files:

- Modify pyproject.toml
- Modify uv.lock
- Modify src/game_vod_clipper/review.py
- Modify src/game_vod_clipper/media.py
- Modify src/game_vod_clipper/cli.py
- Create tests/test_review_sheets.py

Tests first:

1. Create a synthetic 25-frame manifest and assert a 16-cell layout produces two pages.
2. Assert every manifest frame appears exactly once in sheets.json.
3. Assert page and cell mappings point to the correct frame ID and source timestamp.
4. Assert each rendered page has the expected dimensions and non-empty label strip.
5. Assert page one uses the requested legacy output filename and later pages use deterministic page suffixes.
6. Assert a directory with JPEGs but no valid manifest is refused instead of globbed.
7. Assert an unrelated stale JPEG is ignored because it is absent from the manifest.
8. Assert invalid rows, columns, width, or non-finite values are rejected.
9. Assert remote-bound rendering stays within 1600 by 1600 pixels and 1 MiB without dropping a cell; an illegible result fails closed.

Implementation:

1. Add Pillow as a base dependency and update the lockfile.
2. Compose sheets in Python from the manifest's ordered paths.
3. Reserve a label strip for frame ID and HH:MM:SS.mmm using a bundled-safe Pillow font.
4. Cap every sheet at 16 cells in guarded mode.
5. Write versioned sheets.json with page, cell, frame ID, seconds, and image path.
6. Preserve the requested first output path for the legacy sheet command and add deterministic suffixes for additional pages.
7. Return or print the sheet manifest so agents know all pages must be reviewed.
8. Record page dimensions and encoded bytes for later ReviewBudgetUsage accounting.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_review_sheets -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: paginate and label manifest-driven review sheets

### Task 5: Enforce clip boundaries and validate atomic output

Files:

- Modify src/game_vod_clipper/media.py
- Modify src/game_vod_clipper/cli.py
- Create tests/test_clip_video.py

Tests first:

1. Reject start equal to or after victory.
2. Reject victory or victory plus postroll beyond source duration.
3. Reject postroll below five or above ten seconds.
4. Reject non-finite start, victory, and postroll.
5. Assert default postroll is eight seconds.
6. Generate a tiny audio/video source and verify re-encoded duration within a documented tolerance.
7. Verify a video-only source remains valid.
8. Verify the final output has a video stream and any expected audio stream.
9. Verify FFmpeg failure leaves no final output.
10. Verify an existing output requires replace.
11. Verify stream-copy remains an explicit opt-in and is not used by guarded workflow commands.

Implementation:

1. Probe before clipping and validate all semantic boundaries independently.
2. Require at least five seconds of source footage after victory.
3. Write to a temporary sibling and validate media streams and duration before os.replace.
4. Add replace to the CLI and preserve copy as an explicit low-level option.
5. Return a structured ClipResult internally while preserving the printed output path.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_clip_video -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v
    python3 -m compileall -q src tests

Commit:

    fix: enforce semantic clip boundaries and output validation

Slice 1 exit criteria:

- The existing unit suite passes.
- Synthetic media tests demonstrate complete sheets and valid clips.
- No guarded operation silently truncates frames, mixes runs, or leaves a completed-looking partial artifact.

---

## Slice 2: Guarded Workflow, Profiles, Reducer, and Skill-only Mode

### Task 6: Add versioned workflow schemas and an atomic run store

Files:

- Expand src/game_vod_clipper/schemas.py
- Create src/game_vod_clipper/run_store.py
- Create tests/test_schemas.py
- Create tests/test_run_store.py

Tests first:

1. Round-trip RunManifest, ReviewPacket, ObservationBatch, Observation, ValidationRecord, ClipManifest, YouTubeDraft, and UploadReceipt.
2. Reject missing required fields, wrong schema versions, non-finite seconds, and paths outside their artifact roots.
3. Assert unknown optional fields survive a read/write round trip.
4. Assert canonical JSON is stable across key order.
5. Assert run IDs and packet IDs are unique and filesystem-safe.
6. Assert JSON writes are atomic.
7. Assert an existing run cannot be silently replaced.
8. Assert state transitions are append-audited.
9. Round-trip immutable ReviewBudgetPolicy and its stable policy_hash separately from mutable, revisioned ReviewBudgetUsage counters.
10. Reject observation evidence, uncertainty scopes, and profile cue IDs outside the approved vocabularies.
11. Atomically reserve page, cell, byte, and adapter-call capacity and reject a reservation that would exceed either a stage or whole-run limit.
12. Reject an ObservationBatch with a stale or mismatched task/page ID, invented event-window ID, or missing, duplicate, out-of-order, extra, or future-page frame IDs; accept an identical replay idempotently and reject altered replay content.
13. Run concurrent reservation attempts and assert a per-run lock plus expected-revision compare-and-swap permits only one winner and one issued task.
14. Assert non-final work cannot consume the protected final reservation of four pages, 64 cells, eight calls, or 8 MiB.
15. Reserve the 1 MiB page ceiling before render, reconcile to actual bytes after temporary encoding, and refund the difference before exposure; failed encoding refunds the whole reservation.
16. Reject non-finite, negative, internally inconsistent, or unsafe custom policies, including totals smaller than protected final capacity or page limits above the hard 16-cell/1600-pixel/1-MiB work-unit ceilings.
17. Simulate a crash between reservation and reconciliation; on reopen, recover a valid temporary artifact or release the abandoned reservation with an audit event, never double-charge it.

Implementation:

1. Define enums for workflow state, stage status, signals, evidence, uncertainty scope, and review source.
2. Include PHASE_TRANSITION in the observation vocabulary.
3. Require uncertainty_scopes even when empty; separate CONTINUITY, ATTEMPT_START, and VICTORY from GAME_IDENTITY and BOSS_IDENTITY.
4. Add immutable ReviewBudgetPolicy and mutable ReviewBudgetUsage. Economy defaults are 24 pages, 384 cells, 28 adapter calls, 32 MiB remote payload, no more than two automatic candidates, and a protected final reservation of four pages, 64 cells, eight calls, and 8 MiB.
5. Add explicit from_dict and to_dict validation without adding a heavy schema dependency.
6. Add canonical_json_bytes and content_hash helpers.
7. Add RunStore.create, load, update, append_event, write_artifact, ceiling reservation, and actual-byte reconciliation.
8. Serialize mutations with a cross-process per-run lock plus expected revision; use atomic replacement for integrity only after the locked compare-and-swap succeeds.
9. Journal reservation IDs and states so resume can deterministically reconcile or release an interrupted reservation.
10. Keep portable manifests relative to the run root where possible.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_schemas tests.test_run_store -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: add versioned workflow schemas and run store

### Task 7: Add generic and Soulslike game profiles

Files:

- Create src/game_vod_clipper/profiles.py
- Create src/game_vod_clipper/profile_data/generic.toml
- Create src/game_vod_clipper/profile_data/soulslike.toml
- Modify pyproject.toml to package profile data
- Create tests/test_profiles.py

Tests first:

1. Load the built-in generic and Soulslike profiles.
2. Assert each profile has ID, semantic version, supported games, cue groups, optional normalized ROIs, and phase-transition rules.
3. Assert user profile paths load through the same validator.
4. Reject ROI coordinates outside zero to one.
5. Reject profiles that remove global forbidden signals, widen postroll, raise global review caps, or mark failure as victory.
6. Assert aliases normalize without changing the original observed text.
7. Assert selected profile ID and version serialize into run and clip manifests.
8. Reject phase-transition rules with a gap above the global 15-second cap or without explicit cue and PHASE_TRANSITION_VISUAL evidence requirements.

Implementation:

1. Add typed profile dataclasses and TOML loading.
2. Make the generic profile conservative and free of fixed HUD assumptions.
3. Add Soulslike boss-bar, centered-title, death, victory, reward, and phase-transition cue definitions.
4. Allow profiles to add evidence and exceptions only; global hard gates remain code-owned.
5. Validate phase rules against the global 15-second gap cap and bind every exception to named cue IDs.
6. Add deterministic profile selection from an explicit flag, verified game fact, or generic fallback.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_profiles -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: add versioned generic and soulslike profiles

### Task 8: Build review proxies, packets, and bounded refinement scheduling

Files:

- Expand src/game_vod_clipper/review.py
- Create src/game_vod_clipper/workflow.py
- Create tests/test_review_packets.py
- Create tests/test_workflow_scheduling.py

Tests first:

1. Assert local ingest creates a review proxy no larger than 480p.
2. Assert YouTube ingest whitelists source ID, title, date, channel, and duration while excluding source description and arbitrary metadata.
3. Assert whitelisted strings remain structured data and never become task instructions.
4. Assert discover packets cover the full timeline with at most 120 frames and 16 cells per page.
5. Assert refine packets use two-to-five-second intervals and split before 160 frames.
6. Assert suspicious windows cover approximately four seconds on each side at 0.25-to-0.5-second intervals.
7. Assert native-frame packets reject windows longer than two seconds.
8. Assert the same unresolved question permits at most two semantic refinement rounds.
9. Assert black-frame and scene-change detectors only propose windows and cannot mark validation passed.
10. Assert task text includes only the current stage, allowed enums, the exact current page, and required output schema.
11. Assert discover uses at most eight economy pages, refine/suspicious/ROI work uses at most twelve, and final retains protected reservations for four pages, 64 cells, eight calls, and 8 MiB.
12. Assert no more than two candidate windows enter automatic refinement; a third indistinguishable candidate produces blocked_review.
13. Assert overlapping suspicious windows merge before frames, ROI crops, or bytes are charged.
14. Assert native-frame review requires both a window no longer than two seconds and no more than 160 decoded frames.
15. Assert each page reserves its page/cell/call slots and 1 MiB byte ceiling before rendering, reconciles actual bytes before exposure, and charges retransmitted bytes plus another call before an adapter retry.

Implementation:

1. Add proxy generation with atomic output and structured MediaInfo validation.
2. Add whitelisted source metadata extraction for local and YouTube sources.
3. Add ReviewPacket creation from sample and sheet manifests.
4. Add schedule builders for discover, refine, suspicious, and native-frame review.
5. Add cheap black-frame and scene-change trigger hooks; keep red/HP/OCR hooks profile-extensible.
6. Rank at most two candidates using deterministic evidence; block for a user cue rather than silently discarding another plausible win.
7. Merge overlapping suspicious windows and apply native-frame caps before scheduling.
8. Reserve ReviewBudgetUsage ceilings before generation, reconcile actual bytes under the same revision protocol, and reserve retry calls/bytes before remote dispatch.
9. Persist each packet and its reason in the run audit log.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_review_packets tests.test_workflow_scheduling -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: create bounded review packets and refinement schedules

### Task 9: Reduce observations into guarded boundaries

Files:

- Create src/game_vod_clipper/validation.py
- Modify src/game_vod_clipper/workflow.py
- Create tests/test_validation.py
- Create tests/test_workflow_states.py

Tests first:

1. Reject observation batches with mismatched run, stage, packet, page, or frame IDs.
2. Reject unknown required signal values and hallucinated frame IDs.
3. Accept a clean ARENA_ENTRY to BOSS_ACTIVE to VICTORY or REWARD path.
4. Invalidate a candidate containing PLAYER_DEATH, RESPAWN, RUNBACK, or LOADING without a profile-backed phase-transition exemption.
5. Invalidate HP_RESET unless profile-supported PHASE_TRANSITION evidence accompanies it.
6. Walk backward from victory to the latest resolved failure and keep only the continuous winning attempt.
7. Keep a clean same-attempt lead-in when available.
8. Block when several bosses or victories remain ambiguous without a user cue.
9. Block after two unresolved refinement rounds.
10. Distinguish clip uncertainty from game or boss metadata uncertainty.
11. Permit metadata-only uncertainty only after final clip validation.
12. Record every reducer decision and evidence reference.
13. Treat every LOADING signal as failure context unless observations share the exact manifest event_window_id, carry PHASE_TRANSITION_VISUAL evidence and a selected-profile cue ID, fall within that rule's gap capped at 15 seconds, and contain no death, respawn, or runback.
14. Reject HP_RESET exemptions without the same event-window, time-gap, and versioned profile-rule binding.

Implementation:

1. Add a pure chronological reducer over accepted observations.
2. Separate candidate discovery, attempt segmentation, boundary selection, and hard-gate evaluation.
3. Keep profile phase exceptions explicit and bind them to manifest event-window IDs plus validated frame PTS gaps.
4. Evaluate uncertainty_scopes explicitly: clip scopes block, while identity-only scopes remain metadata uncertainty.
5. Set blocked_review instead of guessing when multiple candidates remain.
6. Produce BoundaryDecision and ValidationRecord values for later clipping.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_validation tests.test_workflow_states -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: enforce continuous winning-attempt validation

### Task 10: Expose the guarded workflow CLI

Files:

- Create src/game_vod_clipper/commands/__init__.py
- Create src/game_vod_clipper/commands/workflow.py
- Modify src/game_vod_clipper/cli.py
- Modify src/game_vod_clipper/media.py
- Modify src/game_vod_clipper/workflow.py
- Create tests/test_workflow_cli.py
- Create tests/test_workflow_end_to_end.py

Tests first:

1. Assert existing low-level commands and arguments still parse.
2. Add parser and dispatch tests for workflow start, status, next, observe, choose, cut, validate, and finish.
3. Assert start creates a unique run without touching existing runs.
4. Assert next returns a short Markdown task and a machine-readable JSON option.
5. Assert observe accepts only a valid ObservationBatch for the current issued page and requires every manifest cell exactly once in order.
6. Assert cut is impossible before BOUNDARIES_VERIFIED.
7. Assert final validation requires post-cut review evidence before FINAL_VALIDATED.
8. Assert a resumed command continues from run.json rather than conversation state.
9. Assert command errors state the required next action.
10. Drive a synthetic run with seeded observations through FINAL_VALIDATED without any model SDK.
11. Assert start accepts an optional review-budget TOML, validates it, and freezes its content hash; later environment changes do not alter the run.
12. Assert next exposes exactly one current sheet page, an immutable task_id, at most 16 cells, at most 4 KiB of instructions, and the remaining ReviewBudgetUsage plus protected capacity.
13. Assert observe requires the current task_id, persists exact cell coverage before next can issue another, treats an identical replay idempotently, and rejects altered or stale replay content.
14. Mock a YouTube source and assert BOUNDARIES_VERIFIED triggers yt-dlp section download from max(0, start minus 15 seconds) through min(duration, final end plus 15 seconds).
15. Assert the high-quality section is stored under downloads/, has a high_quality_source media role, and includes enough margin for the precise re-encode.
16. Assert cut refuses a 480p review_proxy media role and cuts only the local source or validated high-quality section.
17. Assert section-download interruption leaves no completed-looking source section or clip and a resumed run does not reuse an invalid partial file.
18. Assert the section manifest records requested source bounds, actual_source_origin, local media start, local duration, and translates every absolute boundary to a validated local timestamp before clipping.
19. Use a one-hour-offset synthetic section to prove the cutter never applies an absolute VOD timestamp directly to a rebased section.
20. Assert blocked_review with multiple candidates exposes immutable candidate IDs; workflow choose accepts only a listed ID, appends USER_CANDIDATE_SELECTION, and resumes refinement without marking validation passed.

Implementation:

1. Split command handlers from the root parser before adding workflow branches.
2. Implement the approved workflow subcommands, including choose, and JSON output mode.
3. Validate a built-in economy policy or an explicit start-time TOML, write immutable review-budget-policy.json, initialize review-budget-usage.json, and reference both from run.json.
4. Write next-task.md for exactly one page and task_id beside each active packet, then advance only after an exact, persisted ObservationBatch consumes that task.
5. Implement candidate selection only for the active ambiguity block and audit it without granting validation evidence.
6. For a YouTube source, invoke yt-dlp --download-sections for the exact high-quality section plus 15-second safety margins only after boundary verification; distinguish it from the review proxy in the media manifest.
7. Record and validate source-origin mapping, translate absolute VOD boundaries to section-local time, and fail closed if any translated timestamp falls outside the section.
8. Generate the high-quality clip only from the original local source or validated high-quality section, never the proxy.
9. Generate final review packets within all protected final reservations and require reducer approval before writing clip.json as FINAL_VALIDATED.
10. Keep all generated media inside the approved roots.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_workflow_cli tests.test_workflow_end_to_end -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v
    PYTHONPATH=src python3 -m game_vod_clipper --help

Commit:

    feat: expose resumable guarded workflow commands

### Task 11: Rewrite the Skill as a concise exact workflow

Files:

- Modify skills/game-vod-boss-clipper/SKILL.md
- Modify AGENTS.md if command routing changes
- Modify README.md
- Replace or expand tests/test_skill_metadata.py
- Create tests/test_skill_contract.py

Tests first:

1. Assert the Skill names every guarded workflow command exactly as CLI help exposes it.
2. Assert the Skill lists the observation enums and schema version.
3. Assert it preserves all non-negotiable failure, victory, postroll, storage, and source-upload rules.
4. Assert it removes whole-fight 0.0167-second extraction guidance.
5. Assert it requires review of every page listed in sheets.json.
6. Assert clip-related uncertainty_scopes and blocked_review stop conditions are explicit.
7. Assert no adapter, provider SDK, or API key is required.
8. Assert optional adapters are described only as alternate observation producers.
9. Assert the Skill lists every evidence and uncertainty-scope enum and explains that LOADING blocks unless a profile-backed phase transition is present.
10. Assert workflow next instructs the agent to inspect only its single current page and submit before requesting another.
11. Assert budget exhaustion and multiple-candidate stop conditions are explicit.
12. Assert the Skill's ObservationBatch example requires current task/page IDs, manifest event-window IDs, and exactly one ordered observation per cell.
13. Assert the Skill documents workflow choose only for listed candidates and never treats the choice itself as success evidence.

Implementation:

1. Replace repeated prose with stage-specific commands, inputs, allowed outputs, and stop rules.
2. Tell agents to run workflow next and inspect only the current single-page task.
3. Require JSON observations with task/page/event-window IDs, evidence, profile_cue_ids, and uncertainty_scopes, and prohibit hand-authored timestamp arithmetic when a frame ID exists.
4. Tell agents to submit the current page before requesting another and never carry prior visual pages in the prompt.
5. Keep a low-level fallback section for diagnosing or manually reproducing media operations.
6. Update README examples for Codex, Claude Code, and OpenCode.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_skill_metadata tests.test_skill_contract -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v
    python3 -m compileall -q src tests

Commit:

    docs: make skill follow the guarded workflow

Slice 2 exit criteria:

- A seeded Skill-only run reaches FINAL_VALIDATED without provider code.
- Invalid or ambiguous attempts stop at blocked_review.
- Profiles improve evidence without weakening global validation.

---

## Slice 3: Naming, OAuth, and YouTube Upload

### Task 12: Add layered configuration and deterministic naming

Files:

- Create src/game_vod_clipper/config.py
- Create src/game_vod_clipper/naming.py
- Create examples/channel-profile.example.toml
- Create .env.example
- Modify .gitignore
- Create tests/test_config.py
- Create tests/test_naming.py

Tests first:

1. Assert precedence is CLI, process environment, dotenv, user TOML, then built-in defaults.
2. Assert the strict dotenv parser accepts only literal KEY=VALUE entries for approved paths and non-sensitive preferences and cannot enable upload by itself.
3. Assert secret-like token, OAuth-code, session-URL, variable-expansion, command-substitution, multiline, and upload-trigger fields in dotenv are rejected.
4. Assert channel profile requires channel identity, locale, templates, category, audience, synthetic-media declaration, notification preference, and rights acknowledgement.
5. Assert notifySubscribers defaults to false.
6. Assert deterministic local naming uses verified game, boss, source ID, and clip hash.
7. Assert local-source fallback uses a stable source hash when no remote ID exists.
8. Assert unsafe path characters and reserved filenames are normalized cross-platform.
9. Assert unknown game or boss produces the approved generic filename and title and sets needs_metadata_review.
10. Assert naming never adds no-hit, first-attempt, difficulty, build, weapon, platform, or unverified translations.
11. Assert title, description-byte, and tag-count limits are enforced without silent truncation.

Implementation:

1. Load TOML with tomllib and implement a small strict dotenv parser with no expansion or third-party dependency.
2. Represent channel settings with a validated dataclass.
3. Add deterministic Unicode-safe slugging and fallback identifiers.
4. Add canonical metadata rendering from allowed facts.
5. Define a narrow NamingSuggestion protocol that returns title and summary only; do not implement a provider.
6. Hash and atomically rename the final clip when its deterministic name is known, then update clip.json.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_config tests.test_naming -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: add deterministic clip and metadata naming

### Task 13: Build YouTube drafts and exact approval gates

Files:

- Create src/game_vod_clipper/youtube_metadata.py
- Create src/game_vod_clipper/commands/youtube.py
- Modify src/game_vod_clipper/schemas.py
- Modify src/game_vod_clipper/cli.py
- Create examples/youtube-edits.example.toml
- Create tests/test_youtube_metadata.py
- Create tests/test_youtube_cli.py

Tests first:

1. Reject arbitrary video paths and require a matching FINAL_VALIDATED clip.json.
2. Reject clip hashes that do not match the current bytes.
3. Build a draft with private preselected.
4. Require explicit category, audience, synthetic-media declaration, rights acknowledgement, and notification choice.
5. Permit Mode A private, unlisted, or public only in the confirmed draft revision.
6. Lock visibility to private when needs_metadata_review is true.
7. Invalidate approval when clip bytes, channel, title, description, tags, visibility, audience, disclosure, or notification choice changes.
8. Assert prepare shows every approval field and never prints credentials.
9. Assert Mode B cannot override private.
10. Assert a user-authored invalid field reports an error rather than being silently modified.
11. Assert youtube revise DRAFT --input EDITS.toml accepts only supported fields, writes a new immutable draft revision, and changes the hash while preserving the prior draft.
12. Assert privacy changes are possible only through revise and require confirmation of the new exact hash.
13. Unit-test a pure Mode A re-upload draft builder with an injected prior artifact record; require allow_reupload and prior_video_id in the canonical hash and reject a missing record.
14. Assert Mode B draft construction cannot set allow_reupload.
15. Assert drafts live at youtube/drafts/<revision-id>.json, include revision_id and parent_revision_id, never overwrite a prior revision, and update current-draft.json atomically.

Implementation:

1. Add YouTubeDraft schema with revision linkage, re-upload fields, and canonical metadata hash.
2. Implement youtube prepare and draft validation without making a network request.
3. Print both a human preview and an optional JSON representation.
4. Implement youtube revise with a validated TOML patch and immutable revision IDs.
5. Require confirm with the exact current hash for Mode A.
6. Add a pure Mode A re-upload draft builder over an injected prior artifact record; defer publish-store lookup and CLI wiring until Tasks 15 and 16.
7. Store immutable draft revisions plus an atomic current-draft pointer.
8. Add Mode B draft construction from the channel profile, but do not upload until Task 16 and never permit re-upload intent.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_youtube_metadata tests.test_youtube_cli -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: prepare exact youtube upload drafts

### Task 14: Add user-owned installed-app OAuth

Files:

- Modify pyproject.toml
- Modify uv.lock
- Create src/game_vod_clipper/youtube_auth.py
- Create src/game_vod_clipper/secrets.py
- Modify src/game_vod_clipper/commands/youtube.py
- Modify src/game_vod_clipper/cli.py
- Create tests/test_youtube_auth.py
- Create tests/test_secrets.py

Tests first:

1. Assert base CLI imports and base tests pass without the youtube extra.
2. Assert YouTube commands give a direct install-extra error when dependencies are absent.
3. Fake installed-app login and assert the exact approved scope set is requested: youtube.upload plus youtube.readonly, with no broader account-management scope.
4. Assert client configuration inside the repository is rejected.
5. Assert refresh tokens are written only through the keyring abstraction.
6. Assert access tokens are not persisted.
7. Assert status returns channel ID, title, scopes, and credential health without token values.
8. Assert target-channel mismatch blocks later upload.
9. Assert logout attempts revocation and removes the keyring entry.
10. Assert all error rendering redacts credentials and authorization material.

Implementation:

1. Add a youtube optional dependency group with the official Google API client, Google OAuth flow, keyring, and platformdirs; dotenv parsing remains the strict dependency-free implementation from Task 12.
2. Lazy-import optional dependencies.
3. Define OAuthBackend and KeyringStore protocols.
4. Implement installed-app browser authorization with PKCE and the exact youtube.upload plus youtube.readonly scope set; request both together because installed apps do not support incremental authorization.
5. Query channels.list(part=id,snippet,mine=true) and store only the authorized channel identity needed for preflight.
6. Add youtube-auth login, status, and logout commands.
7. Use an OS application-state directory with owner-only permissions for non-secret identity metadata.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_youtube_auth tests.test_secrets -v
    uv run --extra youtube python -m unittest tests.test_youtube_auth tests.test_secrets -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: add local youtube oauth authorization

### Task 15: Persist idempotent upload jobs

Files:

- Create src/game_vod_clipper/publish_store.py
- Create tests/test_publish_store.py

Tests first:

1. Create the database in a user-local state directory with owner-only permissions.
2. Assert schema creation and versioned migrations are transactional.
3. Assert channel ID plus clip SHA-256 identifies one artifact.
4. Assert two concurrent default attempts cannot create duplicate active jobs.
5. Assert a changed metadata hash does not turn identical bytes into a new artifact.
6. Assert successful jobs return the prior video ID instead of creating a new attempt.
7. Assert resumable-session URI is stored only in the protected database and never in portable receipts or repr output.
8. Assert allow-reupload creates an explicitly linked new attempt and requires a fresh approval.
9. Assert interrupted state transitions recover after reopening the database.
10. Assert re-upload attempts are accepted only from a Mode A draft whose canonical hash includes allow_reupload and the prior video ID.
11. Assert lookup_completed_artifact returns the exact prior video and attempt needed by the Task 13 re-upload draft builder.

Implementation:

1. Define artifacts, attempts, and state-events tables.
2. Use unique constraints and immediate transactions for concurrency.
3. Add job states for prepared, session_started, uploading, uploaded, processing, completed, blocked, and failed.
4. Store session information separately from portable receipts.
5. Link an explicitly approved re-upload attempt to its prior completed attempt without weakening the default artifact uniqueness rule.
6. Expose lookup_completed_artifact through a narrow read-only protocol for draft preparation.
7. Add redacted representations for all publish-store records.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_publish_store -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: persist idempotent upload jobs

### Task 16: Implement resumable upload and both user flows

Files:

- Create src/game_vod_clipper/youtube_upload.py
- Modify src/game_vod_clipper/commands/youtube.py
- Modify src/game_vod_clipper/commands/workflow.py
- Modify src/game_vod_clipper/workflow.py
- Create tests/test_youtube_upload.py
- Create tests/test_private_upload_flows.py

Tests first:

1. Use a fake transport to assert videos.insert receives only approved snippet and status fields.
2. Assert Mode A requires the current confirmation hash and uses the selected initial visibility.
3. Assert Mode B requires the current upload-private flag and always sends private.
4. Assert dotenv or a saved preference cannot trigger upload.
5. Assert metadata-review drafts remain private in every mode.
6. Assert notifySubscribers is passed explicitly.
7. Assert HTTP 308 is treated as resumable progress and committed Range controls the next byte.
8. Assert 500, 502, 503, and 504 use bounded exponential backoff with full jitter and Retry-After.
9. Assert 401 refreshes once and then requires login.
10. Assert quota and permission 403 responses stop without tight retry.
11. Assert permanent 400 metadata errors return to draft correction.
12. Assert an ambiguous or expired session blocks rather than calling videos.insert again.
13. Assert API-forced private is recorded as actual privacy.
14. Assert processing and rejection status produce complete receipts.
15. Assert a completed artifact returns its existing video ID.
16. Assert no test contacts a real Google endpoint.
17. Assert youtube status RUN resumes only the existing session or processing poll and never creates a new videos.insert request.
18. Assert an approved Mode A re-upload creates one linked new session, while Mode B and drafts without hashed re-upload intent return the existing video ID.
19. Assert the default transfer streams the remaining file in one resumable PUT; if configurable chunk mode is enabled, every non-final chunk is a fixed 8 MiB multiple of 256 KiB.
20. Assert retryable transfer failures make at most eight attempts with full-jitter exponential delays based at one second and capped at 64 seconds; Retry-After is honored without a tight loop.
21. Assert processing polling starts at 15 seconds, backs off to at most 60 seconds, stops after ten minutes, persists processing state, and can continue through youtube status RUN.
22. Assert youtube prepare RUN --allow-reupload looks up a completed identical artifact, builds a new immutable Mode A draft revision, and still requires confirmation of its new hash.
23. Assert every attempt writes youtube/receipts/<attempt-id>.json without overwriting prior receipts and atomically updates current-attempt.json.
24. Assert clip workflow state remains FINAL_VALIDATED or METADATA_DRAFTED while independent publish-attempt states progress through upload, processing, re-upload, failure, or retry.

Implementation:

1. Define YouTubeTransport and resumable-session interfaces.
2. Implement the production transport with the official client and an injectable fake transport.
3. Start and persist a resumable session before transferring bytes.
4. Query committed ranges before every resume.
5. Stream the remaining file as one request by default to minimize request overhead; expose fixed 8 MiB chunking only as an explicit transport setting.
6. Add the bounded eight-attempt retry policy, full jitter, Retry-After handling, and redaction.
7. Write a new immutable youtube/receipts/<attempt-id>.json after every terminal outcome and atomically update current-attempt.json.
8. Keep publish-attempt state independent from the terminal clip-validation state.
9. Wire youtube prepare RUN --allow-reupload to PublishStore lookup and the pure Task 13 builder.
10. Implement youtube upload DRAFT --confirm HASH, including a separately hashed Mode A re-upload draft.
11. Implement workflow finish RUN --upload-private using a deterministic Mode B draft that cannot re-upload identical bytes.
12. Implement youtube status RUN by resolving current-attempt.json and continuing only its existing session or processing state.
13. Poll processing at 15-to-60-second intervals for at most ten minutes per command and persist nonterminal state for a later status call.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_youtube_upload tests.test_private_upload_flows -v
    uv run --extra youtube python -m unittest tests.test_youtube_upload tests.test_private_upload_flows -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: upload validated clips to youtube resumably

Slice 3 exit criteria:

- Base clipping works without YouTube extras.
- Mode A defaults to private and requires exact confirmation for any visibility.
- Mode B is explicit and private-only.
- The same bytes do not upload twice to the same channel by default.
- No credential or resumable-session data appears in logs or receipts.

---

## Slice 4: Provider-neutral Adapter Contract and Release Verification

### Task 17: Formalize the optional observation-adapter boundary

Files:

- Create src/game_vod_clipper/adapters.py
- Modify src/game_vod_clipper/workflow.py
- Create tests/test_adapter_contract.py

Tests first:

1. A fake adapter receives only the current ReviewPacket and whitelisted structured context.
2. A valid adapter result passes through the same Observation parser used by Skill-only mode.
3. Invalid JSON receives at most one schema retry.
4. Unknown enums, mismatched IDs, and hallucinated frame IDs are rejected.
5. Adapter failure moves the semantic question to blocked_review after its allowed attempts.
6. An adapter cannot mutate RunStore, advance state, cut media, name a clip, or call upload code.
7. A remote adapter requires explicit configuration and a disclosure that review images leave the device.
8. No provider SDK is present in base or youtube dependencies.
9. Assert one adapter call receives exactly one page, at most 16 cells, no prior-page observations, at most 4 KiB of task instructions, and only its whitelisted structured context.
10. Assert actual page bytes and every schema retry are reserved against revisioned ReviewBudgetUsage without mutating policy_hash before the adapter is called.

Implementation:

1. Define an ObservationAdapter protocol over ReviewPacket to observation JSON.
2. Add a small adapter runner that validates input and output but owns no workflow decisions.
3. Dispatch one page per call and charge its page, cell, byte, and call totals before sending any remote data.
4. Keep agent/manual observation submission as the default.
5. Document the interface for future OpenAI, Gemini, Ollama, or other adapters without implementing one.

Verify:

    PYTHONPATH=src python3 -m unittest tests.test_adapter_contract -v
    PYTHONPATH=src python3 -m unittest discover -s tests -v

Commit:

    feat: define provider-neutral observation adapters

### Task 18: Complete documentation, security checks, and release verification

Files:

- Modify README.md
- Modify AGENTS.md if needed
- Modify .gitignore
- Modify .env.example
- Modify examples/channel-profile.example.toml
- Modify pyproject.toml version when all acceptance tests pass
- Modify uv.lock
- Create tests/test_security_contract.py
- Create tests/test_acceptance.py

Tests first:

1. Assert ignored secret patterns include dotenv files and common OAuth client filenames while preserving .env.example.
2. Assert documented commands exist in CLI help.
3. Assert example channel profile passes the real validator.
4. Assert the base installation imports no optional YouTube or provider packages.
5. Assert uploader rejects downloads/, runs/ proxies, non-validated clips, and changed hashes.
6. Assert a full seeded Skill-only run reaches FINAL_VALIDATED and generates a draft.
7. Assert metadata-only uncertainty produces a private review-marked draft.
8. Assert continuity uncertainty never produces a clip or draft.
9. Assert all specification acceptance criteria have a named automated test or documented manual check.
10. Assert the economy run cannot exceed 24 one-page tasks, 384 cells, 28 adapter calls, or 32 MiB of remote images and retains protected final capacity of four pages, 64 cells, eight calls, and 8 MiB.
11. Assert a mocked YouTube source final clip comes from a bounded high-quality section, never its review proxy.
12. Assert documented revise, status, and explicit Mode A re-upload commands exist in CLI help and examples.
13. Assert immutable draft and receipt revisions plus current pointers survive an initial upload and an explicitly approved re-upload.
14. Assert documented candidate selection, task replay, budget accounting, and section-origin translation match real CLI behavior.

Implementation:

1. Document the guarded Skill-only workflow first.
2. Document optional YouTube installation, Google Cloud setup, browser login, channel profile, Mode A, and Mode B.
3. Document the economy ReviewBudget, one-page model tasks, explicit budget override, and blocked-review behavior.
4. Document youtube revise, youtube status, and the separately approved Mode A re-upload flow.
5. Warn that Mode A visibility may be forced private for an unverified API project.
6. Document token location and logout/revocation.
7. Document remote-adapter review-image disclosure.
8. Add troubleshooting for ffprobe, missing optional extras, blocked review, quota, and resumable sessions.
9. Bump the package minor version only after all tests and help output pass.

Final automated verification:

    PYTHONPATH=src python3 -m unittest discover -s tests -v
    python3 -m compileall -q src tests
    PYTHONPATH=src python3 -m game_vod_clipper --help
    PYTHONPATH=src python3 -m game_vod_clipper workflow --help
    PYTHONPATH=src python3 -m game_vod_clipper youtube --help
    PYTHONPATH=src python3 -m game_vod_clipper youtube-auth --help
    git diff --check

Optional-extra verification:

    uv run --extra youtube python -m unittest discover -s tests -v

Manual verification with a newly generated local fixture:

1. Start a guarded run.
2. Review every generated page through Skill-only mode.
3. Submit seeded valid observations.
4. Cut and final-validate the fixture.
5. Prepare a YouTube draft.
6. Stop before real OAuth or upload unless the user separately requests and authorizes a private smoke test.

Commit:

    docs: document guarded clipping and youtube upload

## Completion Definition

Implementation is complete only when:

- All 18 task commits are present or intentionally squashed with equivalent review boundaries.
- The full base and optional-extra test suites pass.
- Existing low-level CLI commands remain available.
- The Skill-only workflow needs no model SDK or provider API key.
- Discover review is bounded to 120 frames and every frame appears in sheets.json.
- The economy whole-run budget is enforced at 24 one-page tasks, 384 cells, 28 adapter calls, and 32 MiB of remote images, with protected final reservations in every dimension.
- A clip cannot be FINAL_VALIDATED with failure context or unresolved continuity.
- Metadata-only uncertainty remains private and review-marked.
- Mode A defaults private and Mode B is private-only.
- YouTube operations are user-initiated, idempotent, resumable, and credential-redacted.
- Existing user media has not been modified or uploaded during implementation or testing.
