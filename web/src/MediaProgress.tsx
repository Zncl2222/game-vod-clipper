import { useEffect, useState } from "react";
import "./media-progress.css";

export type MediaProgressInfo = {
  phase: "download" | "merge" | "preview" | "thumbnails";
  percent: number | null; updated_at: number; stream?: "video" | "audio" | "media";
  downloaded_bytes?: number | null; total_bytes?: number | null; total_is_estimate?: boolean;
  speed_bps?: number | null; eta_seconds?: number | null;
};

function bytes(value: number) {
  const unit = value >= 1e9 ? 3 : value >= 1e6 ? 2 : value >= 1e3 ? 1 : 0;
  return `${(value / 1000 ** unit).toFixed(unit ? 1 : 0)} ${["B", "KB", "MB", "GB"][unit]}`;
}
function remaining(seconds: number) {
  const minutes = Math.ceil(seconds / 60);
  return seconds < 60 ? `${Math.ceil(seconds)} 秒` : minutes < 60 ? `${minutes} 分鐘` : `${Math.floor(minutes / 60)} 小時 ${minutes % 60} 分鐘`;
}

export default function MediaProgress({ status, stage, detail, label = "匯入進度", waitingReason }: {
  status: string; stage?: string; detail?: MediaProgressInfo | null; label?: string; waitingReason?: string;
}) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (status !== "running" || detail?.phase !== "download") return;
    setNow(Date.now() / 1000);
    // Only age the last update; transfer percentages always come from the worker.
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 5000);
    return () => window.clearInterval(timer);
  }, [status, detail?.phase]);
  const queued = status === "queued";
  const percent = !queued && detail?.percent != null && Number.isFinite(detail.percent) ? Math.max(0, Math.min(100, detail.percent)) : undefined;
  const stale = detail?.phase === "download" && percent !== 100 && now - detail.updated_at > 45;
  return <div className="media-progress">
    <div className="media-progress-heading"><span>{queued ? "排隊等待處理" : stage || "正在下載與準備預覽"}</span>
      {percent !== undefined && <strong>{detail?.total_is_estimate ? "約 " : ""}{percent.toFixed(1)}%</strong>}</div>
    <progress max={100} value={percent} aria-label={label} />
    {queued ? <p>{waitingReason || "等待前面的下載或匯出完成，會自動接續。"}</p> : <>
      {detail?.phase === "download" && <div className="media-transfer-stats">
        {detail.downloaded_bytes != null && <span>{bytes(detail.downloaded_bytes)}{detail.total_bytes ? ` / ${detail.total_is_estimate ? "約 " : ""}${bytes(detail.total_bytes)}` : " 已下載"}</span>}
        {!stale && detail.speed_bps != null && detail.speed_bps > 0 && <span>{bytes(detail.speed_bps)}/s</span>}
        {!stale && detail.eta_seconds != null && <span>本階段約剩 {remaining(detail.eta_seconds)}</span>}
      </div>}
      {detail?.phase === "preview" && <p>原片已就緒，正在製作編輯用預覽；成品仍保留原片畫質。</p>}
      {detail?.phase === "merge" && <p>下載完成，正在合併影音；完成後會製作預覽。</p>}
      {stale && <p className="media-progress-wait">暫時沒有新的下載進度，正在等待回應。若持續沒有變化，可取消後重試。</p>}
    </>}
  </div>;
}
