import { useEffect, useState } from "react";
import { analysisError, active, api, time, type Job } from "./api";

export default function AnalysisProgress({ job, onError }: {
  job: Job;
  onError: (message: string) => void;
}) {
  const [now, setNow] = useState(Date.now() / 1000);
  const [submitting, setSubmitting] = useState(false);
  const working = active(job);
  useEffect(() => {
    setNow(Date.now() / 1000);
    if (!working) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [job.id, working]);
  const since = job.started_at ?? job.created;
  const elapsed = since === undefined ? null : Math.max(0, (job.finished_at ?? now) - since);
  const heartbeatAge = Math.max(0, now - (job.heartbeat_at ?? job.started_at ?? now));
  const activityAge = Math.max(0, now - (job.last_activity_at ?? job.started_at ?? now));
  const stale = job.status === "running" && heartbeatAge >= 15;
  const quiet = job.status === "running" && activityAge >= 45;
  const step = ({ extracting: 0, analyzing: 1, validating: 2, complete: 3 } as Record<string, number>)[job.phase ?? ""] ?? -1;
  const status = ({
    queued: "等待前面的工作完成",
    succeeded: "分析完成",
    failed: "分析失敗",
    cancelled: "分析已取消",
    interrupted: "分析已中斷，請重試",
  } as Record<string, string>)[job.status] ?? job.stage;

  async function action(command: "cancel" | "retry") {
    setSubmitting(true);
    try {
      await api(`/jobs/${job.id}/${command}`, "POST");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="analysis-progress" aria-label="Codex 分析進度">
      <div className="analysis-status">
        <strong role="status">{status}</strong>
        {elapsed !== null && <span>{job.status === "queued" ? "已等待" : working ? "已執行" : "執行時間"} {time(elapsed)}</span>}
      </div>
      {working && (
        <>
          <div className={`analysis-track ${job.status === "running" && !stale ? "is-running" : ""}`}
            role="progressbar" aria-label="分析進行中" aria-valuetext={status}>
            <div />
          </div>
          <ol className="analysis-steps" aria-label="本輪分析步驟">
            {["擷取畫面", "Codex 判讀", "驗證結果"].map((label, index) => (
              <li key={label} aria-current={step === index ? "step" : undefined}
                className={step === index ? "current" : step > index ? "done" : ""}>
                <span>{index + 1}</span>{label}
              </li>
            ))}
          </ol>
        </>
      )}
      <div className="analysis-metrics">
        {job.sample_every !== undefined && <span>抽樣間隔 {job.sample_every.toFixed(4)} 秒</span>}
        {job.current_round !== undefined && <span>第 {job.current_round} 輪</span>}
        <span>已判讀 {job.rounds ?? 0} 輪</span>
        <span>已擷取 {job.frames ?? 0} 張畫面</span>
        {job.sample_start !== undefined && job.sample_end !== undefined && (
          <span>本輪範圍 {time(job.sample_start)}–{time(job.sample_end)}</span>
        )}
      </div>
      {job.status === "running" && (
        <div className={`analysis-health ${stale || quiet ? "waiting" : ""}`}>
          <p>{stale
            ? `背景工作已 ${Math.floor(heartbeatAge)} 秒未回報，請確認後端服務與連線。`
            : job.heartbeat_at
              ? "背景工作持續回報中"
              : "等待背景工作回報狀態…"}</p>
          <p>{job.last_activity_at
            ? `最近活動：${Math.floor(activityAge)} 秒前${quiet ? "；這個步驟尚未回報新進展，可繼續等待或取消。" : ""}`
            : "等待第一筆活動紀錄。"}</p>
        </div>
      )}
      {job.activity && job.activity.length > 0 && (
        <details className="analysis-activity" open>
          <summary>最近活動</summary>
          <ol>
            {job.activity.slice(-6).map((item, index) => (
              <li key={`${item.time}-${index}`}>
                <time>{new Date(item.time * 1000).toLocaleTimeString("zh-TW", { hour12: false })}</time>
                <span>{item.message}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
      {job.error && <p className="inline-error">{analysisError(job.error)}</p>}
      <div className="analysis-footer">
        {working && <>
          <small>依需要追加抽樣，完成時間會隨判讀輪數變動。</small>
          <button className="text-button" disabled={submitting} onClick={() => action("cancel")}>取消分析</button>
        </>}
        {(["failed", "cancelled", "interrupted"].includes(job.status) || job.result?.can_continue) && (
          <button className="secondary" disabled={submitting} onClick={() => action("retry")}>{job.resumable || job.result?.can_continue ? "接續細查" : "重試分析"}</button>
        )}
      </div>
    </div>
  );
}
