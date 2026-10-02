# CLI 與 Agent

[回到繁體中文 README](../../README.zh-TW.md)

## 安裝

需要 Python 3.11+、uv，以及 PATH 中的 FFmpeg／ffprobe。YouTube 下載另需 Deno 2.3+ 或 Node.js 22+；前端開發使用 Node.js 22.12+。

FFmpeg 請使用系統可信任的套件來源或官方網站列出的發行來源，不要以不明 Python 套件代替。
在儲存庫根目錄執行：

```bash
uv sync --frozen
uv run game-vod-clipper check
```

也可安裝為使用者層級的全域工具：

```bash
uv tool install /path/to/game-vod-clipper
game-vod-clipper check
```

以下範例使用儲存庫內的 `uv run`；全域安裝後可省略此前綴。

## 交給 Agent 剪輯

請 Agent 讀取 [game-vod-boss-clipper Skill](../../skills/game-vod-boss-clipper/SKILL.md)，這是抽樣、畫面判斷、邊界檢查與成品驗證的主要規範。
可在儲存庫中直接使用以下提示，不必複製或另外安裝 Skill：

```text
請讀取 skills/game-vod-boss-clipper/SKILL.md 並依照流程，
從這部 VOD 剪出完整的 Boss 成功挑戰：<YouTube 網址或本機路徑>。
排除失敗嘗試、死亡、讀取、重生與跑圖，保留勝利後 5–10 秒。
完成後驗證影片並回報輸出路徑、原片時間與仍有疑慮的地方。
```

CLI 負責可重現的媒體處理，Agent 負責視覺判斷。單純執行裁切指令不代表已確認該區間是完整勝利。

## 命令範例

下載與讀取影片資訊：

```bash
uv run game-vod-clipper download "https://www.youtube.com/watch?v=..."
uv run game-vod-clipper probe "downloads/video.mp4"
```

先粗略抽樣，再針對候選區間加密。以下時間僅為示例，必須配合實際片長：

```bash
uv run game-vod-clipper sample downloads/video.mp4 --start 00:00:00 --end 03:00:00 --every 60 -o runs/coarse
uv run game-vod-clipper sheet runs/coarse -o runs/coarse.jpg
uv run game-vod-clipper sample downloads/video.mp4 --start 01:20:00 --end 01:35:00 --every 10 -o runs/candidate
uv run game-vod-clipper sheet runs/candidate -o runs/candidate.jpg --columns 6 --rows 5
```

縮圖總覽會自動分頁。請檢查輸出的所有頁面與 JSON manifest，並以抽樣資料夾中的 `samples.json` 對照原片時間。
粗略抽樣只用於定位，最後仍需依 Skill 驗證完整挑戰的連續性與前後邊界。

```bash
uv run game-vod-clipper clip downloads/video.mp4 --start 01:23:42 --end 01:31:18 --postroll 8 -o clips/boss-win.mp4
uv run game-vod-clipper probe clips/boss-win.mp4
uv run game-vod-clipper sample clips/boss-win.mp4 --start 0 --end 20 --every 5 -o runs/final-start-check
```

`clip --end` 是**勝利時刻**，實際片尾再加上 `--postroll`。收尾必須保留 5–10 秒。
片頭抽樣與 `probe` 只是驗證的一部分，還要確認勝利、收尾和整段沒有混入失敗嘗試。

## 指令索引

| 指令 | 用途 |
| --- | --- |
| `check` | 檢查 yt-dlp、FFmpeg 與 JavaScript runtime |
| `download URL` | 下載單部 YouTube VOD，預設放入 `downloads/` |
| `probe VIDEO` | 讀取影片資訊 |
| `sample VIDEO --start TIME --end TIME` | 抽取有時間標記的影格 |
| `sheet FRAME_DIR -o SHEET.jpg` | 建立分頁縮圖總覽 |
| `clip VIDEO --start TIME --end TIME -o OUT.mp4` | 裁切成功片段並加上收尾 |

時間接受秒數、`MM:SS`、`HH:MM:SS` 及小數。`clip --quality` 支援 `max`、`high`、`balanced`、`fast`。
預設重新編碼以準確裁切；`--copy` 適合願意接受關鍵影格邊界限制的情況。
完整選項以指令說明為準：

```bash
uv run game-vod-clipper --help
uv run game-vod-clipper clip --help
```

產生的媒體應放在 `downloads/`、`runs/`、`clips/` 或使用者設定的儲存位置，且不得上傳或散布原始影片。
