import { useEffect, useRef, useState } from "react";
import { ArrowRight, FolderOpen, HardDrive, LoaderCircle, RefreshCw, ShieldCheck, X, Youtube } from "lucide-react";
import { api, type Project, type Source } from "./api";
import DownloadQuality from "./DownloadQuality";
import { setPreferences, usePreferences } from "./preferences";

export default function ImportModal({ onClose, onImport, onYouTube }: { onClose: () => void; onImport: (id: string) => void; onYouTube?: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const errorSummary = useRef<HTMLParagraphElement>(null);
  const [kind, setKind] = useState<"local" | "youtube">("local");
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState("");
  const [url, setUrl] = useState("");
  // Shares the saved preference, so a choice here is still selected next time.
  const quality = usePreferences().downloadQuality;
  const [loading, setLoading] = useState(true);
  const [sourceError, setSourceError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  async function loadSources() {
    setLoading(true); setSourceError("");
    try { setSources(await api<Source[]>("/sources")); }
    catch (reason) { setSourceError((reason as Error).message); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    void loadSources();
    return () => { element?.close(); previous?.focus(); };
  }, []);
  useEffect(() => { if (error) errorSummary.current?.focus(); }, [error]);
  function chooseKind(value: "local" | "youtube") {
    setKind(value); setError(""); setFieldError("");
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    let invalid = "";
    if (kind === "local" && !source) invalid = "請先選擇一支本機影片。";
    if (kind === "youtube") {
      try {
        const parsed = new URL(url.trim());
        if (!["https:", "http:"].includes(parsed.protocol) ||
          !["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(parsed.hostname)) throw new Error();
      } catch { invalid = "請貼上完整的 YouTube 影片網址，例如 https://www.youtube.com/watch?v=…"; }
    }
    setFieldError(invalid);
    if (invalid) { dialog.current?.querySelector<HTMLElement>(kind === "local" ? "#source" : "#youtube")?.focus(); return; }
    setBusy(true); setError("");
    try {
      const result = await api<{ project: Project }>("/projects", "POST", { kind, source: kind === "local" ? source : url.trim(),
        ...(kind === "youtube" ? { download_quality: quality } : {}) });
      onImport(result.project.id);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="import-modal" aria-labelledby="import-title" aria-describedby="import-description"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={submit} noValidate aria-busy={busy}>
      <div className="modal-heading"><div className="modal-icon"><FolderOpen aria-hidden="true" size={24} /></div>
        <button type="button" className="icon-button" disabled={busy} aria-label="關閉匯入視窗" onClick={onClose}><X aria-hidden="true" size={20} /></button></div>
      <span className="studio-kicker">NEW PROJECT</span>
      <h2 id="import-title">帶入你的下一場勝利</h2>
      <p id="import-description">選擇影片來源，準備好預覽就能開始剪輯。</p>
      <div className="tabs" role="group" aria-label="影片來源">
        <button type="button" disabled={busy} className={`tab ${kind === "local" ? "active" : ""}`} aria-pressed={kind === "local"} onClick={() => chooseKind("local")}><HardDrive aria-hidden="true" size={18} />本機影片</button>
        <button type="button" disabled={busy} className={`tab ${kind === "youtube" ? "active" : ""}`} aria-pressed={kind === "youtube"} onClick={() => chooseKind("youtube")}><Youtube aria-hidden="true" size={19} />YouTube 網址</button>
      </div>
      {kind === "local" ? <>
        <div className="source-label"><label htmlFor="source">選擇影片</label><button type="button" className="text-button" disabled={loading || busy} onClick={loadSources}><RefreshCw aria-hidden="true" size={14} className={loading ? "spin" : ""} />重新整理素材</button></div>
        <select id="source" value={source} disabled={busy || loading || !!sourceError || !sources.length} aria-describedby="source-help import-field-error" aria-invalid={!!fieldError}
          onChange={event => { setSource(event.target.value); setFieldError(""); }}>
          <option value="">{loading ? "正在讀取素材…" : sources.length ? "選擇本機素材…" : "尚未找到本機影片"}</option>
          {sources.map(item => <option key={item.path} value={item.path}>{item.name} · {(item.size / 1024 / 1024).toFixed(0)} MB</option>)}
        </select>
        <p id="source-help" className="field-help">顯示 downloads/ 與 clips/ 內的影片。將錄影放入 downloads/ 後，按「重新整理素材」即可選取。</p>
        {sourceError ? <p role="alert" className="inline-error">無法載入素材：{sourceError}。請重新整理素材再試一次。</p> : !loading && !sources.length &&
          <div className="source-empty" role="status"><FolderOpen aria-hidden="true" size={22} /><div><strong>先放入一支錄影</strong><p>將影片放進 downloads/，或切換 YouTube 網址匯入。</p></div></div>}
      </> : <>
        <label htmlFor="youtube">公開影片網址</label>
        <input id="youtube" type="url" value={url} disabled={busy} placeholder="https://www.youtube.com/watch?v=…" autoComplete="off"
          aria-describedby="youtube-help import-field-error" aria-invalid={!!fieldError} onChange={event => { setUrl(event.target.value); setFieldError(""); }} />
        <p id="youtube-help" className="field-help">支援已結束的公開影片。若來源需要登入或無法下載，可以改用本機錄影。</p>
        <DownloadQuality value={quality} onChange={value => setPreferences({ downloadQuality: value })} disabled={busy} />
        {onYouTube && <button type="button" className="import-youtube-account" disabled={busy} onClick={onYouTube}><Youtube size={18} aria-hidden="true" />從我的 YouTube 選直播<ArrowRight size={16} aria-hidden="true" /></button>}
      </>}
      <p id="import-field-error" className="inline-error" role={fieldError ? "alert" : undefined}>{fieldError}</p>
      <div className="subtle-note"><ShieldCheck aria-hidden="true" size={17} /><span>原片保留在本機。匯入後可自行剪輯，或請 AI 協助尋找成功挑戰。</span></div>
      {error && <p ref={errorSummary} tabIndex={-1} role="alert" className="inline-error">{error} 請確認來源後重試。</p>}
      <div className="import-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>取消</button>
        <button className="primary" type="submit" disabled={busy || (kind === "local" && (loading || !sources.length || !!sourceError))}>
          {busy ? <LoaderCircle aria-hidden="true" size={17} className="spin" /> : <ArrowRight aria-hidden="true" size={17} />}{busy ? "建立任務中…" : "建立剪輯專案"}
        </button></div>
    </form>
  </dialog>;
}
