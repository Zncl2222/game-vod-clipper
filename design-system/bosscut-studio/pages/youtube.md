# YouTube connection, livestream import and publishing

Inherits `../MASTER.md`; keep the forest/lime palette, Noto Sans TC, existing
primary/secondary buttons and native dialog interaction.

- Entry: **我的 YouTube** below library import; the URL import view also links here.
- One dialog, with **連接頻道 → 挑選直播 → 確認後上傳** as the orientation cue.
- First use shows three setup steps. Once configured, keep replacement settings in
  a disclosure. Connected users see their channel and livestream list immediately.
- List rows show name, duration, date, privacy, a selection checkbox and an import/open action.
  Explain unavailable/private/processing items inline. Search applies to loaded
  rows, with an explicit next-page button.
- Keep selection across search and pagination. Select-all applies to the current
  filtered list, excludes unavailable/imported/waiting items, and caps selection at
  100. Show the count and a clear-selection action; pin **匯入所選（N）** in the footer.
- Batch submission keeps the dialog open and explains sequential work. Show the
  durable queue in a native disclosure: current download first, five visible rows
  with an explicit show-all action, individual cancel/retry and open-workspace
  controls. Closing the dialog preserves queued work. Failed submissions retain
  selection. Selection itself never starts work.
- The visible AI checkbox and model select apply to imports. Future-stream watching
  is an optional disclosure, off by default, with its saved model shown when enabled.
- Put **上傳 YouTube** next to download on each completed clip. Pre-fill the title
  and source range, default privacy to private, and require the audience choice.
  Show the destination channel and selected privacy beside the confirm action.
- Upload receipts use text statuses and progress, clear pause/resume controls and
  an external link on completion. Failed forms retain input. Expired upload sessions
  require the user to check Studio before explicitly restarting.
- No tab, dialog opening, search or resizing starts a download, analysis or upload.
- Dialog header and footer stay visible; only content scrolls. Escape always closes
  the dialog, including from its search field, and restores focus. Tabs support
  Left/Right/Home/End. Controls are at least 44px tall with semantic text labels.
- Verify at 1440×900, 375×812 and 812×375, reduced motion, keyboard and axe contrast.
  Keep original editor state intact under the dialog. Monkey tests use a reproducible
  seed and exercise navigation, filtering, toggles, resizing and return paths.

Artifacts: `runs/youtube-ux/{setup,desktop,mobile,upload,batch-import-desktop,batch-import-mobile}.png` (mock data).
