# Game VOD Clipper · BossCut Studio

[English](README.md) | **繁體中文**

從遊戲直播 VOD 中找出完整的 Boss 成功挑戰，核對起點與勝利時刻，再匯出乾淨的 MP4 片段。

專案提供三種使用方式：

- **網頁工作區**：匯入影片、AI 搜尋候選、調整時間軸、管理成品與 YouTube 上傳。
- **Python CLI**：透過 yt-dlp 與 FFmpeg 下載、抽幀、製作縮圖總覽與裁切影片。
- **Agent Skill**：讓程式代理依照固定流程檢查畫面、排除失敗嘗試並驗證成品。

這是本機、單人使用的工具。AI 候選仍需檢查；手動剪輯不需要登入 AI 帳號。

## 快速開始

### Docker Compose

安裝 Docker 與 Compose 後，在終端執行：

```bash
git clone https://github.com/Zncl2222/game-vod-clipper.git
cd game-vod-clipper
docker compose up -d --build --wait
```

開啟 **http://127.0.0.1:8000**。映像包含前端、後端、FFmpeg、yt-dlp、Node.js 與 Codex CLI。
服務在背景執行，資料保存在 Docker volumes；停止服務可使用 `docker compose stop`。

本機影片匯入、資料掛載、備份與更新方式，請見 [Docker 部署](docs/guides/deployment.md)。

### 本機執行

需要 Python 3.11+、uv、Node.js 22.12+、npm，以及可信來源的 FFmpeg／ffprobe。
在儲存庫根目錄執行：

```bash
uv sync --frozen --extra web
npm --prefix web ci
npm --prefix web run build
uv run --extra web game-vod-clipper check
uv run --extra web game-vod-web
```

開啟 **http://127.0.0.1:8000**，處理影片時保持後端運作。
AI 功能另需在後端環境安裝並連接 Codex CLI；Docker 映像已包含它。
只需要命令列工具時，請見 [CLI 與 Agent](docs/guides/cli.md)。

## 基本流程

1. 將本機影片放入 `downloads/` 後匯入，或貼上已結束的 YouTube 直播網址。
2. 手動定位成功挑戰，或在「帳號設定」連接 AI 後執行「一鍵搜尋成功挑戰」。
3. 預覽候選並調整開始、勝利時間與收尾，確認是同一次完整成功挑戰。
4. 匯出 MP4；成品可下載、另存修改版本，或經確認後上傳至自己的 YouTube 頻道。

剪輯必須排除較早的失敗嘗試、死亡、讀取、重生與跑圖，並包含勝利時刻及其後 **5–10 秒**。
不應只靠稀疏縮圖判定完成。不得上傳或散布使用者的原始 VOD。

## 文件

專案以英文 README 為預設入口，另提供本繁體中文版。以下詳細指南目前以繁體中文提供；指令、API 名稱與 Agent Skill 保留原有格式。

| 想做的事 | 文件 |
| --- | --- |
| 匯入、AI 搜尋、調整候選、匯出與管理資料 | [操作指南](docs/guides/usage.md) |
| 常駐服務、掛載本機影片、備份與更新 | [Docker 部署](docs/guides/deployment.md) |
| 連接頻道、批次匯入與上傳成品 | [YouTube 工作流程](docs/guides/youtube.md) |
| 使用命令列或交給 Agent 剪輯 | [CLI 與 Agent](docs/guides/cli.md) |
| 開發環境、程式結構、UI 維護與測試 | [開發指南](docs/guides/development.md) |

## 目錄

```text
src/game_vod_clipper/           Python CLI、API 與背景任務
web/                            React 前端與瀏覽器測試
tests/                          Python 測試
skills/game-vod-boss-clipper/    Agent 剪輯流程
docs/guides/                    維護中的使用與開發文件
scripts/                        驗證、效能測量與資料遷移工具
downloads/                      原始影片（不納入 Git）
runs/                           狀態、分析與暫存（不納入 Git）
clips/                          匯出成品（不納入 Git）
```

網頁可自訂影片儲存位置。更換位置只影響新檔案；既有專案不會自動搬移。

## 開發檢查

```bash
make setup
make check
make test-web
```

CI 執行 Ruff、Biome、TypeScript、Python／瀏覽器測試與正式建置。
Bandit 與 pip-audit 在 PR 及每週檢查，Dependabot 提出依賴更新。
環境需求與檢查範圍請見 [開發指南](docs/guides/development.md)。

## 授權

本專案採用 [MIT License](LICENSE)。
