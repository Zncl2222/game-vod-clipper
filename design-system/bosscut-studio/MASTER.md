# BossCut Studio · desktop design system

## Product and direction

BossCut is a local desktop workspace for finding, reviewing, and exporting complete
boss victories. The source video is the primary content. Editing stays usable
while analysis runs and while library or conversation panels are resized.

This system applies the `ui-ux-pro-max` search for **video editing creative workspace**:
Minimalism & Swiss Style, clear grids, functional hierarchy, restrained motion, and
strong text contrast. The suggested generic landing-page pattern applies only to
the empty workspace. The existing forest/lime identity is retained instead of the
database's generic video-product pink/blue palette. The existing Space Grotesk /
Noto Sans TC pairing supports the Traditional Chinese interface.

Scope: desktop windows, primarily 1280×800, 1440×900, and 1920×1080. Preserve the
existing narrow-window fallback without designing a separate mobile experience.

## Tokens

Canonical tokens are in `web/src/studio.css`.

| Role | Value |
| --- | --- |
| Canvas | `#f1f3ef` |
| Surface | `#ffffff` |
| Subtle surface | `#f7f9f5` |
| Active surface | `#eaf1e4` |
| Primary text | `#20342c` |
| Secondary text | `#5f7065` |
| Primary action fill | `#c5ef83` |
| Accent text | `#3d6539` |
| Sidebar | `#182b24` |
| Sidebar secondary text | `#acbcb0` |
| Control border | `#7c8d7a` |
| Error text | `#a43b33` |

Use semantic tokens in new styles. Main body text is 14–16px, desktop controls and
secondary labels 12–13px. Only nonessential decorative labels and timeline ticks
may use 10–11px. Numeric values use tabular figures. Use a 4/8px spacing rhythm,
6px control corners, 10px grouped controls, and 16px main panels.

## Workspace hierarchy

- Library: brand, import, searchable projects, help, local storage/connection status.
- Header: actual import/review/export stage plus help.
- Editor (revised layout A): preview above one independently scrolling workbench;
  the AI conversation keeps its full-height right column. A single ruler aligns selection,
  candidates and optional evidence. The workbench defaults to 260px, with a draggable
  divider, size buttons and a saved, window-bounded preferred height.
  Start/victory fields and independent postroll are inline; draft/review/export stays
  visible below. Never remount the player for layout changes.
- AI: connection, conversation mode, current project, conversation/tasks, search,
  composer/model controls. Technical implementation details belong in advanced help.
- Secondary details: evidence and exploration (workbench toggle), preview shortcuts,
  manual actions and draft management, completed clips, external Agent handoff,
  and processing history.

The source player has transport controls without a second native seek bar. Default
to the current draft's time range, with full-source, zoom and pan controls in the
workbench. Put the current clip directly above AI reference cards. Use a solid export
frame with explicit start/victory/end labels; the victory marker is an internal point,
and the end follows the independent postroll. Only the export track uses postroll
hatching. Candidate cards have numbered text and a light dashed range guide, without
duplicating the filled draft overlay. Show candidate overlap as text. Completed exports use a list
with source timestamps and a separate player. Layout rules live in `workbench.css`.

The current draft's review state drives the workflow header. Any timing edit clears
review. An export action explains its disabled state next to the button. Local
browser edits and explicitly saved drafts must be described differently.

## Interaction and accessibility

Apply the verified UX search **error summary validation** and React search
**forms state accessibility**: controlled form state, explicit submission, inline
field errors linked to controls, and a focusable summary for server failures.

- Native dialogs have names, Escape support, focus containment, and focus restoration.
- Import retains the entered URL on failure and can refresh sources without closing.
- Keyboard shortcuts never change the editor while a dialog or editable control is active.
- Search filters the library without switching the current project or changing its draft.
- Every icon-only action has an accessible name. Decorative SVGs are hidden from AT.
- Every state uses text or shape as well as color. Visible keyboard focus is required.
- Controls respond in 140–200ms; reduced-motion disables movement and transitions.
- Never start analysis, authentication, or export just to decorate a view.
- Final exports still require user review and 5–10 seconds after victory.

## Verification

Run `npm --prefix web run build`, the mocked chat/studio browser suite, and the
synthetic-media editor test. Inspect empty, import, guide, editing, model selection,
and completed-export views. Confirm the review and export controls fit the desktop
viewport, sidebar resizing and theater mode preserve the player, and all existing
candidate/review/AI behavior remains intact. Generated screenshots stay under `runs/`.
