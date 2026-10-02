import { Activity, RotateCcw } from "lucide-react";
import { active, currentAnalysis, time, type Job, type Project } from "../../lib/api";
import { timelinePosition, timelineRange } from "./SelectionOverlay";
import { type TimeWindow } from "./TimelineZoom";

/** Optional evidence track, aligned to the workbench's only ruler and zoom. */
export default function AIWorkspaceTimeline({ project, jobs, current, onSeek, onResetProgress, resetting, view }: {
  project: Project; jobs: Job[]; current: number; onSeek: (seconds: number) => void;
  onResetProgress: () => Promise<void>; resetting: boolean; view: TimeWindow;
}) {
  const local = jobs.filter(j => j.project_id === project.id);
  const searches = local.filter(currentAnalysis);
  const working = searches.find(active);
  const signals = searches.flatMap(j => (j.evidence ?? j.result?.evidence ?? []).map((e, i) => ({ ...e, id: `${j.id}:${i}` })));
  const coverage = searches.flatMap(j => j.coverage ?? j.result?.coverage ?? []);
  const visible = (start: number, end = start) => end >= view.from && start <= view.to;
  return <section className="ai-workspace-timeline" aria-label="AI 探索與證據">
    <div className="workbench-lane-label"><Activity size={14} aria-hidden="true" /><strong>AI 探索</strong></div>
    <div className="ai-overview-track" role="group" aria-label="AI 全片抽樣進度">
      {coverage.filter(c => visible(c.start, c.end)).map((c, i) => <span key={i} className={`ai-coverage ${c.every <= .5 ? "dense" : ""}`}
        style={timelineRange(c.start, c.end, view)} title={`${time(c.start)}–${time(c.end)} · 抽樣間隔 ${c.every} 秒`} />)}
      {working?.sample_start !== undefined && working.sample_end !== undefined && visible(working.sample_start, working.sample_end) &&
        <button className="ai-current-range" style={timelineRange(working.sample_start, working.sample_end, view)}
          aria-label={`AI 正在查看 ${time(working.sample_start)} 至 ${time(working.sample_end)}`}
          onClick={() => onSeek(working.sample_start!)} />}
      {signals.filter(e => visible(e.time)).map(e => <button key={e.id} className="ai-signal" style={{ left: `${timelinePosition(e.time, view)}%` }}
        title={`${time(e.time)} · ${e.event}`} aria-label={`查看證據 ${time(e.time)} ${e.event}`} onClick={() => onSeek(e.time)} />)}
      {!coverage.length && !signals.length && <span className="workbench-track-empty">等待 AI 探索</span>}
      {visible(current) && <span className="aligned-playhead" style={{ left: `${timelinePosition(current, view)}%` }} />}
    </div>
    <div className="workbench-exploration-details">
      <p role="status">{resetting ? "正在停止分析並重置查看進度…" : working
        ? `${working.phase === "extracting" ? "正在擷取畫面" : working.phase === "validating" ? "正在驗證" : "AI 正在查看"}${working.sample_start !== undefined && working.sample_end !== undefined ? ` ${time(working.sample_start)}–${time(working.sample_end)}` : "，等待範圍回報"}`
        : !searches.length && local.some(j => j.progress_reset) ? "AI 查看進度已重置，可以重新搜尋。" : "抽樣範圍不代表已確認勝利。"}</p>
      <button className="text-button reset-viewing-progress" disabled={resetting || !searches.length} title="清空已看範圍，保留候選與草稿"
        onClick={() => void onResetProgress()}><RotateCcw size={13} />{resetting ? "重置中…" : "重置 AI 查看進度"}</button>
    </div>
    {!!signals.length && <details className="ai-signal-list"><summary>查看 {signals.length} 個視覺訊號</summary>
      {signals.map(e => <button key={e.id} onClick={() => onSeek(e.time)}>{time(e.time)} · {e.event}</button>)}
    </details>}
  </section>;
}
