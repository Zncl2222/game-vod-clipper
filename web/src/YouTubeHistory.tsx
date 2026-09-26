import { useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import "./storage-manager.css";

export type ImportHistory = { id: string; title: string; url: string; import_count: number;
  first_imported_at: number | null; last_imported_at: number | null; completed: boolean; project_id: string | null };

export default function YouTubeHistory({ onClose, onOpen }: { onClose: () => void; onOpen: (id: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null), heading = useId();
  const [items, setItems] = useState<ImportHistory[] | null>(null), [error, setError] = useState("");
  const [query, setQuery] = useState(""), [removed, setRemoved] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    let alive = true;
    element?.showModal();
    api<ImportHistory[]>("/youtube/history").then(value => { if (alive) setItems(value); })
      .catch(reason => { if (alive) setError(reason.message); });
    return () => { alive = false; element?.close(); previous?.focus(); };
  }, []);
  const visible = (items ?? []).filter(item => (!removed || !item.project_id)
    && `${item.title} ${item.id}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <dialog ref={dialog} className="project-dialog media-manager" aria-labelledby={heading}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}
    onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); } }}>
    <h2 id={heading}>YouTube 匯入歷史</h2>
    <p>刪除專案或影片檔案後仍保留。不需連接 Google 帳號也能查詢；尚未下載完成的匯入會另外標示。</p>
    <div className="media-manager-tools"><label>搜尋影片名稱或 ID<input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <label><input type="checkbox" checked={removed} onChange={event => setRemoved(event.target.checked)} />只看專案已刪除</label></div>
    {error && <p role="alert" className="project-dialog-error">{error}</p>}
    {!items && !error && <p role="status">載入中…</p>}
    <ul className="media-manager-list" aria-label="YouTube 匯入歷史清單">{visible.map(item => <li key={item.id}><div>
      <strong>{item.title}</strong><p>{item.completed ? "曾匯入完成" : "曾建立匯入，未確認完成"} · {item.project_id ? "專案仍保留" : "專案已刪除"} · {item.import_count} 次</p>
      <p>首次：{item.first_imported_at ? new Date(item.first_imported_at * 1000).toLocaleString("zh-TW") : "舊紀錄未記載時間"}
        {item.last_imported_at && item.last_imported_at !== item.first_imported_at && ` · 最近：${new Date(item.last_imported_at * 1000).toLocaleString("zh-TW")}`}</p>
      <a href={item.url} target="_blank" rel="noreferrer">在 YouTube 查看 · {item.id}</a></div>
      {item.project_id && <button className="secondary" onClick={() => { onClose(); onOpen(item.project_id!); }}>開啟專案</button>}
    </li>)}</ul>
    {items && !visible.length && <p>{items.length ? "沒有符合的匯入紀錄。" : "還沒有可查詢的 YouTube 匯入紀錄。"}</p>}
    <div className="project-dialog-actions"><button className="secondary" onClick={onClose}>關閉匯入歷史</button></div>
  </dialog>;
}
