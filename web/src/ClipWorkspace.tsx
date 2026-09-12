import { useEffect, useRef } from "react";
import { Play, Trophy } from "lucide-react";
import { active, currentAnalysis, media, time, type Draft, type Job, type Project } from "./api";
import CandidateTimeline from "./CandidateTimeline";
import TimeRuler from "./TimeRuler";
import TimelineZoom, { zoomTimeline, type TimeWindow } from "./TimelineZoom";
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

export default function ClipWorkspace({ project, jobs, draft, selected, onSelect, onChange, onPlay, onSeek, current, selectedSegment, onSelectSegment, onError, view, onViewChange }: {
  project: Project; jobs: Job[]; draft: Draft; selected: string | null;
  onSelect: (job: Job) => void; onChange: (values: Partial<Draft>) => void;
  onPlay: (start: number, end: number) => void;
  onSeek: (seconds: number) => void; current: number;
  selectedSegment: string | null; onSelectSegment: (segment: NumberedCandidate, seconds?: number) => void;
  onError: (message: string) => void;
  view: TimeWindow; onViewChange: (view: TimeWindow) => void;
}) {
  const workspace = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ edge: "start" | "victory" | "end"; left: number; width: number; from: number; span: number; draft: Draft } | null>(null);
  const clips = candidates(project, jobs);
  const finish = draft.victory + draft.postroll;
  const valid = Number.isFinite(finish) && draft.start >= 0 && draft.start < draft.victory && draft.postroll >= 5 && draft.postroll <= 10 && finish <= project.duration!;
  const { from, to } = view;
  const span = Math.max(1, to - from);
  useEffect(() => {
    const element = workspace.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = (event.target as HTMLElement).closest(".clip-range-track, .candidate-overview");
      if (!target) return;
      event.preventDefault();
      if (drag.current) return;
      const rect = target.getBoundingClientRect();
      const anchor = from + Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * span;
      onViewChange(zoomTimeline(view, project.duration!, Math.exp(-Math.max(-100, Math.min(100, event.deltaY)) * .01), anchor));
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [view, project.duration, onViewChange, from, span]);
  const selectedJob = clips.find(j => j.id === selected);
  const searches = jobs.filter(currentAnalysis);
  const latest = searches.find(active) ?? searches[0];
  const evidence = latest?.evidence ?? latest?.result?.evidence ?? [];
  const coverage = latest?.coverage ?? latest?.result?.coverage ?? [];
  const thumbnails = project.thumbnails.filter(t => t.time >= from && t.time <= to).slice(0, 12);
  function adjust(edge: "start" | "victory" | "end", at: number, base: Draft) {
    const values = edge === "start" ? { start: Math.max(0, Math.min(base.victory - .033, at)) }
      : edge === "victory" ? { victory: Math.max(base.start + .033, Math.min(project.duration! - base.postroll, at)) }
      : { victory: Math.max(base.start + .033, Math.min(project.duration! - base.postroll, at - base.postroll)) };
    onChange(values);
    onSeek(edge === "start" ? values.start! : edge === "victory" ? values.victory! : values.victory! + base.postroll);
  }
  return <section className="clip-workspace" aria-label="片段工作區" ref={workspace}>
    <TimelineZoom duration={project.duration!} view={view} current={current}
      selection={{ from: draft.start, to: finish }} onChange={onViewChange} />
    {valid && <div className="clip-trimmer">
      <div className="clip-trimmer-heading"><strong>{selectedJob ? "AI 選取範圍" : draft.origin === "agent" ? "AI 候選草稿" : "手動草稿"}</strong>
        <button className="text-button" onClick={() => onPlay(draft.start, finish)}><Play size={13} />預覽這段 · {time(finish - draft.start)}</button></div>
      <TimeRuler start={from} end={to} />
      <div className="clip-range-track" ref={track}>
        {coverage.filter(c => c.end >= from && c.start <= to).map((c, i) => <span key={i} className={`review-coverage ${c.every <= .5 ? "dense" : ""}`}
          title={`${time(c.start)}–${time(c.end)} · 已抽樣`}
          style={{ left: `${Math.max(0, c.start - from) / span * 100}%`, width: `${(Math.min(to, c.end) - Math.max(from, c.start)) / span * 100}%` }} />)}
        {latest && active(latest) && latest.sample_start !== undefined && latest.sample_end !== undefined && <span className="ai-sample-range" aria-label="AI 本輪抽樣範圍"
          style={{ left: `${Math.max(0, Math.min(100, (latest.sample_start - from) / span * 100))}%`, width: `${Math.max(0, Math.min(to, latest.sample_end) - Math.max(from, latest.sample_start)) / span * 100}%` }} />}

        <div className="review-thumbnail-strip">{thumbnails.map(t => <img key={t.file} src={media(project, t.file)} alt={`來源縮圖 ${time(t.time)}`} loading="lazy" />)}</div>
        {finish >= from && draft.start <= to && <div className="clip-range-fill" style={{ left: `${(Math.max(from, draft.start) - from) / span * 100}%`, width: `${(Math.min(to, finish) - Math.max(from, draft.start)) / span * 100}%` }}>
          <span>選取範圍</span>
        </div>}
        <input className="compact-seek" type="range" aria-label="播放位置" min={from} max={to} step={1 / 30} value={Math.max(from, Math.min(to, current))} onChange={e => onSeek(Number(e.target.value))} />
        {evidence.filter(e => e.time >= from && e.time <= to).map((e, i) => <button key={i} className="review-evidence-pin" onClick={() => onSeek(e.time)}
          aria-label={`查看證據 ${time(e.time)} ${e.event}`} title={`${time(e.time)} · ${e.event}`} style={{ left: `${(e.time - from) / span * 100}%` }} />)}
        {current >= from && current <= to && <span className="review-playhead" style={{ left: `${(current - from) / span * 100}%` }} />}
        {draft.victory >= from && draft.victory <= to && <span className="clip-victory-tick" title={`勝利 ${time(draft.victory)}`} style={{ left: `${(draft.victory - from) / span * 100}%` }}>勝利</span>}
        {(["start", "victory", "end"] as const).filter(edge => {
          const at = edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish;
          return at >= from && at <= to;
        }).map(edge => <button key={edge} className={`clip-range-handle ${edge === "victory" ? "victory-handle" : ""}`} role="slider"
          aria-label={edge === "start" ? "片段開始邊界" : edge === "victory" ? "勝利位置邊界" : "片段結束邊界"}
          aria-valuemin={edge === "start" ? 0 : edge === "victory" ? draft.start + .033 : draft.start + .033 + draft.postroll}
          aria-valuemax={edge === "start" ? draft.victory - .033 : edge === "victory" ? project.duration! - draft.postroll : project.duration!}
          aria-valuenow={edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish}
          aria-valuetext={time(edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish, true)}
          style={{ left: `${((edge === "start" ? draft.start : edge === "victory" ? draft.victory : finish) - from) / span * 100}%` }}
          title={edge === "end" ? "調整片段終點，勝利位置隨之移動並保留收尾秒數" : edge === "victory" ? "調整勝利位置" : "調整片段起點"}
          onPointerDown={e => { e.preventDefault(); const rect = track.current!.getBoundingClientRect(); drag.current = { edge, left: rect.left, width: rect.width, from, span, draft }; e.currentTarget.setPointerCapture(e.pointerId); }}
          onPointerMove={e => {
            const d = drag.current;
            if (!d || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
            const at = d.from + Math.max(0, Math.min(1, (e.clientX - d.left) / d.width)) * d.span;
            adjust(d.edge, at, d.draft);
          }}
          onPointerUp={e => { drag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
          onPointerCancel={() => { drag.current = null; }}
          onLostPointerCapture={() => { drag.current = null; }}
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
    <CandidateTimeline project={project} segments={reviewCandidates(project, jobs)} selected={selectedSegment}
      view={view}
      current={current} onSelect={onSelectSegment} onSeek={onSeek} onPlay={onPlay} onApply={onChange} onError={onError} />
    {!!clips.length && <div className="clip-candidates" aria-label="AI 候選片段">
      {clips.map(job => <button key={job.id} className={selected === job.id ? "selected" : ""}
        aria-pressed={selected === job.id} aria-label={`選取片段 ${job.result!.boss || "成功挑戰"}`} onClick={() => onSelect(job)}>
        <Trophy size={13} /><strong>{job.result!.boss || "成功挑戰"}</strong><span>{time(job.result!.victory! + job.result!.postroll - job.result!.start!)}</span>
      </button>)}
    </div>}
  </section>;
}
