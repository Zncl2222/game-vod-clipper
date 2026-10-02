import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

const STORAGE = "bosscut:inspector-width";
const MIN_WIDTH = 264;
// The player keeps at least this much width beside the panel.
const MIN_VIDEO_WIDTH = 360;

/** Width of the clip settings panel beside the player; null follows the player's aspect ratio. */
export function useInspectorWidth(stage: RefObject<HTMLElement | null>, panel: RefObject<HTMLElement | null>) {
  const [preferred, setPreferred] = useState<number | null>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE) ?? "null");
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    } catch { return null; }
  });
  const [bounds, setBounds] = useState({ max: 440, current: MIN_WIDTH });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointer: number; x: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const element = stage.current, side = panel.current;
    if (!element || !side) return;
    const measure = () => setBounds({
      max: Math.max(MIN_WIDTH, Math.floor(element.clientWidth - MIN_VIDEO_WIDTH)),
      current: Math.round(side.getBoundingClientRect().width),
    });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    observer.observe(side);
    measure();
    return () => observer.disconnect();
  }, [stage, panel]);

  useEffect(() => {
    try {
      if (preferred === null) localStorage.removeItem(STORAGE);
      else localStorage.setItem(STORAGE, JSON.stringify(preferred));
    } catch { /* Resizing still works when browser storage is unavailable. */ }
  }, [preferred]);

  const clamp = (value: number) => Math.max(MIN_WIDTH, Math.min(bounds.max, Math.round(value)));
  const change = (value: number) => setPreferred(clamp(value));
  const stop = () => { drag.current = null; setDragging(false); };

  return {
    // CSS clamps again against the live stage width, so a saved width never squeezes the player.
    style: preferred === null ? undefined : { "--inspector-preferred": `${preferred}px` } as CSSProperties,
    dragging,
    handle: <div className="inspector-resize-handle" role="separator" tabIndex={0} aria-label="調整剪輯設定面板寬度"
      aria-orientation="vertical" aria-controls="clip-inspector"
      aria-valuemin={MIN_WIDTH} aria-valuemax={bounds.max} aria-valuenow={bounds.current} aria-valuetext={`${bounds.current} 像素`}
      title="左右拖曳調整面板與影片寬度 · 方向鍵微調 · 雙擊還原" onDoubleClick={() => setPreferred(null)}
      onPointerDown={event => {
        if (!event.isPrimary || event.button !== 0 || drag.current) return;
        event.preventDefault(); event.currentTarget.focus({ preventScroll: true });
        drag.current = { pointer: event.pointerId, x: event.clientX, width: bounds.current };
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragging(true);
      }}
      onPointerMove={event => {
        if (drag.current?.pointer === event.pointerId) change(drag.current.width + event.clientX - drag.current.x);
      }}
      onPointerUp={event => {
        if (drag.current?.pointer !== event.pointerId) return;
        change(drag.current.width + event.clientX - drag.current.x);
        stop();
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={stop} onLostPointerCapture={stop}
      onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); event.stopPropagation();
        change(event.key === "Home" ? MIN_WIDTH : event.key === "End" ? bounds.max
          : bounds.current + (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 40 : 10));
      }}><span aria-hidden="true" /></div>,
  };
}
