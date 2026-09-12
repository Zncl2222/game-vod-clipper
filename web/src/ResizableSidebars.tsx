import { useEffect, useRef, useState, type CSSProperties } from "react";

type Side = "library" | "chat";
type Widths = Partial<Record<Side, number>>;
const STORAGE = "bosscut:panel-widths";
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function readWidths(): Widths {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE) ?? "{}");
    return Object.fromEntries((["library", "chat"] as const)
      .filter(side => typeof value?.[side] === "number" && Number.isFinite(value[side]))
      .map(side => [side, value[side]]));
  } catch { return {}; }
}

function ResizeHandle({ side, value, min, max, onChange, onReset, onDragging }: {
  side: Side; value: number; min: number; max: number;
  onChange: (width: number) => void; onReset: () => void; onDragging: (value: boolean) => void;
}) {
  const drag = useRef<{ pointer: number; start: number; width: number } | null>(null);
  const direction = side === "library" ? 1 : -1;
  const label = side === "library" ? "調整素材庫寬度" : "調整 AI 側欄寬度";
  useEffect(() => () => onDragging(false), [onDragging]);
  return <div className={`panel-resize-handle ${side}`} role="separator" tabIndex={0}
    aria-label={label} aria-orientation="vertical" aria-controls={side === "library" ? "project-sidebar" : "ai-chat-panel"}
    aria-valuemin={min} aria-valuemax={max} aria-valuenow={Math.round(value)} aria-valuetext={`${Math.round(value)} 像素`}
    title={`${label} · 拖曳或使用方向鍵 · 雙擊還原`}
    onDoubleClick={onReset}
    onPointerDown={event => {
      if (!event.isPrimary || event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.focus({ preventScroll: true });
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointer: event.pointerId, start: event.clientX, width: value };
      onDragging(true);
    }}
    onPointerMove={event => {
      const start = drag.current;
      if (start?.pointer === event.pointerId) onChange(clamp(start.width + (event.clientX - start.start) * direction, min, max));
    }}
    onPointerUp={event => {
      if (drag.current?.pointer !== event.pointerId) return;
      const start = drag.current;
      onChange(clamp(start.width + (event.clientX - start.start) * direction, min, max));
      drag.current = null;
      onDragging(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    }}
    onPointerCancel={() => { drag.current = null; onDragging(false); }}
    onLostPointerCapture={() => { drag.current = null; onDragging(false); }}
    onKeyDown={event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      onChange(event.key === "Home" ? min : event.key === "End" ? max :
        clamp(value + (event.key === "ArrowLeft" ? -1 : 1) * direction * (event.shiftKey ? 30 : 10), min, max));
    }}><span /></div>;
}

export function usePanelLayout(chatOpen: boolean) {
  const [widths, setWidths] = useState<Widths>(readWidths);
  const [viewport, setViewport] = useState(window.innerWidth);
  const [resizing, setResizing] = useState(false);
  useEffect(() => {
    const resize = () => setViewport(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    try { localStorage.setItem(STORAGE, JSON.stringify(widths)); } catch { /* Keep resizing usable without storage. */ }
  }, [widths]);
  const desktop = viewport > 1180;
  const defaultLibrary = viewport >= 1550 ? 200 : viewport <= 1390 ? 170 : 184;
  const defaultChat = viewport >= 1550 ? 400 : viewport <= 1390 ? 350 : 376;
  const room = viewport - 540;
  const library = clamp(widths.library ?? defaultLibrary, 170, Math.max(170, Math.min(340, room - (desktop && chatOpen ? 300 : 0))));
  const chat = clamp(widths.chat ?? defaultChat, 300, desktop && chatOpen ? Math.max(300, Math.min(560, room - library)) : 560);
  const libraryMax = Math.max(170, Math.min(340, room - (desktop && chatOpen ? chat : 0)));
  const chatMax = Math.max(300, Math.min(560, room - library));
  const change = (side: Side, value: number) => setWidths(previous => ({ ...previous, [side]: value }));
  const reset = (side: Side) => setWidths(previous => {
    const next = { ...previous }; delete next[side]; return next;
  });
  return {
    style: { "--library-width": `${library}px`, "--chat-width": `${chat}px` } as CSSProperties,
    resizing,
    handles: <>
      {viewport > 640 && <ResizeHandle side="library" value={library} min={170} max={libraryMax}
        onChange={value => change("library", value)} onReset={() => reset("library")} onDragging={setResizing} />}
      {desktop && chatOpen && <ResizeHandle side="chat" value={chat} min={300} max={chatMax}
        onChange={value => change("chat", value)} onReset={() => reset("chat")} onDragging={setResizing} />}
    </>,
  };
}
