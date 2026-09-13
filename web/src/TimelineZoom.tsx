import { type ReactNode } from "react";
import { ChevronLeft, ChevronRight, LocateFixed, Maximize2, Minus, Plus } from "lucide-react";
import { time } from "./api";

export type TimeWindow = { from: number; to: number };

export function timelineWindow(from: number, span: number, duration: number): TimeWindow {
  if (!Number.isFinite(from) || !Number.isFinite(span)) return { from: 0, to: duration };
  const size = Math.max(Math.min(5, duration), Math.min(duration, span));
  const left = Math.max(0, Math.min(duration - size, from));
  return { from: left, to: left + size };
}

export function zoomTimeline(view: TimeWindow, duration: number, factor: number, anchor: number): TimeWindow {
  const span = view.to - view.from;
  const size = Math.max(Math.min(5, duration), Math.min(duration, span / factor));
  const fraction = Math.max(0, Math.min(1, (anchor - view.from) / span));
  return timelineWindow(anchor - size * fraction, size, duration);
}

export default function TimelineZoom({ duration, view, current, selection, onChange, children }: {
  duration: number; view: TimeWindow; current: number; selection: TimeWindow; onChange: (view: TimeWindow) => void; children?: ReactNode;
}) {
  const span = view.to - view.from;
  const level = Math.log2(duration / span);
  const validSelection = Number.isFinite(selection.from) && Number.isFinite(selection.to)
    && selection.from >= 0 && selection.from < selection.to && selection.to <= duration;
  const maxLevel = Math.log2(duration / Math.min(5, duration));
  const anchor = current >= view.from && current <= view.to ? current : (view.from + view.to) / 2;
  const zoom = (factor: number) => onChange(zoomTimeline(view, duration, factor, anchor));
  return <div className="timeline-navigation" role="group" aria-label="時間軸縮放與導航">
    <div className="timeline-toolbar">
      <div className="timeline-view-label"><strong>剪輯與原片對照</strong><span>{time(view.from)}–{time(view.to)}</span></div>
      <div className="timeline-zoom-controls">
        <button type="button" aria-label="縮小時間軸" title="縮小時間軸" disabled={level <= .001} onClick={() => zoom(.5)}><Minus size={14} /></button>
        <input type="range" aria-label="時間軸縮放倍率" min={0} max={maxLevel} step="any" value={level}
          aria-valuetext={`${(duration / span).toFixed(1)} 倍，顯示 ${span.toFixed(1)} 秒`}
          onChange={e => zoom(2 ** (Number(e.target.value) - level))} />
        <button type="button" aria-label="放大時間軸" title="放大時間軸" disabled={level >= maxLevel - .001} onClick={() => zoom(2)}><Plus size={14} /></button>
        <output>{(duration / span).toFixed(level > 3 ? 0 : 1)}×</output>
      </div>
      <div className="timeline-shortcuts">
        {children}
        <button type="button" aria-label="放大片段" title="讓選取範圍填滿時間軸" disabled={!validSelection} onClick={() => onChange(timelineWindow(selection.from - 5, selection.to - selection.from + 10, duration))}>目前剪輯</button>
        <button type="button" aria-label="定位播放頭" title="移到目前播放位置" onClick={() => onChange(timelineWindow(current - span / 2, span, duration))}><LocateFixed size={14} /></button>
        <button type="button" aria-label="看全片" title="重設為全片" onClick={() => onChange({ from: 0, to: duration })}><Maximize2 size={13} />全片</button>
      </div>
    </div>
    {level > .001 && <div className="timeline-pan-row">
      <button type="button" aria-label="向前移動時間軸" disabled={view.from <= 0} onClick={() => onChange(timelineWindow(view.from - span / 2, span, duration))}><ChevronLeft size={15} /></button>
      <label className="timeline-pan-control">平移
        <input type="range" aria-label="可視範圍位置" min={0} max={Math.max(0, duration - span)} step="any" value={view.from}
          aria-valuetext={`${time(view.from)} 至 ${time(view.to)}`}
          onChange={e => onChange(timelineWindow(Number(e.target.value), span, duration))}
          onKeyDown={e => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
            e.preventDefault(); e.stopPropagation();
            const from = e.key === "Home" ? 0 : e.key === "End" ? duration - span
              : view.from + (e.key === "ArrowLeft" ? -1 : 1) * span * (e.shiftKey ? .5 : .1);
            onChange(timelineWindow(from, span, duration));
          }} />
      </label>
      <button type="button" aria-label="向後移動時間軸" disabled={view.to >= duration} onClick={() => onChange(timelineWindow(view.from + span / 2, span, duration))}><ChevronRight size={15} /></button>
    </div>}
  </div>;
}
