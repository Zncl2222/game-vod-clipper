import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";

const STORAGE = "bosscut:workbench-height";
const DEFAULT_HEIGHT = 260;
const MIN_HEIGHT = 160;
const canResize = () => window.matchMedia("(min-width: 641px) and (min-height: 701px)").matches;
const clamp = (value: number, max: number) => Math.max(MIN_HEIGHT, Math.min(max, value));

export function useWorkbenchSize(panel: RefObject<HTMLElement | null>, theater: boolean) {
  const [preferred, setPreferred] = useState<number | null>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE) ?? "null");
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    } catch { return null; }
  });
  const [max, setMax] = useState(500);
  const [enabled, setEnabled] = useState(canResize);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointer: number; y: number; height: number } | null>(null);
  const height = clamp(preferred ?? DEFAULT_HEIGHT, max);

  useLayoutEffect(() => {
    const element = panel.current;
    if (!element) return;
    const footer = element.querySelector<HTMLElement>(".compact-export");
    const divider = element.querySelector<HTMLElement>(".workbench-size-bar");
    const measure = () => {
      setEnabled(canResize());
      // Keep the source and export controls usable even at the largest saved size.
      setMax(Math.max(MIN_HEIGHT, Math.floor(element.clientHeight - (footer?.offsetHeight ?? 84) - (divider?.offsetHeight ?? 28) - 240)));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (footer) observer.observe(footer);
    if (divider) observer.observe(divider);
    window.addEventListener("resize", measure);
    measure();
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
  }, [panel, theater, enabled]);

  useEffect(() => {
    try {
      if (preferred === null) localStorage.removeItem(STORAGE);
      else localStorage.setItem(STORAGE, JSON.stringify(preferred));
    } catch { /* Resizing still works when browser storage is unavailable. */ }
  }, [preferred]);
  useEffect(() => { drag.current = null; setDragging(false); }, [enabled, theater]);
  const change = (value: number) => setPreferred(clamp(value, max));
  const reset = () => setPreferred(null);
  const stop = () => { drag.current = null; setDragging(false); };

  return {
    style: { "--workbench-height": `${height}px` } as CSSProperties,
    dragging,
    divider: enabled && <div className="workbench-size-bar">
      <div className="workbench-resize-handle" role="separator" tabIndex={0} aria-label="調整剪輯區高度"
        aria-orientation="horizontal" aria-controls="clip-workbench-panel"
        aria-valuemin={MIN_HEIGHT} aria-valuemax={max} aria-valuenow={Math.round(height)} aria-valuetext={`${Math.round(height)} 像素`}
        title="上下拖曳調整剪輯區 · 方向鍵微調 · 雙擊還原" onDoubleClick={reset}
        onPointerDown={event => {
          if (!event.isPrimary || event.button !== 0 || drag.current) return;
          event.preventDefault(); event.currentTarget.focus({ preventScroll: true });
          drag.current = { pointer: event.pointerId, y: event.clientY, height };
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }}
        onPointerMove={event => {
          if (drag.current?.pointer === event.pointerId) change(drag.current.height + drag.current.y - event.clientY);
        }}
        onPointerUp={event => {
          if (drag.current?.pointer !== event.pointerId) return;
          change(drag.current.height + drag.current.y - event.clientY);
          stop();
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={stop} onLostPointerCapture={stop}
        onKeyDown={event => {
          if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
          event.preventDefault(); event.stopPropagation();
          change(event.key === "Home" ? MIN_HEIGHT : event.key === "End" ? max
            : height + (event.key === "ArrowUp" ? 1 : -1) * (event.shiftKey ? 40 : 10));
        }}><span aria-hidden="true" /><small>拖曳調整剪輯區</small></div>
      <div className="workbench-size-actions" role="group" aria-label="剪輯區大小">
        <button type="button" aria-label="縮小剪輯區" title="縮小剪輯區" disabled={height <= MIN_HEIGHT} onClick={() => change(height - 40)}><Minus size={14} aria-hidden="true" /></button>
        <button type="button" aria-label="放大剪輯區" title="放大剪輯區" disabled={height >= max} onClick={() => change(height + 40)}><Plus size={14} aria-hidden="true" /></button>
        <button type="button" aria-label="還原剪輯區高度" title="還原剪輯區高度" onClick={reset}><RotateCcw size={13} aria-hidden="true" /></button>
      </div>
    </div>,
  };
}
