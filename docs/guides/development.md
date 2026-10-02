# 開發指南

[回到繁體中文 README](../../README.zh-TW.md)

## 環境

使用 Python 3.11+、uv、Node.js 22.12+、npm 與可信來源的 FFmpeg／ffprobe。
以下命令均從儲存庫根目錄執行：

```bash
uv sync --frozen --extra web --extra test
npm --prefix web ci
uv run --extra web game-vod-clipper check
```

前後端開發分別開啟終端：

```bash
uv run --extra web game-vod-web
```

```bash
npm --prefix web run dev
```

Vite 開發伺服器會將 `/api` 代理到 `127.0.0.1:8000`。一般使用則先執行 `npm --prefix web run build`，由後端直接提供建置後的頁面。

[Dev Container](../../.devcontainer/devcontainer.json) 使用 Dockerfile 的 `development` target；Compose 使用 `runtime` target。
前者提供互動開發環境，後者直接啟動服務。

## 程式結構

| 位置 | 責任 |
| --- | --- |
| `src/game_vod_clipper/cli.py`、`media.py` | 命令列與媒體處理 |
| `web.py`、`web_store.py`、`web_worker.py` | HTTP API、專案保存與背景任務 |
| `codex_*.py`、`review_*.py` | AI 連線、聊天、影像分析與進度 |
| `candidate_registry.py`、`candidates.py` | 候選識別與區間資料 |
| `youtube_*.py` | 帳號、直播匯入、歷史與成品上傳 |
| `locations.py`、`storage.py` | 儲存位置與資料管理 |
| `web/src/` | React 編輯器與樣式 |
| `tests/`、`web/tests/` | Python 與瀏覽器測試 |
| `scripts/` | 效能測量、播放驗證與一次性遷移工具 |

API 行為以 [web.py](../../src/game_vod_clipper/web.py)、[前端 API 型別](../../web/src/lib/api.ts) 與測試為準。
Agent 的媒體檢查流程以 [Skill](../../skills/game-vod-boss-clipper/SKILL.md) 為準，避免在多份文件複製同一套規則。

## 前端目錄規則

```text
web/src/
├── main.tsx                 React 啟動與全域樣式載入
├── App.tsx                  工作區組合與應用程式狀態
├── components/
│   ├── ai/                  AI 連線、聊天與分析
│   ├── editor/              剪輯區間與時間軸
│   ├── layout/              可調整版面與操作指南
│   ├── library/             匯入、專案與成品清單
│   ├── media/               畫質控制與媒體進度
│   ├── settings/            偏好設定與遊戲設定
│   ├── storage/             儲存位置與用量管理
│   └── youtube/             頻道、匯入佇列與播放清單
├── lib/                     API、播放、草稿與共用狀態邏輯
└── styles/                  全域及各功能的 CSS
```

新元件依用途放入對應的 `components/` 子目錄，CSS 放入 `styles/`，共用非 JSX 模組放入 `lib/`。
使用直接檔案引用，避免為了轉出所有元件而新增 `index.ts`。現有元件匯出的型別與輔助函式仍由原模組提供。

全域樣式由 `main.tsx` 載入，功能樣式由使用它的元件引用。保留載入次序，因為現有 CSS 使用全域選擇器與層疊覆寫。
動態座標、進度和可調整寬度仍可由元件傳入 inline style；固定視覺規則放在 CSS。
本次目錄整理沒有拆分大型元件或改寫狀態流程，後續應依功能需求個別重構並驗證。

## UI 維護原則

樣式以實際 CSS 為準，不另維護一套容易過時的色碼表：

- [studio.css](../../web/src/styles/studio.css)：共用視覺設定與工作區樣式。
- [workbench.css](../../web/src/styles/workbench.css)：時間軸與下方工作區。
- [clip-library.css](../../web/src/styles/clip-library.css)：成品清單與相關版面。
- [youtube.css](../../web/src/styles/youtube.css)：頻道與匯入介面。

調整版面時保留播放器、草稿與未送出的對話，不因縮放側欄、切換成品或開關對話框而重置。
原片與成品草稿分開保存，選取候選、編輯欄位、預覽及匯出應指向同一區間。

控制項需有可辨識名稱與鍵盤焦點。狀態不能只靠顏色區分；對話框支援 Escape、焦點限制與關閉後焦點還原。
支援窄視窗與 reduced-motion；不要只為展示介面就啟動下載、登入、分析或匯出。

## 驗證

Python 測試與語法檢查：

```bash
uv run --extra web --extra test python -m unittest discover -s tests
uv run python -m compileall -q src tests
```

前端型別檢查與建置：

```bash
npm --prefix web run build
```

首次跑瀏覽器測試，先安裝測試瀏覽器：

```bash
cd web
npx playwright install chromium
```

以下回到儲存庫根目錄執行；依修改範圍選擇測試：

```bash
npm --prefix web run test:chat
npm --prefix web run test:youtube
npm --prefix web run test:e2e
npm --prefix web run test:e2e -- --config playwright.storage.config.ts
```

`test:chat` 使用模擬 API，涵蓋聊天、工作區與成品等介面，不呼叫真實 AI。
預設 `test:e2e` 與儲存測試會啟動測試後端並處理合成媒體，需要 FFmpeg。
截圖、測試結果與媒體產物放入 `runs/`，不要提交影片、登入資料或本機資料庫。

## 文件與儲存庫整理規則

`README.md` 是英文預設入口，`README.zh-TW.md` 提供繁體中文版，兩者頂端互相連結。
README 只放介紹、快速開始與導覽；修改共用內容或指令時，應同步更新兩個版本。
詳細操作放在 `docs/guides/`，目前使用繁體中文，英文 README 應明確標示指南語言。指令、API 名稱與 Agent 規範保留原有格式，避免同一頁逐段混排翻譯。

歷史規劃、個人測試報告及原型不作為使用者文件入口。此 checkout 原有的本機 `docs/` 筆記仍可保留，但正式維護的指南集中於 `docs/guides/`，由 Git 追蹤。
刪除文件前，先確認引用並搬移仍有用的維護資訊；刪除程式或腳本則需另外確認實際用途。

`.gitignore` 排除媒體、建置產物與本機設定；`.dockerignore` 控制映像建置輸入。兩者用途不同，新增文件或目錄時應分別確認。
