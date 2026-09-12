import { useRef } from "react";
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

export default function TimelineZoom({ duration, view, current, selection, onChange }: {
  duration: number; view: TimeWindow; current: number; selection: TimeWindow; onChange: (view: TimeWindow) => void;
}) {
  const drag = useRef<{ pointer: number; x: number; from: number; width: number; span: number } | null>(null);
  const span = view.to - view.from;
  const level = Math.log2(duration / span);
  const validSelection = Number.isFinite(selection.from) && Number.isFinite(selection.to)
    && selection.from >= 0 && selection.from < selection.to && selection.to <= duration;
  const maxLevel = Math.log2(duration / Math.min(5, duration));
  const anchor = current >= view.from && current <= view.to ? current : (view.from + view.to) / 2;
  const zoom = (factor: number) => onChange(zoomTimeline(view, duration, factor, anchor));
  return <div className="timeline-navigation" aria-label="時間軸縮放與導航">
    <div className="timeline-toolbar">
      <div className="timeline-view-label"><strong>時間軸</strong><span>{time(view.from)}–{time(view.to)}</span></div>
      <div className="timeline-zoom-controls">
        <button type="button" aria-label="縮小時間軸" title="縮小時間軸" disabled={level <= .001} onClick={() => zoom(.5)}><Minus size={14} /></button>
        <input type="range" aria-label="時間軸縮放倍率" min={0} max={maxLevel} step="any" value={level}
          aria-valuetext={`${(duration / span).toFixed(1)} 倍，顯示 ${span.toFixed(1)} 秒`}
          onChange={e => zoom(2 ** (Number(e.target.value) - level))} />
        <button type="button" aria-label="放大時間軸" title="放大時間軸" disabled={level >= maxLevel - .001} onClick={() => zoom(2)}><Plus size={14} /></button>
        <output>{(duration / span).toFixed(level > 3 ? 0 : 1)}×</output>
      </div>
      <div className="timeline-shortcuts">
        <button type="button" aria-label="放大片段" title="讓選取範圍填滿時間軸" disabled={!validSelection} onClick={() => onChange(timelineWindow(selection.from - 5, selection.to - selection.from + 10, duration))}>選取範圍</button>
        <button type="button" aria-label="定位播放頭" title="移到目前播放位置" onClick={() => onChange(timelineWindow(current - span / 2, span, duration))}><LocateFixed size={14} /></button>
        <button type="button" aria-label="看全片" title="重設為全片" onClick={() => onChange({ from: 0, to: duration })}><Maximize2 size={13} />全片</button>
      </div>
    </div>
    {level > .001 && <div className="timeline-pan-row">
      <button type="button" aria-label="向前移動時間軸" disabled={view.from <= 0} onClick={() => onChange(timelineWindow(view.from - span / 2, span, duration))}><ChevronLeft size={15} /></button>
      <div className="timeline-navigator" aria-label="全片導航" onPointerDown={e => {
        if (!e.isPrimary || e.button !== 0) return;
        e.preventDefault();
        const rect = e.currentTarget.getBoundingClientRect();
        const inside = (e.target as HTMLElement).closest(".timeline-visible-window");
        const next = inside ? view : timelineWindow((e.clientX - rect.left) / rect.width * duration - span / 2, span, duration);
        onChange(next);
        drag.current = { pointer: e.pointerId, x: e.clientX, from: next.from, width: rect.width, span };
        e.currentTarget.setPointerCapture(e.pointerId);
      }} onPointerMove={e => {
        const d = drag.current;
        if (d?.pointer === e.pointerId) onChange(timelineWindow(d.from + (e.clientX - d.x) / d.width * duration, d.span, duration));
      }} onPointerUp={e => {
        drag.current = null;
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
      }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}>
        {validSelection && <span className="timeline-navigator-selection" style={{ left: `${selection.from / duration * 100}%`, width: `${(selection.to - selection.from) / duration * 100}%` }} />}
        <span className="timeline-navigator-playhead" style={{ left: `${current / duration * 100}%` }} />
        <button type="button" role="slider" aria-label="可視範圍位置" className="timeline-visible-window"
          aria-valuemin={0} aria-valuemax={duration - span} aria-valuenow={view.from}
          aria-valuetext={`${time(view.from)} 至 ${time(view.to)}`}
          style={{ left: `${view.from / duration * 100}%`, width: `${span / duration * 100}%` }}
          onKeyDown={e => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
            e.preventDefault(); e.stopPropagation();
            const from = e.key === "Home" ? 0 : e.key === "End" ? duration - span
              : view.from + (e.key === "ArrowLeft" ? -1 : 1) * span * (e.shiftKey ? .5 : .1);
            onChange(timelineWindow(from, span, duration));
          }}><span /><span /></button>
      </div>
      <button type="button" aria-label="向後移動時間軸" disabled={view.to >= duration} onClick={() => onChange(timelineWindow(view.from + span / 2, span, duration))}><ChevronRight size={15} /></button>
    </div>}
    {level > .001 && <p className="timeline-navigation-hint">拖曳上方視窗移動範圍 · Ctrl / ⌘ + 滾輪縮放</p>}
  </div>;
}
