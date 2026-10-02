import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import SelectionOverlay, { validSelection } from "./SelectionOverlay";
import { type TimeWindow } from "./TimelineZoom";
import { Check, LoaderCircle, Pencil, Play, Sparkles, Tag } from "lucide-react";
import { active, api, candidateExports, time, type CandidateReview, type Draft, type Job, type NumberedCandidate, type Project } from "../../lib/api";

const kinds = { possible_win: "疑似勝利", fight: "戰鬥", death_retry: "死亡／重試", unknown: "待釐清" };
const confidence = { low: "低", medium: "中", high: "高" };
const reviews = { pending: "待核對", keep: "保留", reject: "排除" };
const verificationLabels = { unverified: "尚未驗證", blocked: "未通過驗證", verified: "已通過 AI 檢查" };

function ExportBadge({ count }: { count: number }) {
  return count ? <span className="candidate-export-badge"><Check size={13} aria-hidden="true" />已匯出{count > 1 ? ` · ${count} 次` : ""}</span> : null;
}

export default function CandidateTimeline({ project, jobs, segments, selected, current, onSelect, onSeek, onPlay, onEdit, onError, onRecheck, view, draft, detailTarget }: {
  project: Project; jobs: Job[]; segments: NumberedCandidate[]; selected: string | null; current: number;
  onSelect: (segment: NumberedCandidate, seconds?: number) => void; onSeek: (seconds: number) => void; onPlay: (start: number, end: number) => void;
  onEdit: (candidate: NumberedCandidate) => void; onError: (message: string) => void;
  onRecheck: (candidateId: string, start: number, end: number) => Promise<string>;
  view: TimeWindow; draft: Draft; detailTarget?: HTMLElement | null;
}) {
  const inPanel = (node: ReactNode) => detailTarget === undefined ? node : detailTarget ? createPortal(node, detailTarget) : null;
  const [busy, setBusy] = useState(false);
  const [recheckBusy, setRecheckBusy] = useState(false);
  const [recheckError, setRecheckError] = useState("");
  const [submitted, setSubmitted] = useState<{ candidateId: string; jobId: string } | null>(null);
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
  const editingSelected = candidate?.id === draft.candidate_id;
  const previewStart = editingSelected ? draft.start : candidate?.start ?? 0;
  const previewEnd = editingSelected ? draft.victory + draft.postroll : candidate?.end ?? 0;
  const recheckJob = candidate && jobs.find(job => job.kind === "analyze" && !job.progress_reset && job.analysis?.candidate_id === candidate.id);
  const otherAnalysisActive = jobs.some(job => job.project_id === project.id && job.kind === "analyze" && active(job));
  const recheckRangeValid = Number.isFinite(previewStart) && Number.isFinite(previewEnd)
    && previewStart >= 0 && previewStart < previewEnd && previewEnd <= duration;
  const exportCounts = new Map(segments.map(segment => [segment.id, candidateExports(project.id, segment, jobs).length]));
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
  const adjusted = (segment: NumberedCandidate) => !!segment.manual_edit || (draft.candidate_id === segment.id && !!draft.manually_adjusted);
  useEffect(() => { setRecheckError(""); }, [selected]);
  useEffect(() => {
    if (submitted && jobs.some(job => job.id === submitted.jobId)) setSubmitted(null);
  }, [jobs, submitted]);

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

  async function recheck() {
    if (!candidate || !recheckRangeValid || recheckBusy) return;
    setRecheckBusy(true);
    setRecheckError("");
    try {
      const jobId = await onRecheck(candidate.id, previewStart, previewEnd);
      setSubmitted({ candidateId: candidate.id, jobId });
    } catch (error) { setRecheckError((error as Error).message); }
    finally { setRecheckBusy(false); }
  }

  return <section className="candidate-review" aria-label="候選片段時間軸">
    <div className="workbench-lane-label candidate-lane-label"><strong><Sparkles size={14} aria-hidden="true" />AI 候選 <span>{segments.length}</span></strong><small>點選即編輯</small></div>
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
        aria-label={`時間軸片段 #${segment.number} ${kinds[segment.kind]} ${time(segment.start)} 至 ${time(segment.end)}${adjusted(segment) ? " · 已手動調整" : ""}${exportCounts.get(segment.id) ? " · 已匯出" : ""}`}
        data-candidate-id={segment.id}
        aria-pressed={selected === segment.id} onClick={e => { if (e.detail === 0) onSelect(segment); }}
        title={`#${segment.number} ${segment.boss} · ${kinds[segment.kind]} · ${time(segment.start)}–${time(segment.end)}${exportCounts.get(segment.id) ? " · 已匯出" : ""}`}>
        <b>{!!exportCounts.get(segment.id) && <Check size={12} aria-hidden="true" />}{adjusted(segment) ? <><Pencil size={11} aria-hidden="true" /> #{segment.number}</> : `AI #${segment.number}`}</b><span> {kinds[segment.kind]}</span>
        <i className="candidate-duration" aria-hidden="true" style={{
          left: `${((Math.max(from, segment.start) - from) / span * 100 - left) / width * 100}%`,
          width: `${(Math.min(to, segment.end) - Math.max(from, segment.start)) / span * 100 / width * 100}%`,
        }} />
      </button>)}
      {current >= from && current <= to && <span className="candidate-playhead" style={{ left: `${(current - from) / span * 100}%` }} />}
      </div>
    </div>
    <p className="candidate-reference-note">點選片段即可預覽與微調，匯出使用同一區間。<span>切換片段會保留修改。</span></p>
    <div className="candidate-legend">{Object.entries(kinds).map(([kind, label]) => <span key={kind} className={kind}><i />{label}</span>)}</div>
    {!segments.length && <p className="candidate-empty">AI 找到可疑片段後會陸續標在這裡；尚未確認勝利的片段也能點選預覽。</p>}
    {!!segments.length && <details className="candidate-list-disclosure"><summary>片段清單 · {segments.length} 個候選</summary><div className="candidate-list" role="group" aria-label="候選片段清單">
      {segments.map(segment => <button key={segment.id} aria-pressed={selected === segment.id}
        className={selected === segment.id ? "selected" : ""} onClick={() => onSelect(segment)}>
        <strong>#{segment.number} {segment.boss || kinds[segment.kind]}</strong>
        <span>{time(segment.start)}–{time(segment.end)}</span><small>{kinds[segment.kind]} · {verificationLabels[segment.verification ?? "unverified"]} · {reviews[review(segment)]}</small>
        {adjusted(segment) && <span className="manual-adjustment-badge"><Pencil size={12} aria-hidden="true" />已手動調整</span>}
        <ExportBadge count={exportCounts.get(segment.id) ?? 0} />
      </button>)}
    </div></details>}
    {candidate && inPanel(<div className="candidate-detail" role="group" aria-label={`片段 #${candidate.number} 詳情`}>
      <div className="candidate-heading"><div><strong>#{candidate.number} {candidate.boss || kinds[candidate.kind]}</strong>
        {adjusted(candidate) && <span className="manual-adjustment-badge"><Pencil size={12} aria-hidden="true" />已手動調整</span>}
        <ExportBadge count={exportCounts.get(candidate.id) ?? 0} />
        <span>{kinds[candidate.kind]} · {adjusted(candidate) ? "人工調整後待核對" : verificationLabels[verification]} · AI 辨識信心{confidence[candidate.confidence]} · {reviews[review(candidate)]}</span></div>
        <button type="button" className="candidate-recheck-button" disabled={!recheckRangeValid || otherAnalysisActive || recheckBusy || !!submitted}
          onClick={() => void recheck()} aria-label={`請 AI 複判片段 #${candidate.number}`}>
          {recheckBusy || submitted?.candidateId === candidate.id ? <LoaderCircle size={14} className="spin" aria-hidden="true" /> : <Sparkles size={14} aria-hidden="true" />}
          {recheckBusy ? "送出中…" : submitted?.candidateId === candidate.id ? "等待進度…" : "請 AI 複判這段"}
        </button>
        <button type="button" className="secondary candidate-edit-button" aria-label={`編輯片段 #${candidate.number} 區間`} onClick={() => onEdit(candidate)}><Pencil size={15} aria-hidden="true" />調整時間</button>
      </div>
      {candidate.kind === "possible_win" && verification !== "verified" && !candidate.manual_edit && <p className="candidate-warning" role="status">
        {verification === "blocked" ? "這段未通過成功挑戰驗證，請先核對失敗／重試畫面並修正區間。" : "這是初步標註，尚未確認完整成功嘗試，可能包含失敗／重試。"}
      </p>}
      <p>{editingSelected ? "目前區間" : "候選區間"} {time(previewStart, true)}–{time(previewEnd, true)}</p>
      <p className="candidate-original-range">候選標註 {time(candidate.start, true)}–{time(candidate.end, true)} · {candidate.summary}</p>
      {candidate.ai_range && <p className="candidate-original-range">AI 原始區間 {time(candidate.ai_range.start, true)}–{time(candidate.ai_range.end, true)} · 已保留供比對</p>}
      <p className="source-candidate-overlap">{editingSelected ? "預覽與匯出使用目前區間" : !validSelection(draft, duration) ? "區間無效，無法對照" : Math.min(draft.victory + draft.postroll, candidate.end) > Math.max(draft.start, candidate.start)
        ? `與目前剪輯重疊 ${time(Math.min(draft.victory + draft.postroll, candidate.end) - Math.max(draft.start, candidate.start), true)}` : "與目前剪輯未重疊"}</p>
      {candidate.warnings.map((warning, i) => <p className="candidate-warning" key={i}>{warning}</p>)}
      <div className="candidate-actions">
        <button disabled={index <= 0} onClick={() => onSelect(segments[index - 1])}>上一段</button>
        <button disabled={editingSelected && !validSelection(draft, duration)} onClick={() => onPlay(previewStart, previewEnd)}><Play size={13} />預覽 #{candidate.number}</button>
        <button disabled={index >= segments.length - 1} onClick={() => onSelect(segments[index + 1])}>下一段</button>
        <label><Tag size={13} /><select aria-label={`片段 #${candidate.number} 核對標籤`} disabled={busy}
          value={review(candidate)} onChange={e => void tag(e.target.value as CandidateReview)}>
          {Object.entries(reviews).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
      </div>
      <p className="candidate-hint">複判範圍 {time(previewStart, true)}–{time(previewEnd, true)}；AI 會檢查勝負、死亡／重試與完整進場。保留／排除僅用於整理候選，不影響匯出。</p>
      {otherAnalysisActive && (!recheckJob || !active(recheckJob)) && <p className="candidate-hint" role="status">目前有其他分析進行中；完成後即可複判這段。</p>}
      {recheckError && <p className="inline-error" role="alert">{recheckError}</p>}
      {recheckJob && <div className="candidate-recheck-result" role="group" aria-label={`片段 #${candidate.number} AI 複判結果`}>
        <div className="candidate-recheck-heading"><strong>AI 複判 · {time(recheckJob.analysis!.start, true)}–{time(recheckJob.analysis!.end, true)}</strong>
          <span role="status">{active(recheckJob) ? "判讀中" : recheckJob.status === "succeeded"
            ? recheckJob.result?.status === "candidate" ? "找到可能成功挑戰" : recheckJob.result?.status === "not_found" ? "未找到明確勝利" : "仍有疑點"
            : ({ failed: "複判失敗", cancelled: "已取消", interrupted: "已中斷" } as Record<string, string>)[recheckJob.status] ?? recheckJob.status}</span></div>
        {active(recheckJob) ? <p role="status">{recheckJob.stage || "正在準備判讀畫面…"}</p>
          : recheckJob.status === "succeeded" && recheckJob.result ? <>
            <p>{recheckJob.result.summary}</p>
            {!!recheckJob.result.evidence?.length && <div className="candidate-recheck-evidence" aria-label="複判畫面證據">
              {recheckJob.result.evidence.map((item, i) => <button key={i} type="button" onClick={() => onSeek(item.time)}>{time(item.time, true)} · {item.event}</button>)}
            </div>}
            {!!recheckJob.result.warnings?.length && <details><summary>需留意 {recheckJob.result.warnings.length} 項</summary>
              {recheckJob.result.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</details>}
            <p className="candidate-hint">這是本次送檢範圍的判斷；新標註會加入時間軸，原片段與剪輯時間不會自動改動。</p>
          </> : <p role="alert">{recheckJob.error || "複判未完成。可再次送出這段。"}</p>}
      </div>}
    </div>)}
  </section>;
}
