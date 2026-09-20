import { useEffect, useRef, useState } from "react";
import { ChevronRight, Film, ListFilter, Play, Trophy } from "lucide-react";
import { active, currentAnalysis, media, reviewCandidates, time, type Draft, type Job, type NumberedCandidate, type Project } from "./api";
import AIWorkspaceTimeline from "./AIWorkspaceTimeline";
import CandidateTimeline from "./CandidateTimeline";
import SelectionOverlay, { timelinePosition, validSelection } from "./SelectionOverlay";
import TimeRuler from "./TimeRuler";
import TimelineZoom, { timelineWindow, zoomTimeline, type TimeWindow } from "./TimelineZoom";

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

export default function ClipWorkspace({ project, jobs, draft, selected, onSelect, onChange, onPlay, onSeek, current,
  selectedSegment, onSelectSegment, onError, view, onViewChange, onResetProgress, resetting, highlightedFields = [] }: {
  project: Project; jobs: Job[]; draft: Draft; selected: string | null;
  onSelect: (job: Job) => void; onChange: (values: Partial<Draft>) => void;
  onPlay: (start: number, end: number) => void; onSeek: (seconds: number) => void; current: number;
  selectedSegment: string | null; onSelectSegment: (segment: NumberedCandidate, seconds?: number) => void;
  onError: (message: string) => void; view: TimeWindow; onViewChange: (view: TimeWindow) => void;
  onResetProgress: () => Promise<void>; resetting: boolean; highlightedFields?: string[];
}) {
  const workspace = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ edge: "start" | "victory"; pointer: number; left: number; width: number; from: number; span: number; draft: Draft } | null>(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [trackWidth, setTrackWidth] = useState(0);
  const duration = project.duration!;
  const finish = draft.victory + draft.postroll;
  const valid = validSelection(draft, duration);
  const { from, to } = view;
  const span = to - from;
  const clips = candidates(project, jobs);
  const selectedJob = clips.find(j => j.id === selected);
  const searches = jobs.filter(j => j.project_id === project.id && currentAnalysis(j));
  const working = searches.find(active);
  const thumbnails = project.thumbnails.filter(t => t.time >= from && t.time <= to).slice(0, 14);
  const selectionInView = valid && draft.start < to && finish > from;
  const crowdedMarkers = trackWidth > 0 && (draft.victory - draft.start) / span * trackWidth < 96;

  useEffect(() => {
    const element = track.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setTrackWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = workspace.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = (event.target as HTMLElement).closest(".clip-range-track, .candidate-overview, .ai-overview-track");
      if (!target) return;
      event.preventDefault();
      if (drag.current) return;
      // Candidate scrubbing owns a pointer capture; its time window remains stable.
      if (element.querySelector('[data-scrubbing="true"]')) return;
      const rect = target.getBoundingClientRect();
      const anchor = from + Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * span;
      onViewChange(zoomTimeline(view, duration, Math.exp(-Math.max(-100, Math.min(100, event.deltaY)) * .01), anchor));
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [view, duration, onViewChange, from, span]);

  function adjust(edge: "start" | "victory", at: number, base: Draft) {
    const value = edge === "start" ? Math.max(0, Math.min(base.victory - 1 / 30, at))
      : Math.max(base.start + 1 / 30, Math.min(duration - base.postroll, at));
    onChange({ [edge]: value });
    onSeek(value);
  }
  function apply(values: Partial<Draft>) {
    onChange(values);
    const next = { ...draft, ...values };
    if (validSelection(next, duration)) onViewChange(timelineWindow(next.start - 5, next.victory + next.postroll - next.start + 10, duration));
  }
  return <section className="clip-workspace unified-workbench" aria-label="片段工作區" ref={workspace}>
    <TimelineZoom duration={duration} view={view} current={current} selection={{ from: draft.start, to: finish }} onChange={onViewChange}>
      <button type="button" aria-expanded={showEvidence} aria-controls="workbench-evidence" onClick={() => setShowEvidence(value => !value)}>
        <ListFilter size={14} aria-hidden="true" />證據{working && <span className="tiny-dot" />}
      </button>
    </TimelineZoom>
    <div className="clip-trimmer">
      <div className="workbench-ruler"><span>原片時間</span><TimeRuler start={from} end={to} /></div>
      <div className="workbench-trim-row">
        <div className="workbench-lane-label clip-lane-label"><strong><Film size={14} aria-hidden="true" />目前剪輯</strong><small>匯出範圍 · 可調整</small></div>
        <div className="clip-range-track" data-crowded-markers={crowdedMarkers || undefined} ref={track}>
          <div className="review-thumbnail-strip">{thumbnails.map(t => <img key={t.file} src={media(project, t.file)} alt={`來源縮圖 ${time(t.time)}`} loading="lazy" />)}</div>
          <SelectionOverlay draft={draft} duration={duration} view={view} />
          <input className="compact-seek" type="range" aria-label="播放位置" min={from} max={to} step={1 / 30}
            aria-valuetext={time(Math.max(from, Math.min(to, current)), true)} value={Math.max(from, Math.min(to, current))} onChange={e => onSeek(Number(e.target.value))} />
          {current >= from && current <= to && <span className="review-playhead" style={{ left: `${(current - from) / span * 100}%` }} />}
          {valid && (["start", "victory"] as const).filter(edge => draft[edge] >= from && draft[edge] <= to).map(edge =>
            <button key={edge} className="clip-range-handle" data-edge={edge} role="slider"
              aria-label={edge === "start" ? "片段開始邊界" : "勝利位置邊界"}
              aria-valuemin={edge === "start" ? 0 : draft.start + 1 / 30} aria-valuemax={edge === "start" ? draft.victory - 1 / 30 : duration - draft.postroll}
              aria-valuenow={draft[edge]} aria-valuetext={time(draft[edge], true)}
              aria-describedby={edge === "victory" ? "clip-end-explanation" : undefined}
              style={{ left: `${(draft[edge] - from) / span * 100}%` }} title={edge === "start" ? "調整開始位置 · 方向鍵微調" : "調整勝利位置 · 收尾秒數保持不變"}
              onPointerDown={e => {
                if (!e.isPrimary || e.button !== 0 || drag.current) return;
                e.preventDefault(); e.currentTarget.focus({ preventScroll: true });
                const rect = track.current!.getBoundingClientRect();
                drag.current = { edge, pointer: e.pointerId, left: rect.left, width: rect.width, from, span, draft };
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerMove={e => {
                const d = drag.current;
                if (!d || d.pointer !== e.pointerId) return;
                adjust(d.edge, d.from + Math.max(0, Math.min(1, (e.clientX - d.left) / d.width)) * d.span, d.draft);
              }}
              onPointerUp={e => { drag.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
              onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
              onKeyDown={e => {
                if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
                e.preventDefault(); e.stopPropagation();
                adjust(edge, draft[edge] + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 1 / 30), draft);
              }}><span className="trim-handle-grip" /></button>)}
          {valid && draft.victory >= from && draft.victory <= to && <span className="clip-victory-guide" aria-hidden="true" style={{ left: `${timelinePosition(draft.victory, view)}%` }} />}
          {valid && ([{ kind: "start", at: draft.start, label: "開始" }, { kind: "victory", at: draft.victory, label: "勝利" }, { kind: "end", at: finish, label: "結束" }])
            .filter(point => point.at >= from && point.at <= to).map(point => <span key={point.kind}
              className={`clip-point-label point-${point.kind}`} aria-hidden="true" data-time={point.at}
              style={{ left: `clamp(0px, ${timelinePosition(point.at, view)}%, calc(100% - 48px))` }}>{point.label}</span>)}
          {valid && finish >= from && finish <= to && <span className="clip-end-marker" aria-hidden="true" style={{ left: `${timelinePosition(finish, view)}%` }} />}
        </div>
      </div>
    </div>
    <div id="source-selection-details" className={valid ? "sr-only" : "inline-error"} role={!valid ? "status" : undefined}>
      {valid ? <>目前剪輯 {time(draft.start, true)} → {time(finish, true)} · 片長 {time(finish - draft.start, true)} · 含收尾 {draft.postroll} 秒</>
        : "目前區間無效。請讓開始早於勝利，並保留原片內的 5–10 秒收尾。"}
    </div>
    {valid && !selectionInView && <p className="workbench-outside">目前剪輯區間在可視範圍外
      <button className="text-button" onClick={() => onViewChange(timelineWindow(draft.start - 5, finish - draft.start + 10, duration))}>回到目前剪輯</button></p>}
    <section className="workbench-timing" aria-label="剪輯設定">
      <h2 className="sr-only">剪輯設定</h2>
      {(["start", "victory"] as const).map(edge => <div className="workbench-time-field" key={edge}>
        <label htmlFor={edge}>{edge === "start" ? "開始時間" : "勝利時間"}<span>{time(draft[edge], true)}</span></label>
        <div><input id={edge} className={highlightedFields.includes(edge) ? "ai-target" : undefined} type="number" min="0" max={duration} step="0.001"
          aria-invalid={edge === "start" ? !Number.isFinite(draft.start) || draft.start < 0 || draft.start >= draft.victory : !Number.isFinite(draft.victory) || draft.victory <= draft.start || finish > duration}
          aria-describedby={!valid ? "source-selection-details" : undefined} value={draft[edge]} onChange={e => onChange({ [edge]: Number(e.target.value) })} />
          <span>秒</span><button type="button" aria-label={edge === "start" ? "跳到開始" : "跳到勝利"} onClick={() => onSeek(draft[edge])}><ChevronRight size={14} /></button></div>
      </div>)}
      <div className="workbench-postroll"><label htmlFor="postroll">勝利後收尾 <output>{draft.postroll} 秒</output></label>
        <input id="postroll" className={highlightedFields.includes("postroll") ? "ai-target" : undefined} type="range" min="5" max="10" step="1"
          aria-valuetext={`${draft.postroll} 秒`} aria-describedby="clip-end-explanation" value={draft.postroll} onChange={e => onChange({ postroll: Number(e.target.value) })} />
        <span>5–10 秒</span><p id="clip-end-explanation">結束＝勝利＋收尾 {draft.postroll} 秒</p></div>
      <div className="workbench-preview-actions">
        <button type="button" disabled={!valid} onClick={() => onPlay(draft.start, finish)}><Play size={14} />預覽這段 · {time(Math.max(0, finish - draft.start))}</button>
        <span className="clip-end-time">片段結束 {time(finish, true)}</span>
      </div>
    </section>
    <div className="source-comparison-legend" role="group" aria-label="原片對照圖例">
      <span><i className="source-legend-selection" aria-hidden="true" />實框：匯出範圍</span>
      <span><i className="source-legend-postroll" aria-hidden="true" />淡色區：收尾，仍會匯出</span>
    </div>
    <CandidateTimeline project={project} draft={draft} segments={reviewCandidates(project, jobs)} selected={selectedSegment} view={view}
      current={current} onSelect={onSelectSegment} onSeek={onSeek} onPlay={onPlay} onApply={apply} onError={onError} />
    <div id="workbench-evidence" hidden={!showEvidence}>
      <AIWorkspaceTimeline project={project} jobs={jobs} view={view} current={current} onSeek={onSeek} onResetProgress={onResetProgress} resetting={resetting} />
    </div>
    <details className="workbench-review-tools"><summary>快速核對與 AI 草稿{selectedJob ? ` · ${selectedJob.result!.boss || "成功挑戰"}` : ""}</summary>
      <div className="review-preview-actions">
        <button disabled={!valid} onClick={() => onPlay(draft.start, Math.min(finish, draft.start + 8))}><Play size={13} />檢查開頭</button>
        <button disabled={!valid} onClick={() => onPlay(Math.max(draft.start, draft.victory - 4), Math.min(finish, draft.victory + 3))}><Trophy size={13} />看勝利瞬間</button>
        <button disabled={!valid} onClick={() => onPlay(draft.victory, finish)}><Play size={13} />檢查收尾</button>
      </div>
      {!!clips.length && <div className="clip-candidates" role="group" aria-label="AI 候選片段">
        {clips.map(job => <button key={job.id} className={selected === job.id ? "selected" : ""} aria-pressed={selected === job.id}
          aria-label={`選取片段 ${job.result!.boss || "成功挑戰"}`} onClick={() => onSelect(job)}>
          <Trophy size={13} /><strong>{job.result!.boss || "成功挑戰"}</strong><span>{time(job.result!.victory! + job.result!.postroll - job.result!.start!)}</span>
        </button>)}
      </div>}
      {!!selectedJob?.result?.warnings.length && <details><summary>候選需留意的地方</summary>{selectedJob.result.warnings.map((w, i) => <p key={i}>{w}</p>)}</details>}
    </details>
  </section>;
}
