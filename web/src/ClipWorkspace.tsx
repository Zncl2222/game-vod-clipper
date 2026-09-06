import { useRef, useState } from "react";
import { Play, Trophy } from "lucide-react";
import { active, media, time, type Draft, type Job, type Project } from "./api";
import CandidateTimeline from "./CandidateTimeline";
import { reviewCandidates, type NumberedCandidate } from "./api";

export function candidates(project: Project, jobs: Job[]) {
  return jobs.filter(j => {
    const r = j.result;
    return j.project_id === project.id && j.kind === "analyze" && j.status === "succeeded"
      && r?.status === "candidate" && (!r.project_id || r.project_id === project.id)
      && r.start !== null && r.victory !== null
      && [r.start, r.victory, r.postroll].every(Number.isFinite)
      && r.start >= 0 && r.start < r.victory && r.postroll >= 5 && r.postroll <= 10
      && r.victory + r.postroll <= project.duration!;
  });
}

export default function ClipWorkspace({ project, jobs, draft, selected, onSelect, onChange, onPlay, onSeek, current, selectedSegment, onSelectSegment, onError }: {
  project: Project; jobs: Job[]; draft: Draft; selected: string | null;
  onSelect: (job: Job) => void; onChange: (values: Partial<Draft>) => void;
  onPlay: (start: number, end: number) => void;
  onSeek: (seconds: number) => void; current: number;
  selectedSegment: string | null; onSelectSegment: (segment: NumberedCandidate) => void;
  onError: (message: string) => void;
}) {
  const [fullView, setFullView] = useState(false);
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ edge: "start" | "victory" | "end"; left: number; width: number; from: number; span: number; draft: Draft } | null>(null);
  const clips = candidates(project, jobs);
  const exports = jobs.filter(j => j.project_id === project.id && j.kind === "export" && j.status === "succeeded");
  const finish = draft.victory + draft.postroll;
  const valid = Number.isFinite(finish) && draft.start >= 0 && draft.start < draft.victory && draft.postroll >= 5 && draft.postroll <= 10 && finish <= project.duration!;
  const from = fullView ? 0 : Math.max(0, draft.start - 15);
  const to = fullView ? project.duration! : Math.min(project.duration!, finish + 15);
  const span = Math.max(1, to - from);
  const selectedJob = clips.find(j => j.id === selected);
  const latest = jobs.find(j => j.kind === "analyze" && active(j)) ?? jobs.find(j => j.kind === "analyze");
  const evidence = latest?.evidence ?? latest?.result?.evidence ?? [];
  const coverage = latest?.coverage ?? latest?.result?.coverage ?? [];
  const thumbnails = project.thumbnails.filter(t => t.time >= from && t.time <= to).slice(0, 12);
  function adjust(edge: "start" | "victory" | "end", at: number, base: Draft) {
    const values = edge === "start" ? { start: Math.max(0, Math.min(base.victory - .033, at)) }
      : edge === "victory" ? { victory: Math.max(base.start + .033, Math.min(project.duration! - base.postroll, at)) }
      : { postroll: Math.max(5, Math.min(10, project.duration! - base.victory, at - base.victory)) };
    onChange(values);
    onSeek(edge === "start" ? values.start! : edge === "victory" ? values.victory! : base.victory + values.postroll!);
  }
  return <section className="clip-workspace" aria-label="片段工作區">
    <CandidateTimeline project={project} segments={reviewCandidates(project, jobs)} selected={selectedSegment}
      current={current} onSelect={onSelectSegment} onPlay={onPlay} onApply={onChange} onError={onError} />
    {!!clips.length && <div className="clip-candidates" aria-label="AI 候選片段">
      {clips.map(job => <button key={job.id} className={selected === job.id ? "selected" : ""}
        aria-pressed={selected === job.id} aria-label={`選取片段 ${job.result!.boss || "成功挑戰"}`} onClick={() => onSelect(job)}>
        <Trophy size={13} /><strong>{job.result!.boss || "成功挑戰"}</strong><span>{time(job.result!.victory! + job.result!.postroll - job.result!.start!)}</span>
      </button>)}
    </div>}
    {valid && <div className="clip-trimmer">
      <div className="clip-trimmer-heading"><strong>{selectedJob ? "AI 選取範圍" : draft.origin === "agent" ? "AI 候選草稿" : "手動草稿"}</strong>
        <button className="text-button" onClick={() => setFullView(v => !v)}>{fullView ? "放大片段" : "看全片"}</button>
        <button className="text-button" onClick={() => onPlay(draft.start, finish)}><Play size={13} />預覽這段 · {time(finish - draft.start)}</button></div>
      <div className="clip-range-track" ref={track}>
        {coverage.filter(c => c.end >= from && c.start <= to).map((c, i) => <span key={i} className={`review-coverage ${c.every <= .5 ? "dense" : ""}`}
          title={`${time(c.start)}–${time(c.end)} · 已抽樣`}
          style={{ left: `${Math.max(0, c.start - from) / span * 100}%`, width: `${(Math.min(to, c.end) - Math.max(from, c.start)) / span * 100}%` }} />)}
        {latest && active(latest) && latest.sample_start !== undefined && latest.sample_end !== undefined && <span className="ai-sample-range" aria-label="AI 本輪抽樣範圍"
          style={{ left: `${Math.max(0, Math.min(100, (latest.sample_start - from) / span * 100))}%`, width: `${Math.max(0, Math.min(to, latest.sample_end) - Math.max(from, latest.sample_start)) / span * 100}%` }} />}

        <div className="review-thumbnail-strip">{thumbnails.map(t => <img key={t.file} src={media(project, t.file)} alt={`來源縮圖 ${time(t.time)}`} loading="lazy" />)}</div>
        <div className="clip-range-fill" style={{ left: `${(draft.start - from) / span * 100}%`, width: `${(finish - draft.start) / span * 100}%` }}>
          <span>選取範圍</span>
        </div>
        <input className="compact-seek" type="range" aria-label="播放位置" min={from} max={to} step={1 / 30} value={Math.max(from, Math.min(to, current))} onChange={e => onSeek(Number(e.target.value))} />
        {evidence.filter(e => e.time >= from && e.time <= to).map((e, i) => <button key={i} className="review-evidence-pin" onClick={() => onSeek(e.time)}
          aria-label={`查看證據 ${time(e.time)} ${e.event}`} title={`${time(e.time)} · ${e.event}`} style={{ left: `${(e.time - from) / span * 100}%` }} />)}
        {current >= from && current <= to && <span className="review-playhead" style={{ left: `${(current - from) / span * 100}%` }} />}
        <span className="clip-victory-tick" title={`勝利 ${time(draft.victory)}`} style={{ left: `${(draft.victory - from) / span * 100}%` }}>勝利</span>
        {(["start", "victory", "end"] as const).map(edge => <button key={edge} className={`clip-range-handle ${edge === "victory" ? "victory-handle" : ""}`} role="slider"
          aria-label={edge === "start" ? "片段開始邊界" : edge === "victory" ? "勝利位置邊界" : "片段結束邊界"}
          aria-valuemin={edge === "start" ? 0 : edge === "victory" ? draft.start + .033 : draft.victory + 5}
          aria-valuemax={edge === "start" ? draft.victory - .033 : edge === "victory" ? project.duration! - draft.postroll : Math.min(project.duration!, draft.victory + 10)}
          aria-valuenow={edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish}
          aria-valuetext={time(edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish, true)}
          style={{ left: `${((edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish) - from) / span * 100}%` }}
          onPointerDown={e => { const rect = track.current!.getBoundingClientRect(); drag.current = { edge, left: rect.left, width: rect.width, from, span, draft }; e.currentTarget.setPointerCapture(e.pointerId); }}
          onPointerMove={e => {
            const d = drag.current;
            if (!d || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
            const at = d.from + Math.max(0, Math.min(1, (e.clientX - d.left) / d.width)) * d.span;
            adjust(d.edge, at, d.draft);
          }}
          onPointerUp={e => { drag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
          onPointerCancel={() => { drag.current = null; }}
          onKeyDown={e => { if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return; e.preventDefault(); e.stopPropagation();
            const delta = (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 1 / 30);
            adjust(edge, (edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish) + delta, draft);
          }}><span /></button>)}
      </div>
      <div className="clip-range-labels"><span>開始 {time(draft.start, true)}</span><span>結束 {time(finish, true)}</span></div>
      <div className="review-preview-actions">
        <button onClick={() => onPlay(draft.start, Math.min(finish, draft.start + 8))}><Play size={13} /><span>檢查開頭</span></button>
        <button onClick={() => onPlay(Math.max(draft.start, draft.victory - 4), Math.min(finish, draft.victory + 3))}><Trophy size={13} /><span>看勝利瞬間</span></button>
        <button onClick={() => onPlay(Math.max(draft.start, draft.victory), finish)}><Play size={13} /><span>檢查收尾</span></button>
      </div>
      {!!selectedJob?.result?.warnings.length && <details><summary>候選需留意的地方</summary>{selectedJob.result.warnings.map((w, i) => <p key={i}>{w}</p>)}</details>}
    </div>}
    {!!exports.length && <details className="clip-exports"><summary>已匯出 {exports.length} 支影片</summary><div className="clip-cards">{exports.map(job => <article className="clip-export" key={job.id}>
      <video controls preload="none" src={`/api/jobs/${job.id}/download`} aria-label={`成品預覽 版本 ${job.draft?.revision ?? ""}`} />
      <strong>成品 · 版本 {job.draft?.revision}</strong><a href={`/api/jobs/${job.id}/download`} download>下載 MP4</a>
    </article>)}</div></details>}
  </section>;
}
