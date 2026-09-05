import { useEffect, useState } from "react";
import { Check, LoaderCircle, Sparkles } from "lucide-react";
import {
  active,
  api,
  time,
  type AnalysisResult,
  type Job,
  type Project,
} from "./api";

export default function CodexPanel({
  project,
  jobs,
  onError,
  onApply,
  onSeek,
}: {
  project: Project;
  jobs: Job[];
  onError: (message: string) => void;
  onApply: (result: AnalysisResult) => void;
  onSeek: (seconds: number) => void;
}) {
  const [connection, setConnection] = useState<{
    available: boolean;
    detail: string;
  } | null>(null);
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(Math.min(project.duration!, 1800));
  const [submitting, setSubmitting] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const analysis = jobs.find((j) => j.kind === "analyze");
  const running = jobs.some((j) => j.kind === "analyze" && active(j));
  const result = analysis?.status === "succeeded" ? analysis.result : undefined;
  const valid =
    Number.isFinite(start) &&
    Number.isFinite(end) &&
    start >= 0 &&
    start < end &&
    end <= project.duration! &&
    end - start <= 1800;
  useEffect(() => {
    api<{ available: boolean; detail: string }>("/codex")
      .then(setConnection)
      .catch((e) => onError(e.message));
  }, [project.id]);
  async function analyze() {
    setSubmitting(true);
    onError("");
    setApplied(null);
    try {
      await api(`/projects/${project.id}/analyze`, "POST", { start, end });
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <section className="codex-panel">
      <div className="codex-heading">
        <div className="agent-icon">
          <Sparkles size={20} />
        </div>
        <div>
          <h2>用 Codex 找到成功的那一次</h2>
          <p>gpt-5.6-luna · 使用這台裝置的 Codex CLI 登入</p>
        </div>
        <span className="badge">
          {connection?.available ? "CLI 已就緒" : "CLI 尚未就緒"}
        </span>
      </div>
      <div className="codex-controls">
        <label>
          分析起點（秒）
          <input
            aria-label="Codex 分析起點"
            type="number"
            min="0"
            max={project.duration}
            value={start}
            onChange={(e) => setStart(Number(e.target.value))}
          />
        </label>
        <label>
          分析終點（秒）
          <input
            aria-label="Codex 分析終點"
            type="number"
            min="0"
            max={project.duration}
            value={end}
            onChange={(e) => setEnd(Number(e.target.value))}
          />
        </label>
        <button
          className="primary"
          disabled={!valid || running || submitting || !connection?.available}
          onClick={analyze}
        >
          {running || submitting ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <Sparkles size={16} />
          )}
          {running ? "Codex 判讀中…" : "開始 Codex 分析"}
        </button>
      </div>
      <p className="codex-disclosure">
        原片不會上傳；抽樣畫面與判讀指令會傳送至 OpenAI，使用你的 Codex
        額度。每次最多分析 30 分鐘、12 輪判讀，可在處理紀錄取消。
      </p>
      {!valid && (
        <p className="inline-error">
          請選擇原片內的時間範圍，每次最長 30 分鐘。
        </p>
      )}
      {connection && !connection.available && (
        <p className="inline-error">{connection.detail}</p>
      )}
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
                  setApplied(analysis!.id);
                }}
              >
                <Check size={14} />
                {applied === analysis?.id
                  ? "已套用，可重新套用"
                  : `套用候選 ${time(result.start)} → ${time(result.victory)}`}
              </button>
            )}
        </div>
      )}
    </section>
  );
}
