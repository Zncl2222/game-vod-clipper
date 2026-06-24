# Agent Workflow

This repository is designed for Claude Code, Codex, OpenCode, and similar coding agents. Use the repository skill as the primary workflow for clipping successful boss fight attempts from YouTube or local game livestream VODs.

## Primary Skill

Load or follow `skills/game-vod-boss-clipper/SKILL.md` when the user asks to clip a boss fight, boss win, successful attempt, victory moment, Elden Ring/Dark Souls boss kill, or similar gameplay segment.

The skill contains the full workflow for setup, trusted FFmpeg requirements, download, sampling, visual inspection, clipping, and validation.

## Non-Negotiable Rules

- Do not include earlier failed attempts, death screens, loading screens after death, or runback footage before the winning attempt.
- The final clip must include the boss victory moment and 5-10 seconds after it.
- Keep generated media under `downloads/`, `runs/`, or `clips/`.
- Do not upload or redistribute the user's source video.

## Fallback

If your environment does not support loading repository skills, read `skills/game-vod-boss-clipper/SKILL.md` directly and follow it as procedural instructions.
