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
- Header: actual import/review/export stage, **專案工具**, and help.
- Editor (revised layout A): the desktop shell fits the viewport without scrolling,
  with the preview above one independently scrolling workbench;
  the AI conversation keeps its full-height right column. A single ruler aligns selection,
  candidates and optional evidence. The workbench defaults to 260px, with a draggable
  divider, size buttons and a saved, window-bounded preferred height.
  Start/victory fields and independent postroll precede AI candidates. Candidate rows
  expand naturally and share the workbench scroll; never nest a vertical candidate
  scrollbar inside it. Draft/review/export stays visible below. At widths up to 640px
  or heights up to 700px, use a single natural page scroll and hide the height divider,
  including in theater mode. Never remount the player for layout changes.
- Right drawer: AI / completed clips tabs share the existing column. Keep the AI
  mounted when browsing clips, preserving unsent input and ongoing work. Clicking
  a clip directly loads its source range into the same editor. The upper source
  button returns to the fully editable source workspace, not a read-only preview.
  Connection, conversation/tasks, search and composer/model controls stay in AI.
  One assistant handles ordinary conversation and requested editor tools in the
  same transcript and composer. Attach the selected video automatically; keep
  ordinary chat available without a video or valid draft. Show a compact current
  video label and its search tasks. Browsing completed clips preserves pending
  replies and unsent input without stealing focus. Search shortcuts preserve input.
  A collapsed **用量與額度** row shows local tokens and the reported weekly usage.
  Expanding it exposes per-video counts, account quota windows/reset times, and
  explicitly estimated analysis-period changes. Keep local totals visible when
  quota lookup fails; unavailable allowance is never represented as zero percent.
- Secondary details: evidence and exploration (workbench toggle) and preview shortcuts.
  Manual actions, draft management, external Agent handoff, and processing history live
  in the **專案工具** dialog. Keep its header fixed, scroll only its content, preserve
  editor state, and restore focus on close. Processing history remains inline while
  a source is being prepared; active/failed jobs are indicated on the tools button.

The source player has transport controls without a second native seek bar. Default
to the current draft's time range, with full-source, zoom and pan controls in the
workbench. Put the current clip directly above AI reference cards. Use a solid export
frame with explicit start/victory/end labels; the victory marker is an internal point,
and the end follows the independent postroll. Start and victory use matching slim
grips and solid guides, with consistent labels for all three points. Only the export
track uses a subtle solid tint for postroll. Candidate cards have numbered text and a light dashed range guide, without
duplicating the filled draft overlay. Show candidate overlap as text. Completed exports use a list
with source timestamps, direct editing, download and file location; no second player.
Retain separate source/clip drafts, viewport and playhead on workspace switches.
Selecting a candidate immediately loads its editable range: the selected candidate,
timing controls, preview shortcut and export all use that same draft. The fixed export
footer names the current target and its start/end, with a shortcut to timing inputs.
The selected candidate detail offers a focused AI recheck of the currently displayed
range. Keep its task status, finding and timestamped evidence with that candidate;
show the exact submitted range and leave the working draft unchanged by the reply.
Candidate working edits persist locally across selection and reload; selecting the
same candidate never resets them. Late AI replies cannot overwrite another candidate
or survive a selection round trip. Selecting a candidate from a completed clip returns
to source editing while preserving the completed clip's separate working draft.
Keep the optional clip name in the fixed export footer so naming remains visible
while the workbench scrolls. Finished clips expose explicit edit and confirmed delete
actions; deleting the selected clip restores the source workspace and its draft.
Keep the footer focused on naming and exporting: name and export button align on
one row, current range sits below the name, and save/export status shares a separate
bottom row. Stack these groups in narrow panels. Keep AI search and analysis reset
with the candidate section, away from the export button. Timeline navigation uses
aligned rows for viewing shortcuts and zoom/pan; allow the title its own row in
narrow panels. Keep the useful project tools dialog explicitly named **專案工具**.
Keep the source-return button below the sticky header (including after scrolling).
Layout rules live in `workbench.css` and `clip-library.css`.

The current range's successful export state drives the workflow header. Valid ranges
export directly and are saved automatically; no review checkbox or keep tag gates export.
Candidate export history persists after timing edits, while the current range clearly
states whether it has changed since export. An export action explains its disabled
state next to the button. Local browser edits and saved drafts must be described differently.

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
- Exports require valid timing with 5–10 seconds after victory. Encourage inspecting
  the candidate, without requiring a review checkbox or claiming visual validation.

## Verification

Run `npm --prefix web run build`, the mocked chat/studio browser suite, and the
synthetic-media editor test. Inspect empty, import, guide, editing, model selection,
and completed-export views. Confirm the review and export controls fit the desktop
viewport, sidebar resizing and theater mode preserve the player, and all existing
candidate/review/AI behavior remains intact. Generated screenshots stay under `runs/`.
