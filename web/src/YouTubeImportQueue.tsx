import { ArrowRight, X } from "lucide-react";
import { useState } from "react";
import { qualityLabel, type DownloadQualityValue } from "./DownloadQuality";
import MediaProgress, { type MediaProgressInfo } from "./MediaProgress";

export type ImportRecord = {
  id: string; video_id: string; title: string; channel: { id: string; title: string };
  status: string; project_id: string | null; error: string | null; auto_analyze: boolean; progress: number;
  download_quality?: DownloadQualityValue; height?: number | null;
  stage?: string; job_status?: string; media_progress?: MediaProgressInfo | null;
  queue_position?: number; waiting_reason?: string; retry_at?: number;
};
export const importIsPending = (item: ImportRecord) => ["queued", "importing", "waiting_account"].includes(item.status);
export const importIsWorking = (item: ImportRecord) => importIsPending(item) || item.status === "preparing";
const labels: Record<string, string> = { queued: "等待匯入", importing: "正在確認影片", preparing: "下載與準備素材",
  ready: "已匯入", failed: "無法加入", needs_attention: "需要重試下載", cancelled: "已取消", removed: "專案已移除", waiting_account: "等待連回原頻道" };

export default function YouTubeImportQueue({ items, busy, channelId, onOpen, onCancel, onRetry }: {
  items: ImportRecord[]; busy: boolean; channelId?: string;
  onOpen: (id: string) => void; onCancel: (id: string) => void; onRetry: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!items.length) return null;
  const waiting = items.filter(importIsWorking).length;
  const failed = items.filter(item => ["failed", "needs_attention"].includes(item.status)).length;
  return <details className="yt-import-queue" open>
    <summary>匯入佇列 <span>{waiting ? `${waiting} 部處理中／等待中` : "目前沒有等待項目"}{failed > 0 && ` · ${failed} 部需處理`}</span></summary>
    <p>一次下載並準備一部，完成後自動接續；AI 分析另外排隊。關閉視窗仍會繼續，請讓 BossCut 保持運作。</p>
    <div className="yt-import-items">
      {(expanded ? items : items.slice(0, 5)).map(item => <article key={item.id} className="yt-import-item" aria-label={`匯入進度：${item.title}`}>
        <div><strong>{item.title}</strong><p><span>{item.status === "preparing" && item.job_status === "queued" ? "等待下載" : labels[item.status] ?? item.status}</span> · {item.auto_analyze ? "自動找片段" : "只匯入影片"}</p>
          <p>{item.height ? `已保留 ${item.height}p` : qualityLabel(item.download_quality)}</p>
          {item.status === "waiting_account" && <p>請連回「{item.channel.title}」即可接續。</p>}
          {item.status === "queued" && <p>{item.queue_position && `排隊第 ${item.queue_position} 部 · `}{item.waiting_reason || "等待前一部完成後自動接續。"}</p>}
          {item.status === "preparing" && <MediaProgress status={item.job_status || "running"} stage={item.stage}
            detail={item.media_progress} waitingReason={item.waiting_reason} label={`${item.title} 匯入進度`} />}
          {item.error && <p className="yt-record-error">{item.error}{item.status === "queued" && " 下一次會自動重試。"}</p>}
        </div>
        <div className="yt-actions">
          {["queued", "waiting_account"].includes(item.status) && <button type="button" className="text-button" disabled={busy}
            onClick={() => onCancel(item.id)} aria-label={`取消等待：${item.title}`}><X size={15} aria-hidden="true" />取消等待</button>}
          {["failed", "cancelled"].includes(item.status) && <button type="button" className="secondary" disabled={busy || item.channel.id !== channelId}
            onClick={() => onRetry(item.id)} aria-label={`重新排隊：${item.title}`}>重新排隊</button>}
          {item.project_id && <button type="button" className="secondary" onClick={() => onOpen(item.project_id!)} aria-label={`開啟工作區：${item.title}`}>
            開啟工作區<ArrowRight size={15} aria-hidden="true" /></button>}
        </div>
      </article>)}
    </div>
    {items.length > 5 && <button type="button" className="text-button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
      {expanded ? "收起清單" : `顯示全部 ${items.length} 部`}</button>}
  </details>;
}
