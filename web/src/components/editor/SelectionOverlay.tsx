import { type Draft } from "../../lib/api";
import { type TimeWindow } from "./TimelineZoom";

export function validSelection(draft: Draft, duration: number) {
  return [draft.start, draft.victory, draft.postroll, duration].every(Number.isFinite)
    && draft.start >= 0 && draft.start < draft.victory
    && draft.postroll >= 5 && draft.postroll <= 10 && draft.victory + draft.postroll <= duration;
}

export function timelinePosition(seconds: number, view: TimeWindow) {
  return Math.max(0, Math.min(100, (seconds - view.from) / Math.max(.001, view.to - view.from) * 100));
}

export function timelineRange(start: number, end: number, view: TimeWindow) {
  const left = timelinePosition(start, view);
  return { left: `${left}%`, width: `${Math.max(0, timelinePosition(end, view) - left)}%` };
}

/** One source-time selection, reused by the filmstrip and candidate comparison. */
export default function SelectionOverlay({ draft, duration, view, reference = false }: { draft: Draft; duration: number; view: TimeWindow; reference?: boolean }) {
  const end = draft.victory + draft.postroll;
  if (!validSelection(draft, duration) || draft.start >= view.to || end <= view.from) return null;
  return <>
    <span className={`source-selection-fill${reference ? " source-reference-fill" : ""}`} aria-hidden="true" style={timelineRange(draft.start, end, view)} />
    {!reference && draft.victory < view.to && end > view.from && <span className="source-selection-postroll" aria-hidden="true" style={timelineRange(draft.victory, end, view)} />}
    {[draft.start, end].filter(at => at >= view.from && at <= view.to).map((at, index) =>
      <span key={index} className={`source-selection-edge${reference ? " source-reference-edge" : ""}`} aria-hidden="true" style={{ left: `${timelinePosition(at, view)}%` }} />)}
  </>;
}
