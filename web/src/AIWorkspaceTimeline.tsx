import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { RotateCcw } from "lucide-react";
import { active, currentAnalysis, time, reviewCandidates, type Draft, type Job, type Project } from "./api";
import TimeRuler from "./TimeRuler";
import { type TimeWindow } from "./TimelineZoom";

export default function AIWorkspaceTimeline({ project, jobs, draft, current, onSeek, onResetProgress, resetting, view }: {
  project: Project; jobs: Job[]; draft: Draft; current: number; onSeek: (seconds: number) => void;
  onResetProgress: () => Promise<void>; resetting: boolean;
  view: TimeWindow;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const drag = useRef<{ pointer: number; left: number; width: number; from: number; to: number } | null>(null);
  const local = jobs.filter(j => j.project_id === project.id);
  const searches = local.filter(currentAnalysis);
  const working = searches.find(active);
  const exports = local.filter(j => j.kind === "export" && j.status === "succeeded" && j.draft);
  const encoding = local.find(j => j.kind === "export" && active(j));
  const clip = exports.find(j => j.id === selected) ?? exports[0];
  const index = exports.findIndex(j => j.id === clip?.id);
  const { from, to } = view;
  const visible = (start: number, end = start) => end >= from && start <= to;
  const position = (seconds: number) => Math.max(0, Math.min(100, (seconds - from) / (to - from) * 100));
  const range = (start: number, end: number) => ({ left: `${position(start)}%`, width: `${Math.max(0, position(end) - position(start))}%` });
  const signals = searches.flatMap(j => (j.evidence ?? j.result?.evidence ?? []).map((e, i) => ({ ...e, id: `${j.id}:${i}` })));
  const coverage = searches.flatMap(j => j.coverage ?? j.result?.coverage ?? []);
  const candidates = reviewCandidates(project, jobs);
  const playhead = visible(current) && <span className="aligned-playhead" style={{ left: `${position(current)}%` }} />;
  function seekPointer(clientX: number) {
    const bounds = drag.current;
    if (!bounds) return;
    onSeek(bounds.from + Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width)) * (bounds.to - bounds.from));
  }
  const scrub = {
    tabIndex: 0,
    role: "group",
    onPointerDown(event: PointerEvent<HTMLDivElement>) {
      if (!event.isPrimary || event.button !== 0 || drag.current) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (!bounds.width) return;
      event.preventDefault();
      // Use the whole source track, including the current zoom window, rather
      // than the candidate's visible width. Freeze it for this drag gesture.
      drag.current = { pointer: event.pointerId, left: bounds.left, width: bounds.width, from, to };
      ((event.target as HTMLElement).closest("button") ?? event.currentTarget).focus({ preventScroll: true });
      event.currentTarget.setPointerCapture(event.pointerId);
      seekPointer(event.clientX);
    },
    onPointerMove(event: PointerEvent<HTMLDivElement>) {
      if (drag.current?.pointer === event.pointerId) seekPointer(event.clientX);
    },
    onPointerUp(event: PointerEvent<HTMLDivElement>) {
      if (drag.current?.pointer !== event.pointerId) return;
      seekPointer(event.clientX);
      drag.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    },
    onPointerCancel(event: PointerEvent<HTMLDivElement>) {
      if (drag.current?.pointer === event.pointerId) drag.current = null;
    },
    onLostPointerCapture(event: PointerEvent<HTMLDivElement>) {
      if (drag.current?.pointer === event.pointerId) drag.current = null;
    },
    onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      onSeek(event.key === "Home" ? from : event.key === "End" ? to :
        Math.max(from, Math.min(to, current + (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 10 : 1))));
    },
  };
  return <section className="ai-workspace-timeline" aria-label="AI 探索與成品時間軸">
    <div className="candidate-heading"><strong>原片對照時間軸</strong><span>所有軌道共用原片時間 · {time(current)}</span></div>
    <p>點選或拖曳草稿與候選色塊，可定位到對應的原片時間。</p>
    <TimeRuler start={from} end={to} />
    <div className="aligned-source-track">
      <input type="range" aria-label="共用原片播放位置" min={from} max={to} step={1 / 30} value={Math.max(from, Math.min(to, current))} onChange={e => onSeek(Number(e.target.value))} />
      {playhead}
    </div>
    <div className="candidate-heading"><strong>{draft.origin === "agent" ? "AI 草稿" : "手動草稿"}</strong><span>{time(draft.start)}–{time(draft.victory + draft.postroll)}</span></div>
    <div className="aligned-draft-track source-scrub-track" aria-label="草稿原片對照" {...scrub}>
      {visible(draft.start, draft.victory + draft.postroll) && <button style={range(draft.start, draft.victory + draft.postroll)} onClick={event => { if (event.detail === 0) onSeek(draft.start); }} aria-label="查看草稿原片位置" />}{playhead}
    </div>
    {!!candidates.length && <div className="aligned-candidates" aria-label="AI 片段原片對照">
      {candidates.map(segment => <div key={segment.id}>
        <div className="candidate-heading"><strong>AI #{segment.number} · {segment.boss || segment.kind}</strong><span>{time(segment.start)}–{time(segment.end)}</span></div>
        <div className="aligned-draft-track source-scrub-track" aria-label={`AI 片段 #${segment.number} 原片定位`} {...scrub}>
          {visible(segment.start, segment.end) && <button className={`aligned-candidate ${segment.kind}`} style={range(segment.start, segment.end)}
            onClick={event => { if (event.detail === 0) onSeek(segment.start); }} aria-label={`對照 AI 片段 #${segment.number}`} />}{playhead}</div>
      </div>)}
    </div>}
    <div className="candidate-heading"><strong>AI 探索 · 全片</strong>
      <button className="text-button reset-viewing-progress" disabled={resetting || !searches.length}
        onClick={() => void onResetProgress()}><RotateCcw size={13} />{resetting ? "重置中…" : "重置 AI 查看進度"}</button>
    </div>
    <p>清空已看範圍，保留候選與草稿；下次搜尋會從所選範圍重新分析。</p>
    <p role="status">{resetting ? "正在停止分析並重置查看進度…" : working
      ? `${working.phase === "extracting" ? "正在擷取畫面" : working.phase === "validating" ? "正在驗證" : "AI 正在查看"}${working.sample_start !== undefined && working.sample_end !== undefined ? ` ${time(working.sample_start)}–${time(working.sample_end)}` : "，等待範圍回報"}`
      : !searches.length && local.some(j => j.progress_reset) ? "AI 查看進度已重置，可以重新搜尋。"
      : "等待搜尋，或點選訊號回看原片"}</p>
    <div className="ai-overview-track" aria-label="AI 全片抽樣進度">
      {coverage.filter(c => visible(c.start, c.end)).map((c, i) => <span key={i} className={`ai-coverage ${c.every <= .5 ? "dense" : ""}`} style={range(c.start, c.end)} title={`${time(c.start)}–${time(c.end)} · 抽樣間隔 ${c.every} 秒`} />)}
      {working?.sample_start !== undefined && working.sample_end !== undefined && visible(working.sample_start, working.sample_end) &&
        <button className="ai-current-range" style={range(working.sample_start, working.sample_end)}
          aria-label={`AI 正在查看 ${time(working.sample_start)} 至 ${time(working.sample_end)}`}
          onClick={() => onSeek(working.sample_start!)} />}
      {signals.filter(e => visible(e.time)).map(e => <button key={e.id} className="ai-signal" style={{ left: `${position(e.time)}%` }}
        title={`${time(e.time)} · ${e.event}`} aria-label={`AI 訊號 ${time(e.time)} ${e.event}`} onClick={() => onSeek(e.time)} />)}
      {playhead}
    </div>
    <p>抽樣範圍不代表已確認勝利。</p>
    <TimeRuler start={from} end={to} />
    {!!signals.length && <details className="ai-signal-list"><summary>查看 {signals.length} 個視覺訊號</summary>
      {signals.map(e => <button key={e.id} onClick={() => onSeek(e.time)}>{time(e.time)} · {e.event}</button>)}
    </details>}
    <div className="candidate-heading"><strong>成品片段 <span>{exports.length}</span></strong>
      <span>{encoding ? `FFmpeg 剪輯中 · ${Math.round(encoding.progress)}%` : "點選色塊切換成品"}</span></div>
    <div className="export-overview" aria-label="已匯出片段時間軸">
      {exports.map((job, i) => <div className="export-timeline-row" key={job.id}>
        <span>#{i + 1}</span><div className="export-timeline-track">
          {visible(job.draft!.start, job.draft!.victory + job.draft!.postroll) && <button className={job.id === clip?.id ? "selected" : ""} aria-pressed={job.id === clip?.id}
            aria-label={`成品 #${i + 1} ${time(job.draft!.start)} 至 ${time(job.draft!.victory + job.draft!.postroll)}`}
            style={range(job.draft!.start, job.draft!.victory + job.draft!.postroll)}
            onClick={() => { setSelected(job.id); onSeek(job.draft!.start); }} />}
          {playhead}
        </div>
      </div>)}
    </div>
    {clip ? <section className="finished-clip-player" aria-label="成品切換播放器">
      <video key={clip.id} controls preload="metadata" src={`/api/jobs/${clip.id}/download`} aria-label={`成品預覽 #${index + 1}`} />
      <div className="finished-clip-controls">
        <label>切換成品<select aria-label="切換成品" value={clip.id} onChange={e => setSelected(e.target.value)}>
          {exports.map((j, i) => <option key={j.id} value={j.id}>#{i + 1} · {time(j.draft!.start)}–{time(j.draft!.victory + j.draft!.postroll)} · {j.draft!.origin === "agent" ? "AI" : "手動"}</option>)}
        </select></label>
        <p>原片 {time(clip.draft!.start)}–{time(clip.draft!.victory + clip.draft!.postroll)} · 收尾 {clip.draft!.postroll} 秒</p>
        <details className="export-location"><summary>檔案儲存位置</summary>
          <code>clips/web/{project.id}/{clip.id}.mp4</code>
          <p>影片已存於後端專案資料夾。按「下載 MP4」另存到這台電腦。</p>
        </details>
        <div><button disabled={index <= 0} onClick={() => setSelected(exports[index - 1].id)}>上一段</button>
          <button disabled={index >= exports.length - 1} onClick={() => setSelected(exports[index + 1].id)}>下一段</button>
          <a href={`/api/jobs/${clip.id}/download`} download>下載 MP4</a></div>
      </div>
    </section> : <p className="candidate-empty">完成剪輯後，每支成品會標示原片範圍，並可在這裡切換播放。</p>}
  </section>;
}
