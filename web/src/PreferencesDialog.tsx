import { useEffect, useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { qualityOptions, type DownloadQualityValue } from "./DownloadQuality";
import { exportQualityOptions, setPreferences, usePreferences, type ExportQuality } from "./preferences";
import StorageLocations from "./StorageLocations";
import "./preferences.css";

function notificationState() {
  try { return "Notification" in window ? Notification.permission : "unsupported"; } catch { return "unsupported"; }
}

export default function PreferencesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const preferences = usePreferences();
  const [permission, setPermission] = useState(notificationState);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    setPermission(notificationState());
    return () => { element?.close(); previous?.focus({ preventScroll: true }); };
  }, [open]);

  function toggleNotifications(enabled: boolean) {
    setPreferences({ notifyOnExport: enabled });
    // Ask inside the click so the browser shows its prompt.
    if (enabled && permission === "default")
      void Notification.requestPermission().then(setPermission).catch(() => setPermission(notificationState()));
  }

  return <dialog ref={dialog} id="preferences" className="editor-tools-dialog preferences-dialog" aria-labelledby={`${id}-title`}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="editor-tools-heading">
      <div><h2 id={`${id}-title`}>偏好設定</h2><p>變更會自動儲存，套用到之後新增的匯入與匯出。</p></div>
      <button type="button" className="icon-button" aria-label="關閉偏好設定" onClick={onClose}><X size={20} aria-hidden="true" /></button>
    </header>
    <div className="editor-tools-content preferences-content">
      <fieldset className="preference-group">
        <legend>匯出畫質</legend>
        <p className="preference-help">成品一律保留原片解析度、幀率與色彩；差別在重新編碼時保留多少細節。上傳 YouTube 前建議使用高畫質以上。</p>
        <div className="quality-choices">
          {exportQualityOptions.map(option => <label key={option.value} className="quality-choice">
            <input type="radio" name={`${id}-export`} value={option.value} checked={preferences.exportQuality === option.value}
              onChange={() => setPreferences({ exportQuality: option.value as ExportQuality })} />
            <span><strong>{option.label}</strong><small>{option.summary}</small><em>{option.detail}</em></span>
          </label>)}
        </div>
        <p className="preference-note">只影響之後的匯出，已完成的成品不會改變。音訊一律為 AAC 192 kbps。</p>
      </fieldset>
      <fieldset className="preference-group">
        <legend>YouTube 下載畫質</legend>
        <label className="preference-row" htmlFor={`${id}-download`}>預設保留畫質
          <select id={`${id}-download`} value={preferences.downloadQuality}
            onChange={event => setPreferences({ downloadQuality: event.target.value as DownloadQualityValue })}>
            {qualityOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <p className="preference-note">YouTube 網址匯入與「我的 YouTube」匯入都會使用這個畫質；在匯入視窗改選也會更新這裡。已開啟的自動匯入沿用開啟時的設定。下載不會重新編碼，選最高可用畫質即保留 YouTube 提供的原始串流。</p>
      </fieldset>
      <StorageLocations />
      <fieldset className="preference-group">
        <legend>通知</legend>
        <label className="preference-check">
          <input type="checkbox" checked={preferences.notifyOnExport} disabled={permission === "unsupported"}
            onChange={event => toggleNotifications(event.target.checked)} />
          <span>匯出完成或失敗時通知我<small>只在 BossCut 分頁位於背景時顯示。</small></span>
        </label>
        {permission === "denied" && preferences.notifyOnExport && <p className="preference-note is-warning" role="status">
          瀏覽器已封鎖本站通知。請在網址列左側的網站設定中允許通知。</p>}
        {permission === "unsupported" && <p className="preference-note" role="status">這個瀏覽器不支援通知。</p>}
      </fieldset>
    </div>
  </dialog>;
}
