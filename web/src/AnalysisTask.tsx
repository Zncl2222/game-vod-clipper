import { useState } from "react";
import { Check } from "lucide-react";
import AnalysisProgress from "./AnalysisProgress";
import { active, time, type AnalysisResult, type Job } from "./api";

export default function AnalysisTask({ job, onError, onApply, onSeek }: {
  job: Job;
  onError: (message: string) => void;
  onApply: (result: AnalysisResult) => void;
  onSeek: (seconds: number) => void;
}) {
  const [applied, setApplied] = useState<string | null>(null);
  const result = job.status === "succeeded" ? job.result : undefined;
  return <article className="assistant-task" aria-label="AI 搜尋任務">
    <header><strong>成功挑戰搜尋</strong><span>{job.model ?? result?.model ?? "Codex"}</span></header>
    {!!(job.candidates ?? result?.candidates)?.length && <p>候選片段已標在影片時間軸，可按編號逐段預覽與核對。</p>}
    <details open={active(job) || job.status === "failed"}>
      <summary>搜尋進度與紀錄 · {({ queued: "等待中", running: "執行中", failed: "失敗", succeeded: "完成", cancelled: "已取消", interrupted: "已中斷" } as Record<string, string>)[job.status] ?? job.status}</summary>
      <AnalysisProgress job={job} onError={onError} />
    </details>
      {result && (
        <div className="codex-result">
          <div className="codex-result-heading">
            <strong>
              {result.status === "candidate"
                ? `${result.boss || "Boss 戰"} · 待確認候選`
                : result.status === "not_found"
                  ? "抽樣中未找到明確勝利"
                  : "目前證據不足，需要檢查"}
            </strong>
            <span>
              {result.frames} 張畫面 / {result.rounds} 輪
            </span>
          </div>
          <p>{result.summary}</p>
          {result.evidence.length > 0 && (
            <div className="evidence-list">
              {result.evidence.map((e, i) => (
                <button
                  key={i}
                  className="secondary"
                  onClick={() => onSeek(e.time)}
                >
                  {time(e.time)} · {e.event}
                </button>
              ))}
            </div>
          )}
          {result.warnings.map((warning, i) => (
            <p className="codex-warning" key={i}>
              {warning}
            </p>
          ))}
          {result.status === "candidate" &&
            result.start !== null &&
            result.victory !== null && (
              <button
                className="secondary"
                onClick={() => {
                  onApply(result);
                  setApplied(job.id);
                }}
              >
                <Check size={14} />
                {applied === job.id
                  ? "已套用，可重新套用"
                  : `套用候選 ${time(result.start)} → ${time(result.victory)}`}
              </button>
            )}
        </div>
      )}
  </article>;
}
