import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export default function EditorTools({ open, onClose, error, onClearError, children }: {
  open: boolean; onClose: () => void; error: string; onClearError: () => void; children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const errorNotice = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    return () => {
      element?.querySelectorAll("video").forEach(video => video.pause());
      element?.close();
      previous?.focus({ preventScroll: true });
    };
  }, [open]);
  useEffect(() => {
    if (open && error) errorNotice.current?.focus();
  }, [open, error]);

  return <dialog ref={dialog} id="editor-tools" className="editor-tools-dialog" aria-labelledby="editor-tools-title"
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="editor-tools-heading">
      <div><h2 id="editor-tools-title">更多工具</h2><p>管理草稿、匯入分析結果與查看處理紀錄。</p></div>
      <button type="button" className="icon-button" aria-label="關閉更多工具" onClick={onClose}><X size={20} aria-hidden="true" /></button>
    </header>
    <div className="editor-tools-content">
      {error && <div ref={errorNotice} role="alert" tabIndex={-1} className="notice error">{error}
        <button type="button" onClick={onClearError} aria-label="關閉錯誤"><X size={16} aria-hidden="true" /></button>
      </div>}
      {children}
    </div>
  </dialog>;
}
