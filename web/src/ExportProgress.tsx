import { ArrowDownToLine, Check, CircleAlert, LoaderCircle, RotateCcw, X } from "lucide-react";
import { active, type Job } from "./api";
import MediaProgress, { remaining } from "./MediaProgress";
import "./export-progress.css";

// Inline status for the most recent export, so the export bar never looks idle while FFmpeg works.
export default function ExportProgress({ job, clipNumber, estimate, onAction, onDismiss }: {
  job: Job; clipNumber?: number; estimate?: number | null;
  onAction: (job: Job, command: "cancel" | "retry") => Promise<void>; onDismiss: () => void;
}) {
  const running = active(job);
  const failed = ["failed", "interrupted"].includes(job.status);
  const tone = running ? "running" : job.status === "succeeded" ? "done" : failed ? "failed" : "cancelled";
  const title = running ? (job.status === "queued" ? "匯出排隊中" : "正在匯出 MP4")
    : job.status === "succeeded" ? `匯出完成${clipNumber ? ` · 成品 #${clipNumber}` : ""}`
    : failed ? "匯出失敗" : "已取消匯出";
  return <section className={`export-progress is-${tone}`} aria-label="匯出狀態">
    <div className="export-progress-icon" aria-hidden="true">
      {running ? <LoaderCircle size={18} className="spin" /> : tone === "done" ? <Check size={18} /> : <CircleAlert size={18} />}
    </div>
    <div className="export-progress-body">
      <strong aria-live="polite">{title}</strong>
      {running ? <MediaProgress status={job.status} stage={job.stage} detail={job.media_progress} label="匯出進度"
        startedAt={job.status === "running" ? job.started_at : undefined}
        waitingReason="等待前面的下載、預覽或匯出完成，會自動開始。可以繼續編輯下一段。" />
        : null}
      {running && estimate != null && job.media_progress?.eta_seconds == null && job.media_progress?.phase !== "verify" &&
        <p className="export-progress-estimate">{job.status === "queued" ? "開始後" : "編碼速度量測前，"}預估約需 {remaining(estimate)}（依此裝置過去的匯出速度）</p>}
      {running ? null
        : <p>{tone === "done" ? "已加入本專案的成品清單。"
          : job.error || (job.status === "interrupted" ? "服務曾中斷，請重試。" : "這次匯出沒有產生成品。")}</p>}
    </div>
    <div className="export-progress-actions">
      {running && <button type="button" className="text-button" onClick={() => void onAction(job, "cancel")}>取消匯出</button>}
      {tone === "done" && <a className="secondary" href={`/api/jobs/${job.id}/download`}><ArrowDownToLine size={14} aria-hidden="true" />下載 MP4</a>}
      {(failed || tone === "cancelled") && <button type="button" className="secondary" onClick={() => void onAction(job, "retry")}>
        <RotateCcw size={14} aria-hidden="true" />重試</button>}
      {!running && <button type="button" className="icon-button" aria-label="關閉匯出狀態" onClick={onDismiss}><X size={16} aria-hidden="true" /></button>}
    </div>
  </section>;
}
