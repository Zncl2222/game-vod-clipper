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
前者提供互動開發環境與 Ruff／Biome 的 VS Code 擴充套件，後者直接啟動服務。

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

## 檢查工具與 CI

Python 使用 [Ruff](https://docs.astral.sh/ruff/)、[Bandit](https://bandit.readthedocs.io/) 與 [pip-audit](https://github.com/pypa/pip-audit)；前端使用 [Biome](https://biomejs.dev/) 與 TypeScript。
前端套件管理仍為 npm，使用 `package-lock.json`；Biome 不需要 Bun。
工具版本由 `uv.lock` 與 `web/package-lock.json` 鎖定，CI 使用 frozen／clean install。

在根目錄安裝開發與測試依賴：

```bash
make setup
```

需要 GNU Make、Python 3.11+、uv、Node.js 22.12+、npm 與 FFmpeg／ffprobe。
沒有 Make 時可直接執行下表的等價指令。

| 檢查 | 指令 |
| --- | --- |
| Python lint | `uv run --frozen ruff check src tests scripts web/tests` |
| 前端 lint（TS／TSX／CSS／JSON） | `npm --prefix web run lint` |
| TypeScript 型別 | `npm --prefix web run typecheck` |
| Python 安全靜態分析 | `uv run --frozen bandit -c pyproject.toml -r src scripts -ll` |
| 鎖定套件的漏洞稽核 | `make security`（包含 Bandit） |
| Python 單元與媒體整合測試 | `make test` |
| 前端正式建置 | `make build` |
| 上述檢查，不含瀏覽器測試 | `make check` |

`make lint` 一次執行 Ruff、Biome 與 TypeScript。`npm --prefix web run lint:fix` 只套用 Biome 的安全修正，請檢查差異後再提交。

目前 lint 著重錯誤檢查，沒有要求全面重新排版：

- Ruff 啟用 `E4`、`E7`、`E9`、`F`；保留既有單行敘述風格，排除 `E701`、`E702`。
- Biome 啟用 correctness、suspicious、security 的建議規則及部分 ARIA／替代文字檢查。格式化與 import 重排暫不啟用。
- React effect 依賴、陣列 index key 與 explicit `any` 暫不列為 Biome 阻擋項目；這些既有模式需逐項審查，不能透過自動修正一次改寫。樣式排序與全面無障礙規則也不是本輪門檻；瀏覽器測試仍包含 axe 檢查。
- Bandit 掃描 `src/` 與 `scripts/`，中／高嚴重度會阻擋 CI。低嚴重度（例如匯入 subprocess）可用不帶 `-ll` 的指令另行檢視。已人工確認的 SQL 誤判以逐行 `nosec B608` 說明，沒有全域忽略 SQL 注入規則。
- pip-audit 從 `uv.lock` 匯出含 hashes 的完整依賴清單，包含 web、test 與 dev；不安裝未鎖定版本，任何已知漏洞或稽核失敗都會使檢查失敗。稽核需要網路，會查詢套件名稱與版本。

若不使用 Make，可手動稽核：

```bash
mkdir -p runs/security
uv export --frozen --all-extras --no-emit-project --format requirements-txt -o runs/security/requirements.txt
uv run --frozen pip-audit --strict --disable-pip --require-hashes -r runs/security/requirements.txt
```

[CI workflow](../../.github/workflows/ci.yml) 在 PR、推送到 `main` 與手動觸發時執行 lint、型別、建置、Python 3.11／3.12 測試，以及四組 Chromium 瀏覽器測試。
[安全檢查](../../.github/workflows/security.yml) 另外每週執行，讓未改程式碼時新公布的漏洞也能被發現。
Actions 以完整 commit SHA 固定，僅有讀取權限；不需要 AI 或 YouTube 帳號密鑰。
[Dependabot](../../.github/dependabot.yml) 每週檢查 uv、npm 與 Actions 更新，不自動合併。

Workflow 提交到 GitHub 後才會在遠端執行；如要禁止合併失敗的 PR，維護者還需在 GitHub ruleset／branch protection 將這些 checks 設為必須通過。

## 瀏覽器測試

首次跑瀏覽器測試，先在 `web/` 安裝 Chromium；Linux CI 同時安裝系統函式庫：

```bash
cd web
npx --no-install playwright install --with-deps chromium
```

回到根目錄，依修改範圍選擇測試：

```bash
npm --prefix web run test:chat
npm --prefix web run test:youtube
npm --prefix web run test:e2e
npm --prefix web run test:storage
```

`make test-web` 會先建置，再依序執行四組測試。YouTube 與儲存測試共用連接埠 8012，本機執行時不要同時跑。
`test:chat`、`test:youtube` 使用模擬 API，不呼叫真實模型或 Google。
`test:e2e` 與 `test:storage` 使用獨立暫存工作區與合成媒體，需要 FFmpeg；不使用個人的影片或登入資料。

截圖與測試產物放入 `runs/`。GitHub CI 失敗時上傳 Playwright 報告與測試附件，保留七天；不提交或上傳原始 VOD、登入資料與個人資料庫。

## 文件與儲存庫整理規則

`README.md` 是英文預設入口，`README.zh-TW.md` 提供繁體中文版，兩者頂端互相連結。
README 只放介紹、快速開始與導覽；修改共用內容或指令時，應同步更新兩個版本。
詳細操作放在 `docs/guides/`，目前使用繁體中文，英文 README 應明確標示指南語言。指令、API 名稱與 Agent 規範保留原有格式，避免同一頁逐段混排翻譯。

歷史規劃、個人測試報告及原型不作為使用者文件入口。此 checkout 原有的本機 `docs/` 筆記仍可保留，但正式維護的指南集中於 `docs/guides/`，由 Git 追蹤。
刪除文件前，先確認引用並搬移仍有用的維護資訊；刪除程式或腳本則需另外確認實際用途。

`.gitignore` 排除媒體、建置產物與本機設定；`.dockerignore` 控制映像建置輸入。兩者用途不同，新增文件或目錄時應分別確認。
