import { useEffect, useId, useRef, useState } from "react";
import { api } from "./api";
import "./storage-manager.css";

type StoredVideo = { id: string; name: string; path: string; category: string; bytes: number; blocked: string;
  project_id: string | null; job_id: string | null };
type Inventory = { items: StoredVideo[]; incomplete: boolean };
type DeletionResult = { deleted: { id: string; bytes: number; project_id: string | null; job_id: string | null }[];
  failed: { id: string; detail: string }[]; bytes: number };
const selectionLimit = 500;
const categories = { sources: "原片", exports: "成品剪輯", previews: "舊預覽與暫存" };
export const formatBytes = (value: number) => value >= 1e9 ? `${(value / 1e9).toFixed(2)} GB`
  : value >= 1e6 ? `${(value / 1e6).toFixed(1)} MB` : `${(value / 1000).toFixed(1)} KB`;

function ConfirmDeletion({ items, onClose, onDeleted }: {
  items: StoredVideo[]; onClose: () => void; onDeleted: (result: DeletionResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), cancel = useRef<HTMLButtonElement>(null);
  const heading = useId(), description = useId();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal(); cancel.current?.focus();
    return () => { element?.close(); previous?.focus(); };
  }, []);
  async function remove() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true); setError("");
    try {
      const result = await api<DeletionResult>("/storage/delete-batch", "POST", { ids: items.map(item => item.id) });
      onDeleted(result);
    } catch (reason) { setError(`${(reason as Error).message}。刪除結果尚未確認，請關閉此視窗並重新整理清單。`); setBusy(false); }
    finally { pending.current = false; }
  }
  return <dialog ref={dialog} className="project-dialog" role="alertdialog" aria-labelledby={heading} aria-describedby={description}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!busy) onClose(); }}>
    <h2 id={heading}>{items.length === 1 ? "永久刪除這個影片檔案？" : `永久刪除 ${items.length} 個影片檔案？`}</h2>
    <div id={description}><p>將刪除 {items.length} 個本機檔案（共 {formatBytes(items.reduce((sum, item) => sum + item.bytes, 0))}）
      {items.some(item => item.job_id) ? "及對應成品的紀錄、編輯草稿" : ""}，無法復原。</p>
      <p>YouTube 匯入歷史、YouTube 上的影片及其他本機影片都會保留。</p></div>
    <ul className="media-delete-files" aria-label="即將刪除的檔案">{items.map(item => <li key={item.id}>{item.path} · {formatBytes(item.bytes)}</li>)}</ul>
    {error && <p className="project-dialog-error" role="alert">{error}</p>}
    <div className="project-dialog-actions"><button ref={cancel} className="secondary" disabled={busy} onClick={onClose}>取消</button>
      <button className="project-delete-button" disabled={busy} onClick={() => void remove()}>{busy ? "刪除中…" : "永久刪除檔案"}</button></div>
  </dialog>;
}

