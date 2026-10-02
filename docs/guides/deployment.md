# Docker 部署

[回到繁體中文 README](../../README.zh-TW.md)

## 啟動與日常管理

在儲存庫根目錄執行：

```bash
docker compose up -d --build --wait
```

開啟 http://127.0.0.1:8000。單一服務提供 React 前端、FastAPI 後端與 SQLite 狀態儲存，並啟動媒體處理與 AI 子程序。每個工作區只執行一個後端。

容器使用非 root 帳號，設定為 `unless-stopped` 自動重啟，停止時保留 60 秒讓程序結束。Docker 本身仍需持續運作。

```bash
docker compose ps
docker compose logs -f --tail=100 bosscut
docker compose stop
docker compose up -d --wait
```

更新程式後，執行 `docker compose up -d --build --wait` 重建服務。停止或更新前，先等待匯出完成；被中斷的工作可在重啟後依介面提供的操作重試或接續。

健康檢查讀取 `/api/health` 並檢查本機資料庫，不會呼叫 AI。`unhealthy` 是診斷狀態；重啟政策針對程序退出，不會僅因健康檢查失敗而重啟。

## 資料保存與備份

預設使用四個 Docker volumes：

| Volume | 容器路徑 | 內容 |
| --- | --- | --- |
| `downloads` | `/data/downloads` | 原始影片與下載資料 |
| `clips` | `/data/clips` | 成品與匯出紀錄 |
| `runs` | `/data/runs` | 資料庫、分析、縮圖、YouTube 登入與設定 |
| `codex` | `/home/bosscut/.codex` | Codex 登入與設定 |

重啟或重建容器會保留資料。`docker compose down` 保留 volumes，**`docker compose down -v` 會刪除它們**。
Compose 會在 volume 名稱前加上專案名稱；更新時維持相同名稱，避免誤用新的空白工作區。

備份前停止服務，保存四個 volumes，尤其是 `runs` 與 `codex`。備份包含登入資料，應保持私密。
容器日誌輪替上限為 10 MB × 3 份；`runs` 中的應用程式資料由工作區的儲存管理功能處理。

## 掛載本機資料夾

需要匯入本機錄影或使用外接硬碟時：

```bash
cp .env.example .env
```

依照 [.env.example](../../.env.example) 設定下列值；留空則保留對應的 Docker volume。

| 變數 | 用途 |
| --- | --- |
| `BOSSCUT_DOWNLOADS_DIR` | 原始影片資料夾 |
| `BOSSCUT_CLIPS_DIR` | 匯出成品資料夾 |
| `BOSSCUT_RUNS_DIR` | 狀態與暫存資料夾 |
| `BOSSCUT_CODEX_DIR` | Codex 登入與設定資料夾 |
| `BOSSCUT_UID`、`BOSSCUT_GID` | 容器使用者 ID，預設均為 1000 |

資料夾使用絕對路徑或以 `./` 開頭的相對路徑，啟動前先建立並確保容器使用者有寫入權限。Linux 可用 `id -u`、`id -g` 查詢 ID；修改 ID 後需重建，既有檔案的擁有者不會自動改變。

建議將資料放在儲存庫以外。若使用儲存庫內的自訂資料夾，請自行加入 Git 忽略規則，尤其是含登入資訊的資料夾。

將影片放入 `BOSSCUT_DOWNLOADS_DIR` 指定的主機資料夾，再從「匯入 → 本機影片」選擇。
介面看到的路徑是 `/data/downloads`；在網頁更換儲存位置時，也必須選擇**容器內已掛載的路徑**。
其他主機目錄可透過本機 `compose.override.yaml` 掛載。

## 沿用既有工作區

預設部署會建立新工作區，不會自動複製原先的資料庫、影片或帳號。
先停止舊後端並備份，再明確掛載既有資料夾。資料庫內既有的絕對影片路徑，必須在容器內以相同路徑存在；更改儲存偏好不會重寫舊路徑。不要讓兩個後端同時使用相同的 `runs`。

## AI 與 YouTube 登入

在「帳號設定」選擇「使用 ChatGPT 登入」，依畫面完成裝置碼登入。也可在容器內執行：

```bash
docker compose exec bosscut codex login --device-auth
```

容器有獨立保存的登入狀態，不會自動使用主機帳號。容器未公開瀏覽器登入回呼連接埠，因此使用裝置碼流程。
YouTube 透過「我的 YouTube」設定，詳見 [YouTube 工作流程](youtube.md)。

## 連接埠與存取範圍

預設只接受本機連線。若 8000 已被占用，在 `.env` 設定 `BOSSCUT_PORT`。
可信任區網可設定 `BOSSCUT_BIND_ADDRESS` 為主機的區網介面位址，並在 `BOSSCUT_ALLOWED_HOSTS` 填入瀏覽器使用的 IP 或主機名稱，以逗號分隔、不含協定與連接埠。

本工具沒有訪客登入或多使用者權限隔離，能連線的人可操作工作區。若需公開存取，應由自己管理的驗證閘道限制存取。
`.env` 與 `compose.override.yaml` 不納入 Git；Docker 建置只包含 [.dockerignore](../../.dockerignore) 列出的輸入。
