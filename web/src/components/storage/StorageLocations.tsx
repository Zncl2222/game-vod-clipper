import { useEffect, useId, useState } from "react";
import { api, type StorageKind, type StorageLocations as Locations } from "../../lib/api";

const KINDS: { kind: StorageKind; label: string; help: string }[] = [
  { kind: "sources", label: "原始影片", help: "本機匯入從這裡挑選，YouTube 下載也存到這裡。" },
  { kind: "exports", label: "輸出成品", help: "匯出的 MP4 與驗證紀錄。" },
  { kind: "cache", label: "預覽與暫存", help: "預覽影片、縮圖與 AI 分析畫面，長直播可能佔用數 GB。" },
];

export default function StorageLocations() {
  const id = useId();
  const [locations, setLocations] = useState<Locations | null>(null);
  const [loadError, setLoadError] = useState("");
  const [values, setValues] = useState<Partial<Record<StorageKind, string>>>({});
  const [errors, setErrors] = useState<Partial<Record<StorageKind, string>>>({});
  const [saving, setSaving] = useState<StorageKind | null>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let current = true;
    api<Locations>("/locations").then(result => { if (current) setLocations(result); })
      .catch(reason => { if (current) setLoadError((reason as Error).message); });
    return () => { current = false; };
  }, []);

  async function save(kind: StorageKind, label: string, path: string | null) {
    setSaving(kind); setNotice(""); setErrors(previous => ({ ...previous, [kind]: "" }));
    try {
      const result = await api<Locations>("/locations", "PUT", { [kind]: path });
      setLocations(result);
      setValues(previous => ({ ...previous, [kind]: undefined }));
      setNotice(`已更新「${label}」位置，之後的新檔案會存到 ${result[kind].path}`);
    } catch (reason) { setErrors(previous => ({ ...previous, [kind]: (reason as Error).message })); }
    finally { setSaving(null); }
  }

  return <fieldset className="preference-group">
    <legend>儲存位置</legend>
    <p className="preference-help">資料夾設定存在執行 BossCut 的電腦上，所有瀏覽器共用。變更只影響之後的新檔案，現有專案與成品留在原位置，照常可用。</p>
    {loadError && <p className="preference-note is-warning" role="alert">無法讀取儲存位置：{loadError}</p>}
    {!locations && !loadError && <p className="preference-note" role="status">正在讀取儲存位置…</p>}
    {locations && <div className="storage-locations">
      {KINDS.map(({ kind, label, help }) => {
        const saved = locations[kind];
        const value = values[kind] ?? saved.path;
        const changed = value.trim() !== "" && value.trim() !== saved.path;
        const field = `${id}-${kind}`;
        return <form key={kind} className="storage-location" noValidate
          onSubmit={event => { event.preventDefault(); if (changed && !saving) void save(kind, label, value.trim()); }}>
          <div className="storage-location-label"><label htmlFor={field}>{label}</label><small id={`${field}-help`}>{help}</small></div>
          <div className="storage-location-row">
            <input id={field} type="text" value={value} spellCheck={false} autoComplete="off" disabled={saving === kind}
              aria-describedby={`${field}-help${errors[kind] ? ` ${field}-error` : ""}`} aria-invalid={!!errors[kind]}
              onChange={event => { const next = event.target.value; setValues(previous => ({ ...previous, [kind]: next })); }} />
            <button type="submit" className="secondary" disabled={!changed || !!saving}>{saving === kind ? "套用中…" : "套用"}</button>
          </div>
          {saved.custom && <button type="button" className="text-button storage-location-reset" disabled={!!saving}
            onClick={() => void save(kind, label, null)}>還原預設<code>{saved.default}</code></button>}
          {errors[kind] && <p id={`${field}-error`} className="preference-note is-warning" role="alert">{errors[kind]}</p>}
        </form>;
      })}
    </div>}
    {notice && <p className="preference-note" role="status">{notice}</p>}
  </fieldset>;
}
