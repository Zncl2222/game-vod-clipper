import { useEffect, useState } from "react";
import "../../styles/media-progress.css";

export type MediaProgressInfo = {
  phase: "download" | "merge" | "preview" | "thumbnails" | "export" | "verify";
  percent: number | null; updated_at: number; stream?: "video" | "audio" | "media";
  downloaded_bytes?: number | null; total_bytes?: number | null; total_is_estimate?: boolean;
  speed_bps?: number | null; eta_seconds?: number | null;
  processed_seconds?: number | null; total_seconds?: number | null; speed_ratio?: number | null;
};

// Phases whose worker reports at least once per second; silence here means the tool may be stuck.
const LIVE_PHASES = new Set(["download", "preview", "export"]);
const STALE_AFTER = { download: 45, preview: 30, export: 30 } as Record<string, number>;

function bytes(value: number) {
  const unit = value >= 1e9 ? 3 : value >= 1e6 ? 2 : value >= 1e3 ? 1 : 0;
  return `${(value / 1000 ** unit).toFixed(unit ? 1 : 0)} ${["B", "KB", "MB", "GB"][unit]}`;
}
export function remaining(seconds: number) {
  const minutes = Math.ceil(seconds / 60);
  return seconds < 60 ? `${Math.max(1, Math.ceil(seconds))} 秒` : minutes < 60 ? `${minutes} 分鐘` : `${Math.floor(minutes / 60)} 小時 ${minutes % 60} 分鐘`;
}

function clock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function MediaProgress({ status, stage, detail, label = "匯入進度", waitingReason, startedAt }: {
  status: string; stage?: string; detail?: MediaProgressInfo | null; label?: string; waitingReason?: string; startedAt?: number;
}) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (status !== "running" || !(LIVE_PHASES.has(detail?.phase ?? "") || startedAt)) return;
    setNow(Date.now() / 1000);
    // Only age the last update and the elapsed clock; percentages always come from the worker.
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [status, detail?.phase, startedAt]);
  const queued = status === "queued";
  const percent = !queued && detail?.percent != null && Number.isFinite(detail.percent) ? Math.max(0, Math.min(100, detail.percent)) : undefined;
  const stale = !!detail && LIVE_PHASES.has(detail.phase) && percent !== 100 && now - detail.updated_at > STALE_AFTER[detail.phase];
  const encoding = detail?.phase === "export" || detail?.phase === "preview";
  return <div className="media-progress">
    <div className="media-progress-heading"><span>{queued ? "排隊等待處理" : stage || "正在下載與準備原片"}</span>
      {percent !== undefined && <strong>{detail?.total_is_estimate ? "約 " : ""}{percent.toFixed(1)}%</strong>}</div>
    <progress max={100} value={percent} aria-label={label} />
    {queued ? <p>{waitingReason || "等待前面的下載或匯出完成，會自動接續。"}</p> : <>
      {detail?.phase === "download" && <div className="media-transfer-stats">
        {detail.downloaded_bytes != null && <span>{bytes(detail.downloaded_bytes)}{detail.total_bytes ? ` / ${detail.total_is_estimate ? "約 " : ""}${bytes(detail.total_bytes)}` : " 已下載"}</span>}
        {!stale && detail.speed_bps != null && detail.speed_bps > 0 && <span>{bytes(detail.speed_bps)}/s</span>}
        {!stale && detail.eta_seconds != null && <span>本階段約剩 {remaining(detail.eta_seconds)}</span>}
      </div>}
      {encoding && detail && <div className="media-transfer-stats">
        {detail.processed_seconds != null && detail.total_seconds != null && <span>已處理 {clock(detail.processed_seconds)} / {clock(detail.total_seconds)}</span>}
        {!stale && detail.speed_ratio != null && detail.speed_ratio > 0 && <span>速度 {detail.speed_ratio.toFixed(1)}×</span>}
        {!stale && detail.eta_seconds != null && <span>約剩 {remaining(detail.eta_seconds)}</span>}
        {startedAt && <span>已執行 {clock(now - startedAt)}</span>}
      </div>}
      {detail?.phase === "preview" && <p>原片已就緒，正在製作編輯用預覽；成品仍保留原片畫質。</p>}
      {detail?.phase === "merge" && <p>下載完成，正在無損合併影音；完成後即可直接播放原片。</p>}
      {detail?.phase === "thumbnails" && <p>原片已可播放與編輯，時間軸縮圖會陸續出現。</p>}
      {detail?.phase === "verify" && <p>編碼完成，正在檢查成品長度與影像軌。</p>}
      {!detail && startedAt && <p>正在啟動 FFmpeg… 已執行 {clock(now - startedAt)}</p>}
      {stale && <p className="media-progress-wait">{detail.phase === "download"
        ? "暫時沒有新的下載進度，正在等待回應。若持續沒有變化，可取消後重試。"
        : `已有 ${Math.round(now - detail.updated_at)} 秒沒有新的編碼進度，處理可能卡住。可再等一下，或取消後重試。`}</p>}
    </>}
  </div>;
}
