import { useEffect, useRef, useState } from "react";
import SelectionOverlay, { validSelection } from "./SelectionOverlay";
import { type TimeWindow } from "./TimelineZoom";
import { Play, Sparkles, Tag } from "lucide-react";
import { api, time, type CandidateReview, type Draft, type NumberedCandidate, type Project } from "./api";

const kinds = { possible_win: "疑似勝利", fight: "戰鬥", death_retry: "死亡／重試", unknown: "待釐清" };
const confidence = { low: "低", medium: "中", high: "高" };
const reviews = { pending: "待核對", keep: "保留", reject: "排除" };
const verificationLabels = { unverified: "尚未驗證", blocked: "未通過驗證", verified: "已通過 AI 檢查" };

export default function CandidateTimeline({ project, segments, selected, current, onSelect, onSeek, onPlay, onApply, onError, view, draft }: {
  project: Project; segments: NumberedCandidate[]; selected: string | null; current: number;
  onSelect: (segment: NumberedCandidate, seconds?: number) => void; onSeek: (seconds: number) => void; onPlay: (start: number, end: number) => void;
  onApply: (draft: Partial<Draft>) => void; onError: (message: string) => void;
  view: TimeWindow; draft: Draft;
}) {
  const [busy, setBusy] = useState(false);
  const drag = useRef<{ pointer: number; left: number; width: number; from: number; span: number;
    x: number; y: number; started: boolean; target: HTMLElement; segment?: NumberedCandidate } | null>(null);
  const [savedReviews, setSavedReviews] = useState<Record<string, CandidateReview>>({});
  useEffect(() => {
    setSavedReviews(previous => {
      const acknowledged = Object.keys(previous).filter(id => segments.some(c => c.id === id && c.review === previous[id]));
      if (!acknowledged.length) return previous;
      return Object.fromEntries(Object.entries(previous).filter(([id]) => !acknowledged.includes(id)));
    });
  }, [segments]);
  const duration = project.duration!;
  const { from, to } = view;
  const span = to - from;
  const position = (x: number, bounds: { left: number; width: number; from: number; span: number }) =>
    bounds.from + Math.max(0, Math.min(1, (x - bounds.left) / Math.max(1, bounds.width))) * bounds.span;
  const index = segments.findIndex(c => c.id === selected);
  const candidate = segments[index];
  const lanes: number[] = [];
  const markers = segments.filter(s => s.end >= from && s.start <= to).sort((a, b) => a.start - b.start).map(segment => {
    const left = Math.min(95, Math.max(0, segment.start - from) / span * 100);
    const width = Math.min(100 - left, Math.max(5, (Math.min(to, segment.end) - from) / span * 100 - left));
    let lane = lanes.findIndex(end => end + .5 <= left);
    if (lane < 0) lane = lanes.length;
    lanes[lane] = left + width;
    return { segment, left, width, lane };
  });
  const review = (segment: NumberedCandidate) => savedReviews[segment.id] ?? segment.review;
  const verification = candidate?.verification ?? "unverified";
  const postroll = candidate?.victory == null ? 0 : Math.min(candidate.postroll ?? 8, duration - candidate.victory);
  const canApply = candidate?.kind === "possible_win" && candidate.victory !== null
    && Number.isFinite(candidate.victory) && candidate.start < candidate.victory && candidate.victory <= candidate.end && postroll >= 5;

  function scrub(x: number) {
    const gesture = drag.current;
    if (!gesture) return;
    const seconds = position(x, gesture);
    if (!gesture.started) {
      gesture.started = true;
      gesture.target.focus({ preventScroll: true });
      if (gesture.segment) { onSelect(gesture.segment, seconds); return; }
    }
    onSeek(seconds);
  }

  async function tag(value: CandidateReview) {
    if (!candidate) return;
    setBusy(true);
    try {
      await api(`/projects/${project.id}/candidate-review`, "PUT", { candidate_id: candidate.id,
        review: value, analysis_generation: project.analysis_generation ?? 0 });
      setSavedReviews(previous => ({ ...previous, [candidate.id]: value }));
    } catch (error) { onError((error as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="candidate-review" aria-label="候選片段時間軸">
    <div className="workbench-lane-label candidate-lane-label"><strong><Sparkles size={14} aria-hidden="true" />AI 候選 <span>{segments.length}</span></strong><small>參考片段 · 點選預覽</small></div>
    <div className="candidate-overview" role="group" aria-label="候選時間軸定位" tabIndex={0}
      onPointerDown={e => {
        if (!e.isPrimary || e.button !== 0 || drag.current) return;
        const rect = e.currentTarget.getBoundingClientRect();
        e.preventDefault();
        const bounds = { left: rect.left, width: e.currentTarget.clientWidth, from, span };
        const button = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-candidate-id]");
        const segment = segments.find(s => s.id === button?.dataset.candidateId);
        drag.current = { pointer: e.pointerId, ...bounds, x: e.clientX, y: e.clientY,
          started: false, target: button ?? e.currentTarget, segment };
        e.currentTarget.dataset.scrubbing = "true";
        // Touch may become a vertical scroll; wait for a tap or horizontal movement.
        if (e.pointerType !== "touch") scrub(e.clientX);
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={e => {
        const gesture = drag.current;
        if (gesture?.pointer !== e.pointerId) return;
        if (!gesture.started) {
          const dx = Math.abs(e.clientX - gesture.x), dy = Math.abs(e.clientY - gesture.y);
          if (dx < 8 || dx <= dy) return;
        }
        scrub(e.clientX);
      }}
      onPointerUp={e => {
        const gesture = drag.current;
        if (gesture?.pointer !== e.pointerId) return;
        if (gesture.started || Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y) < 8) scrub(e.clientX);
        drag.current = null;
        delete e.currentTarget.dataset.scrubbing;
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onPointerCancel={e => { drag.current = null; delete e.currentTarget.dataset.scrubbing; }}
      onLostPointerCapture={e => { drag.current = null; delete e.currentTarget.dataset.scrubbing; }}
      onKeyDown={e => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
        e.preventDefault(); e.stopPropagation();
        onSeek(e.key === "Home" ? from : e.key === "End" ? to :
          Math.max(from, Math.min(to, current + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 10 : 1))));
      }}>
      <div className="candidate-track" style={{ height: Math.max(44, lanes.length * 40 + 8) }}>
      {!!segments.length && <SelectionOverlay draft={draft} duration={duration} view={view} reference />}
      {markers.map(({ segment, left, width, lane }) => <button key={segment.id}
        className={`candidate-marker ${segment.kind} ${selected === segment.id ? "selected" : ""} ${review(segment) === "reject" ? "rejected" : ""}`}
        style={{ left: `${left}%`, width: `${width}%`, top: lane * 40 + 4 }}
        aria-label={`時間軸片段 #${segment.number} ${kinds[segment.kind]} ${time(segment.start)} 至 ${time(segment.end)}`}
        data-candidate-id={segment.id}
        aria-pressed={selected === segment.id} onClick={e => { if (e.detail === 0) onSelect(segment); }}
        title={`#${segment.number} ${segment.boss} · ${kinds[segment.kind]} · ${time(segment.start)}–${time(segment.end)}`}>
        <b>AI #{segment.number}</b><span> {kinds[segment.kind]}</span>
        <i className="candidate-duration" aria-hidden="true" style={{
          left: `${((Math.max(from, segment.start) - from) / span * 100 - left) / width * 100}%`,
          width: `${(Math.min(to, segment.end) - Math.max(from, segment.start)) / span * 100 / width * 100}%`,
        }} />
      </button>)}
      {current >= from && current <= to && <span className="candidate-playhead" style={{ left: `${(current - from) / span * 100}%` }} />}
      </div>
    </div>
    <p className="candidate-reference-note">AI 候選供核對；放入剪輯草稿後才會成為匯出範圍。<span>虛線僅對齊目前剪輯。</span></p>
    <div className="candidate-legend">{Object.entries(kinds).map(([kind, label]) => <span key={kind} className={kind}><i />{label}</span>)}</div>
    {!segments.length && <p className="candidate-empty">AI 找到可疑片段後會陸續標在這裡；尚未確認勝利的片段也能點選預覽。</p>}
    {!!segments.length && <details className="candidate-list-disclosure"><summary>片段清單 · {segments.length} 個候選</summary><div className="candidate-list" role="group" aria-label="候選片段清單">
      {segments.map(segment => <button key={segment.id} aria-pressed={selected === segment.id}
        className={selected === segment.id ? "selected" : ""} onClick={() => onSelect(segment)}>
        <strong>#{segment.number} {segment.boss || kinds[segment.kind]}</strong>
        <span>{time(segment.start)}–{time(segment.end)}</span><small>{kinds[segment.kind]} · {verificationLabels[segment.verification ?? "unverified"]} · {reviews[review(segment)]}</small>
      </button>)}
    </div></details>}
    {candidate && <div className="candidate-detail" role="group" aria-label={`片段 #${candidate.number} 詳情`}>
      <div className="candidate-heading"><strong>#{candidate.number} {candidate.boss || kinds[candidate.kind]}</strong>
        <span>{kinds[candidate.kind]} · {verificationLabels[verification]} · 辨識信心{confidence[candidate.confidence]} · {reviews[review(candidate)]}</span></div>
      {candidate.kind === "possible_win" && verification !== "verified" && <p className="candidate-warning" role="status">
        {verification === "blocked" ? "這段未通過成功挑戰驗證，請先核對失敗／重試畫面並修正區間。" : "這是初步標註，尚未確認完整成功嘗試，可能包含失敗／重試。"}
      </p>}
      <p>{time(candidate.start, true)}–{time(candidate.end, true)} · {candidate.summary}</p>
      <p className="source-candidate-overlap">{!validSelection(draft, duration) ? "區間無效，無法對照" : Math.min(draft.victory + draft.postroll, candidate.end) > Math.max(draft.start, candidate.start)
        ? `與目前剪輯重疊 ${time(Math.min(draft.victory + draft.postroll, candidate.end) - Math.max(draft.start, candidate.start), true)}` : "與目前剪輯未重疊"}</p>
      {candidate.warnings.map((warning, i) => <p className="candidate-warning" key={i}>{warning}</p>)}
      <div className="candidate-actions">
        <button disabled={index <= 0} onClick={() => onSelect(segments[index - 1])}>上一段</button>
        <button onClick={() => onPlay(candidate.start, candidate.end)}><Play size={13} />預覽 #{candidate.number}</button>
        <button disabled={index >= segments.length - 1} onClick={() => onSelect(segments[index + 1])}>下一段</button>
        <label><Tag size={13} /><select aria-label={`片段 #${candidate.number} 核對標籤`} disabled={busy}
          value={review(candidate)} onChange={e => void tag(e.target.value as CandidateReview)}>
          {Object.entries(reviews).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        {canApply && <button className="secondary" onClick={() => onApply({ start: candidate.start, victory: candidate.victory!, postroll,
          origin: verification === "verified" ? "agent" : "manual" })}>
          {verification === "verified" ? `將 #${candidate.number} 放入剪輯草稿` : `載入 #${candidate.number} 手動修正`}
        </button>}
      </div>
      <p className="candidate-hint">可在 AI 對話輸入「查看 #{candidate.number}」。保留標籤不代表已確認成功；匯出前請檢查完整挑戰。</p>
    </div>}
  </section>;
}
