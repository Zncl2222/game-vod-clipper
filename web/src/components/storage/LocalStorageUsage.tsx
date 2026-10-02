import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, HardDrive, RefreshCw } from "lucide-react";
import { api, type VideoStorage } from "../../lib/api";
import StorageManager from "./StorageManager";

function bytes(value: number) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log10(Math.max(1, value)) / 3));
  return `${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: index ? 1 : 0 }).format(value / 1000 ** index)} ${units[index]}`;
}

function validStorage(value: unknown): value is VideoStorage {
  if (!value || typeof value !== "object") return false;
  const result = value as VideoStorage;
  const nonnegative = (number: unknown) => typeof number === "number" && Number.isFinite(number) && number >= 0;
  return nonnegative(result.bytes) && nonnegative(result.files) && nonnegative(result.updated_at)
    && typeof result.incomplete === "boolean" && !!result.categories
    && (["sources", "exports", "previews"] as const).every(key =>
      nonnegative(result.categories[key]?.bytes) && nonnegative(result.categories[key]?.files));
}

export default function LocalStorageUsage({ refreshKey, onClipRemoved }: {
  refreshKey: string; onClipRemoved: (project: string, jobs: string[]) => void;
}) {
  const [manager, setManager] = useState(false);
  const [storage, setStorage] = useState<VideoStorage | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(false);
  const pending = useRef(false);

  async function refresh() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    try {
      const result = await api<unknown>("/storage");
      if (!validStorage(result)) throw new Error("影片用量格式異常");
      if (mounted.current) { setStorage(result); setFailed(false); }
    } catch { if (mounted.current) setFailed(true); }
    finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    const visibleRefresh = () => { if (!document.hidden) void refresh(); };
    const timer = window.setInterval(visibleRefresh, 30_000);
    window.addEventListener("focus", visibleRefresh);
    return () => { mounted.current = false; window.clearInterval(timer); window.removeEventListener("focus", visibleRefresh); };
  }, []);
  useEffect(() => { void refresh(); }, [refreshKey]);

  return <><details className="local-storage" aria-label="本地影片容量">
    <summary>
      <HardDrive size={18} aria-hidden="true" />
      <span><span className="local-storage-label">本地影片用量</span><strong>{storage ? bytes(storage.bytes) : failed ? "暫時無法讀取" : "計算中…"}</strong></span>
      <ChevronDown className="local-storage-chevron" size={14} aria-hidden="true" />
    </summary>
    <div className="local-storage-details">
      {storage && <dl>{([ ["sources", "原片"], ["exports", "成品"], ["previews", "預覽與暫存"] ] as const).map(([key, label]) =>
        <div key={key}><dt>{label}</dt><dd>{bytes(storage.categories[key].bytes)}</dd></div>)}</dl>}
      <p>{failed ? (storage ? "更新失敗，顯示上次計算結果。" : "無法讀取本地影片容量，請重試。")
        : storage?.incomplete ? "部分檔案無法讀取，顯示已計算的用量。" : "統計此工作區的影片檔案，每 30 秒更新。"}</p>
      <button type="button" disabled={busy} onClick={() => void refresh()} aria-label="更新影片用量"><RefreshCw size={13} aria-hidden="true" />{busy ? "更新中…" : "重新計算"}</button>
      <button type="button" aria-haspopup="dialog" onClick={() => setManager(true)}>管理影片檔案</button>
    </div>
  </details>{manager && createPortal(<StorageManager onClose={() => setManager(false)} onChanged={() => void refresh()} onClipRemoved={onClipRemoved} />, document.body)}</>;
}
