import { useState } from "react";
import { LoaderCircle, Sparkles, Trophy } from "lucide-react";
import { active, analysisError, api, time, type Job } from "./api";

export default function BossReviewDock({ jobs, onSearch, onReset, onError }: {
  jobs: Job[]; onSearch: () => Promise<void>; onReset: () => Promise<void>; onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const job = jobs.find(j => j.kind === "analyze" && active(j)) ?? jobs.find(j => j.kind === "analyze");
  const working = !!job && active(job);
  const result = job?.status === "succeeded" ? job.result : undefined;
  const segmentCount = new Set(jobs.filter(j => j.kind === "analyze").flatMap(j => (j.candidates ?? j.result?.candidates ?? []).map(c => c.id))).size;
  const stage = ({ search: 0, refine: 1, continuity: 1, dense: 2, suspicious: 2, boundaries: 3 } as Record<string, number>)[job?.review_stage ?? ""];
  const complete = result?.status === "candidate";
  const retry = !!job && (["failed", "cancelled", "interrupted"].includes(job.status) || result?.can_continue);
  async function act(command?: "cancel" | "retry" | "reset") {
    setBusy(true);
    try {
      if (command === "reset") await onReset();
      else if (command && job) await api(`/jobs/${job.id}/${command}`, "POST");
      else await onSearch();
    } catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  }
  const heading = segmentCount ? `已標註 ${segmentCount} 個候選片段${working ? "，持續檢查中" : "，可逐段核對"}`
    : working ? (job.status === "queued" ? "已排入細查，等待開始" : "AI 正在逐段檢查影片")
    : complete ? "找到勝利候選，先看看這一場"
    : result?.can_continue ? "這次還沒查完，已保留進度"
    : result?.status === "uncertain" ? "還有疑點，尚未確認成功挑戰"
    : result?.status === "not_found" ? "這次抽樣未找到明確勝利"
    : retry ? (job?.resumable ? "搜尋已停止，已完成的檢查可保留" : "搜尋已停止，可以重新搜尋")
    : "讓 AI 找出成功的那一次";
  return <div className="boss-review-dock assistant-shortcut" aria-label="影片 AI 助手">
    <div className="boss-review-top">
      <div className="boss-review-icon">{working ? <LoaderCircle size={20} className="spin" /> : complete ? <Trophy size={20} /> : <Sparkles size={20} />}</div>
      <div className="boss-review-copy"><strong role="status">{heading}</strong>
</div>
      <button className="secondary" disabled={busy} onClick={() => act(working ? "cancel" : retry ? "retry" : undefined)}>
        {busy ? "處理中…" : working ? "停止搜尋" : retry ? (job?.resumable || result?.can_continue ? "接續細查" : "重新搜尋") : "一鍵搜尋成功挑戰"}
      </button>
      <button className="text-button reset-analysis" disabled={busy} onClick={() => act("reset")} aria-label="重置分析結果" title="停止分析並清除這支影片的候選、檢查點與剪輯草稿；保留原片與成品。">重置</button>
    </div>
    <details className="dock-details"><summary>分析詳情</summary>
    <p>{working ? job.stage : result?.summary}</p>
    <ol className="boss-review-steps" aria-label="成功挑戰檢查流程">
      {["逐段搜尋", "確認整場", "密集複查", "細調起訖"].map((label, i) => <li key={label}
        aria-current={working && stage === i ? "step" : undefined}>
        <span>{i + 1}</span>{label}</li>)}
    </ol>
    {job && <div className="boss-review-meta">
      <span>已判讀 {job.rounds ?? result?.rounds ?? 0} 輪 · {job.frames ?? result?.frames ?? 0} 張畫面</span>
      {working && job.sample_start !== undefined && job.sample_end !== undefined && <span>正在看 {time(job.sample_start)}–{time(job.sample_end)}</span>}
      {working && job.sample_every !== undefined && <span>{job.sample_every < 1 ? `每秒約 ${Math.round(1 / job.sample_every)} 張` : `每 ${job.sample_every.toFixed(1)} 秒一張`}</span>}
      {result && <span>{complete ? "細查結果仍需完整預覽確認" : "尚未套用這次結果"}</span>}
    </div>}
    {!!job?.error && <p className="inline-error">{analysisError(job.error)}</p>}
    {!job && <p className="boss-review-hint">預設搜尋全片；可在 AI 對話設定範圍與模型。細查需要較多時間與模型用量，可停止後接續。</p>}
    </details>
  </div>;
}