export default function StorageManager({ onClose, onChanged, onClipRemoved }: {
  onClose: () => void; onChanged: () => void; onClipRemoved: (project: string, jobs: string[]) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId(), alive = useRef(true);
  const selectAll = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<Inventory | null>(null), [category, setCategory] = useState("sources");
  const [query, setQuery] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [confirmation, setConfirmation] = useState<StoredVideo[] | null>(null), [notice, setNotice] = useState("");
  const [failures, setFailures] = useState<{ path: string; detail: string }[]>([]);
  async function refresh() {
    setBusy(true); setError("");
    try {
      const value = await api<Inventory>("/storage/files");
      if (alive.current) {
        setData(value);
        const available = new Set(value.items.filter(item => !item.blocked).map(item => item.id));
        setSelected(previous => new Set([...previous].filter(id => available.has(id))));
      }
    }
    catch (reason) { if (alive.current) setError((reason as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal(); void refresh();
    return () => { alive.current = false; element?.close(); previous?.focus(); };
  }, []);
  const items = data?.items.filter(item => item.category === category && item.path.toLocaleLowerCase().includes(query.toLocaleLowerCase())) ?? [];
  const selectable = items.filter(item => !item.blocked);
  const selectedItems = data?.items.filter(item => selected.has(item.id) && !item.blocked) ?? [];
  const selectedVisible = items.filter(item => selected.has(item.id)).length;
  const allSelected = selectable.length > 0 && selectable.every(item => selected.has(item.id));
  const hiddenCount = selectedItems.length - selectedVisible;
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = selectedVisible > 0 && !allSelected;
  }, [selectedVisible, allSelected]);
  function toggleAll() {
    setSelected(previous => {
      const next = new Set(previous);
      for (const item of selectable) {
        if (allSelected) next.delete(item.id);
        else if (next.size < selectionLimit) next.add(item.id);
      }
      return next;
    });
  }
  function toggle(id: string) {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else if (next.size < selectionLimit) next.add(id);
      return next;
    });
  }
  return <dialog ref={dialog} className="project-dialog media-manager" aria-labelledby={heading}
    onCancel={event => { event.preventDefault(); if (!confirmation) onClose(); }}>
    <h2 id={heading}>管理影片檔案</h2>
    <p>包含已刪專案留下的影片。原片仍被專案使用時，請先從素材庫的專案選單刪除專案，再回來清理；成品可以單獨刪除。</p>
    <div className="media-manager-tools"><label>檔案類型<select value={category} onChange={event => setCategory(event.target.value)}>
      {Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>搜尋檔名或路徑<input value={query} onChange={event => setQuery(event.target.value)} type="search" /></label>
      <button className="secondary" disabled={busy} onClick={() => void refresh()}>重新整理</button></div>
    {error && <p role="alert" className="project-dialog-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!!failures.length && <div className="project-dialog-error" role="alert"><p>{failures.length} 個檔案未完成刪除，請確認原因後重新勾選：</p>
      <ul className="media-delete-files">{failures.map(item => <li key={item.path}>{item.path}：{item.detail}</li>)}</ul></div>}
    {data?.incomplete && <p role="status">部分位置無法讀取，清單只顯示可安全管理的檔案。</p>}
    <p>{busy ? "讀取中…" : `${items.length} 個檔案 · ${formatBytes(items.reduce((total, item) => total + item.bytes, 0))}`}</p>
    <div className="media-selection-tools" role="group" aria-label="批次選取影片">
      <label><input ref={selectAll} type="checkbox" checked={allSelected} disabled={busy || !selectable.length}
        onChange={toggleAll} />全選目前可刪檔案</label>
      <span role="status">已選 {selectedItems.length} 個 · {formatBytes(selectedItems.reduce((total, item) => total + item.bytes, 0))}
        {hiddenCount > 0 && `（其中 ${hiddenCount} 個不在目前清單）`}</span>
      <button className="secondary" disabled={busy || !selected.size} onClick={() => setSelected(new Set())}>清除勾選</button>
      <button className="project-delete-button" disabled={busy || !selectedItems.length} onClick={() => setConfirmation(selectedItems)}>刪除已選（{selectedItems.length}）</button>
    </div>
    {selected.size >= selectionLimit && <p role="status">每次最多選取 {selectionLimit} 個檔案，請先處理這一批。</p>}
    <ul className="media-manager-list" aria-label="影片檔案" aria-busy={busy}>{items.map(item => <li key={item.id}>
      <input type="checkbox" className="media-file-check" aria-label={`選取檔案：${item.path}`} aria-describedby={`file-status-${item.id}`}
        checked={selected.has(item.id)} disabled={!!item.blocked || busy || !selected.has(item.id) && selected.size >= selectionLimit}
        onChange={() => toggle(item.id)} />
      <div><strong>{item.name}</strong><p className="media-manager-path">{item.path}</p><p id={`file-status-${item.id}`}>{formatBytes(item.bytes)}{item.blocked && ` · ${item.blocked}`}</p></div>
      <button className="secondary" disabled={!!item.blocked || busy} onClick={() => setConfirmation([item])} aria-label={`刪除檔案：${item.path}`}>刪除</button>
    </li>)}</ul>
    {!busy && data && !items.length && <p>沒有符合的影片檔案。</p>}
    <div className="project-dialog-actions"><button className="secondary" onClick={onClose}>關閉檔案管理</button></div>
    {confirmation && <ConfirmDeletion items={confirmation} onClose={() => setConfirmation(null)} onDeleted={result => {
      const deletedIds = new Set(result.deleted.map(item => item.id));
      for (const item of result.deleted) if (item.job_id && item.project_id) onClipRemoved(item.project_id, [item.job_id]);
      setSelected(previous => new Set([...previous].filter(id => !deletedIds.has(id))));
      const byId = new Map(confirmation.map(item => [item.id, item.path]));
      setFailures(result.failed.map(item => ({ path: byId.get(item.id) ?? item.id, detail: item.detail })));
      setConfirmation(null); setNotice(`已刪除檔案：${result.deleted.length} 個（${formatBytes(result.bytes)}）；匯入歷史已保留。`);
      onChanged(); void refresh();
    }} />}
  </dialog>;
}
