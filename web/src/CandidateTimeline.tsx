import { useEffect, useState } from "react";
import { Play, Tag } from "lucide-react";
import { api, time, type CandidateReview, type Draft, type NumberedCandidate, type Project } from "./api";

const kinds = { possible_win: "疑似勝利", fight: "戰鬥", death_retry: "死亡／重試", unknown: "待釐清" };
const confidence = { low: "低", medium: "中", high: "高" };
const reviews = { pending: "待核對", keep: "保留", reject: "排除" };

export default function CandidateTimeline({ project, segments, selected, current, onSelect, onPlay, onApply, onError }: {
  project: Project; segments: NumberedCandidate[]; selected: string | null; current: number;
  onSelect: (segment: NumberedCandidate) => void; onPlay: (start: number, end: number) => void;
  onApply: (draft: Partial<Draft>) => void; onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [savedReviews, setSavedReviews] = useState<Record<string, CandidateReview>>({});
  useEffect(() => {
    setSavedReviews(previous => {
      const acknowledged = Object.keys(previous).filter(id => segments.some(c => c.id === id && c.review === previous[id]));
      if (!acknowledged.length) return previous;
      return Object.fromEntries(Object.entries(previous).filter(([id]) => !acknowledged.includes(id)));
    });
  }, [segments]);
  const duration = project.duration!;
  const index = segments.findIndex(c => c.id === selected);
  const candidate = segments[index];
  const lanes: number[] = [];
  const markers = [...segments].sort((a, b) => a.start - b.start).map(segment => {
    const left = Math.min(95, segment.start / duration * 100);
    const width = Math.min(100 - left, Math.max(5, segment.end / duration * 100 - left));
    let lane = lanes.findIndex(end => end + .5 <= left);
    if (lane < 0) lane = lanes.length;
    lanes[lane] = left + width;
    return { segment, left, width, lane };
  });
  const review = (segment: NumberedCandidate) => savedReviews[segment.id] ?? segment.review;
  const postroll = candidate?.victory == null ? 0 : Math.min(8, duration - candidate.victory);
  const canApply = candidate?.kind === "possible_win" && candidate.victory !== null
    && Number.isFinite(candidate.victory) && candidate.start < candidate.victory && candidate.victory <= candidate.end && postroll >= 5;

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
    <div className="candidate-heading"><strong>候選片段 <span>{segments.length}</span></strong>
      <span>先標時間，再逐段核對</span></div>
    <div className="candidate-legend">{Object.entries(kinds).map(([kind, label]) => <span key={kind} className={kind}><i />{label}</span>)}</div>
    <div className="candidate-overview" style={{ height: Math.max(40, lanes.length * 30 + 8) }}>
      {markers.map(({ segment, left, width, lane }) => <button key={segment.id}
        className={`candidate-marker ${segment.kind} ${selected === segment.id ? "selected" : ""} ${review(segment) === "reject" ? "rejected" : ""}`}
        style={{ left: `${left}%`, width: `${width}%`, top: lane * 30 + 4 }}
        aria-label={`時間軸片段 #${segment.number} ${kinds[segment.kind]} ${time(segment.start)} 至 ${time(segment.end)}`}
        aria-pressed={selected === segment.id} onClick={() => onSelect(segment)}
        title={`#${segment.number} ${segment.boss} · ${kinds[segment.kind]} · ${time(segment.start)}–${time(segment.end)}`}>
        <b>#{segment.number}</b><span> {kinds[segment.kind]}</span>
        <i className="candidate-duration" aria-hidden="true" style={{
          left: `${(segment.start / duration * 100 - left) / width * 100}%`,
          width: `${(segment.end - segment.start) / duration * 100 / width * 100}%`,
        }} />
      </button>)}
      <span className="candidate-playhead" style={{ left: `${Math.max(0, Math.min(100, current / duration * 100))}%` }} />
    </div>
    <div className="candidate-scale"><span>{time(0)}</span><span>{time(duration / 2)}</span><span>{time(duration)}</span></div>
    {!segments.length && <p className="candidate-empty">AI 找到可疑片段後會陸續標在這裡；尚未確認勝利的片段也能點選預覽。</p>}
    {!!segments.length && <details className="candidate-list-disclosure"><summary>片段清單 · {segments.length} 個候選</summary><div className="candidate-list" aria-label="候選片段清單">
      {segments.map(segment => <button key={segment.id} aria-pressed={selected === segment.id}
        className={selected === segment.id ? "selected" : ""} onClick={() => onSelect(segment)}>
        <strong>#{segment.number} {segment.boss || kinds[segment.kind]}</strong>
        <span>{time(segment.start)}–{time(segment.end)}</span><small>{kinds[segment.kind]} · {reviews[review(segment)]}</small>
      </button>)}
    </div></details>}
    {candidate && <div className="candidate-detail" aria-label={`片段 #${candidate.number} 詳情`}>
      <div className="candidate-heading"><strong>#{candidate.number} {candidate.boss || kinds[candidate.kind]}</strong>
        <span>{kinds[candidate.kind]} · 信心{confidence[candidate.confidence]} · {reviews[review(candidate)]}</span></div>
      <p>{time(candidate.start, true)}–{time(candidate.end, true)} · {candidate.summary}</p>
      {candidate.warnings.map((warning, i) => <p className="candidate-warning" key={i}>{warning}</p>)}
      <div className="candidate-actions">
        <button disabled={index <= 0} onClick={() => onSelect(segments[index - 1])}>上一段</button>
        <button onClick={() => onPlay(candidate.start, candidate.end)}><Play size={13} />預覽 #{candidate.number}</button>
        <button disabled={index >= segments.length - 1} onClick={() => onSelect(segments[index + 1])}>下一段</button>
        <label><Tag size={13} /><select aria-label={`片段 #${candidate.number} 核對標籤`} disabled={busy}
          value={review(candidate)} onChange={e => void tag(e.target.value as CandidateReview)}>
          {Object.entries(reviews).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        {canApply && <button className="secondary" onClick={() => onApply({ start: candidate.start, victory: candidate.victory!, postroll, origin: "agent" })}>將 #{candidate.number} 放入剪輯草稿</button>}
      </div>
      <p className="candidate-hint">可在 AI 對話輸入「查看 #{candidate.number}」。保留標籤不代表已確認成功；匯出前請檢查完整挑戰。</p>
    </div>}
  </section>;
}
