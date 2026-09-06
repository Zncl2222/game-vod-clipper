import { useEffect, useState } from "react";
import { ArrowUpRight, CircleAlert, LoaderCircle, Check } from "lucide-react";
import { analysisError, active, time, type Job } from "./api";

export default function AIActivity({ job, onInspect }: { job: Job; onInspect: () => void }) {
  const working = active(job);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    setNow(Date.now() / 1000);
    if (!working) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [job.id, working]);
  const heartbeat = job.heartbeat_at ?? job.started_at ?? job.created;
  const stale = job.status === "running" && (heartbeat === undefined || now - heartbeat >= 15);
  const problem = stale || ["failed", "cancelled", "interrupted"].includes(job.status);
  const phase = ({ extracting: 0, analyzing: 1, validating: 2 } as Record<string, number>)[job.phase ?? ""] ?? -1;
  const label = job.status === "queued" ? "等待分析"
    : stale ? "等待背景工作回報"
    : job.status === "succeeded" ? (job.result?.status === "candidate" ? "找到候選，等待你檢查" : "分析已完成，查看結果")
    : ({ failed: "分析失敗", cancelled: "分析已取消", interrupted: "分析已中斷" } as Record<string, string>)[job.status]
      ?? ({ extracting: "正在擷取畫面", analyzing: "AI 正在判讀", validating: "正在驗證時間點" } as Record<string, string>)[job.phase ?? ""]
      ?? "正在準備分析";
  return <section className={`ai-activity ${problem ? "is-warning" : ""}`} aria-label="AI 即時工作狀態">
    <div className="ai-activity-heading" role="status">
      {problem ? <CircleAlert size={14} /> : working ? <LoaderCircle size={14} className={!stale ? "spin" : ""} /> : <Check size={14} />}
      <strong>{label}</strong>
      <button onClick={onInspect} aria-label="查看分析詳情" title="查看分析詳情"><ArrowUpRight size={15} /></button>
    </div>
    {working && <ol className="ai-activity-steps" aria-label="即時分析階段">
      {["擷取", "判讀", "驗證"].map((label, index) => <li key={label}
        aria-current={!stale && phase === index ? "step" : undefined}
        className={!stale && phase === index ? "current" : ""}>{label}</li>)}
    </ol>}
    <p>{job.current_round ? `第 ${job.current_round} 輪 · ` : ""}已擷取 {job.frames ?? 0} 張</p>
    {working && job.sample_start !== undefined && job.sample_end !== undefined &&
      <p>本輪範圍 {time(job.sample_start)}–{time(job.sample_end)}</p>}
    {problem && <p>{stale ? "暫未收到新狀態，可查看詳情或取消工作。" : (job.error ? analysisError(job.error) : "本次工作已停止。")}</p>}
  </section>;
}
