import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, ExternalLink, Film, Link2, LoaderCircle, RefreshCw, Upload, X, SquarePlay } from "lucide-react";
import { api, ApiError, time, type Job, type Project } from "../../lib/api";
import YouTubeImportQueue, { importIsPending, importIsWorking, type ImportRecord } from "./YouTubeImportQueue";
import YouTubePlaylistPicker from "./YouTubePlaylistPicker";
import DownloadQuality, { qualityLabel, type DownloadQualityValue } from "../media/DownloadQuality";
import { setPreferences, usePreferences } from "../../lib/preferences";
import "../../styles/youtube.css";
import YouTubeHistory, { type ImportHistory } from "./YouTubeHistory";

type Channel = { id: string; title: string };
type Watch = { enabled: boolean; auto_analyze: boolean; model: string; download_quality?: DownloadQualityValue; last_checked: number | null; error: string | null };
type UploadRecord = { id: string; export_id: string; project_id: string; channel: Channel; title: string; description: string;
  privacy: string; status: string; progress: number; error: string | null; video_id: string | null; created: number;
  playlist_id?: string | null; playlist_title?: string | null; playlist_status?: string | null; playlist_error?: string | null };
type Account = { configured: boolean; connected: boolean; channel: Channel | null; pending: boolean; error: string | null;
  reconnect_required: boolean; playlist_write_enabled?: boolean; watch: Watch; uploads: UploadRecord[]; imports?: ImportRecord[] };
type Broadcast = { id: string; title: string; duration: number; ended_at: string; privacy: string; available: boolean;
  reason: string; project_id: string | null; import_history?: ImportHistory | null };
type Model = { id: string; name: string; is_default?: boolean; input_modalities?: string[] };
export type UploadTarget = { job: Job; project: Project };
const privacyLabels: Record<string, string> = { private: "私人", unlisted: "不公開", public: "公開" };
const uploadLabels: Record<string, string> = { queued: "等待上傳", uploading: "正在上傳", processing: "影片已上傳，等 YouTube 處理完會自動完成", adding_to_playlist: "影片已上傳，正在加入播放清單", succeeded: "上傳完成", paused: "已暫停", failed: "需要重試", needs_review: "請到 YouTube 確認" };
const isWorking = (item: UploadRecord) => ["queued", "uploading", "processing", "adding_to_playlist"].includes(item.status);
const errorLinks: Record<string, { href: string; label: string }> = {
  liveStreamingNotEnabled: { href: "https://www.youtube.com/features", label: "檢查 YouTube 直播功能" },
  accessNotConfigured: { href: "https://console.cloud.google.com/apis/library/youtube.googleapis.com", label: "啟用 YouTube Data API" },
  youtubeSignupRequired: { href: "https://www.youtube.com/", label: "前往 YouTube 建立頻道" },
};

function readChatModel() {
  try { return localStorage.getItem("bosscut:chat-model") ?? ""; } catch { return ""; }
}

export default function YouTubeDialog({ onClose, onImport, target, referenceTitle }: {
  onClose: () => void; onImport: (id: string) => void; target?: UploadTarget;
  /** Game references new imports will search with; null when none, undefined while unknown. */
  referenceTitle?: string | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true), pendingAction = useRef(false), listVersion = useRef(0);
  const errorRef = useRef<HTMLDivElement>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [tab, setTab] = useState<"live" | "upload" | "history">(target ? "upload" : "live");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loginUrl, setLoginUrl] = useState("");
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listLoaded, setListLoaded] = useState(false);
  const [nextPage, setNextPage] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Map<string, Broadcast>>(new Map());
  const selectAll = useRef<HTMLInputElement>(null);
  const [models, setModels] = useState<Model[]>([]);
  // Import choices live in preferences so they stay put until the user changes them.
  const preferences = usePreferences();
  const quality = preferences.downloadQuality, autoAnalyze = preferences.importAutoAnalyze;
  const savedModel = preferences.importModel || readChatModel();
  // Fall back to the default model for this visit only; the saved choice returns once it is available again.
  const model = !models.length || models.some(item => item.id === savedModel) ? savedModel
    : (models.find(item => item.is_default) ?? models[0]).id;
  const [title, setTitle] = useState(target?.job.draft?.title?.trim() || (target ? `${target.project.title.slice(0, 85)} · 精華片段` : ""));
  const [description, setDescription] = useState(target?.job.draft ? `原片片段：${time(target.job.draft.start)}–${time(target.job.draft.victory + target.job.draft.postroll)}` : "");
  const [privacy, setPrivacy] = useState("private");
  const [audience, setAudience] = useState("");
  const [notify, setNotify] = useState(false);
  const [playlistId, setPlaylistId] = useState("");
  const [playlistTitle, setPlaylistTitle] = useState("");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState("");
  const connected = !!account?.connected && !account.reconnect_required;
  const chosenModel = models.some(item => item.id === model);
  const channelId = account?.channel?.id;
  const errorMessage = error?.message;
  const errorLink = error instanceof ApiError && error.code ? errorLinks[error.code] : undefined;
  useEffect(() => { setPlaylistId(""); setPlaylistTitle(""); }, [channelId, account?.playlist_write_enabled]);

  async function refresh() {
    const data = await api<Account>("/youtube");
    if (alive.current) setAccount(data);
    return data;
  }
  async function perform(key: string, action: () => Promise<void>) {
    if (pendingAction.current) return;
    pendingAction.current = true; setBusy(key); setError(null); setNotice("");
    try { await action(); }
    catch (reason) { if (alive.current) setError(reason as Error); }
    finally { pendingAction.current = false; if (alive.current) setBusy(""); }
  }
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal();
    void refresh().catch(reason => { if (alive.current) setError(reason); });
    return () => { alive.current = false; listVersion.current++; element?.close(); previous?.focus(); };
  }, []);
  useEffect(() => { if (errorMessage) errorRef.current?.focus(); }, [errorMessage]);
  const polling = !!account?.pending || !!account?.uploads.some(isWorking) || !!account?.imports?.some(importIsWorking);
  useEffect(() => {
    if (!polling) return;
    let disposed = false, fetching = false;
    const timer = window.setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try { const data = await api<Account>("/youtube"); if (!disposed && alive.current) setAccount(data); }
      catch (reason) { if (!disposed && alive.current) setError(reason as Error); }
      finally { fetching = false; }
    }, 2000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [polling]);
  async function loadList(token = "") {
    const version = ++listVersion.current;
    setListLoading(true); setError(null);
    try {
      const result = await api<{ items: Broadcast[]; next_page_token: string }>(`/youtube/broadcasts${token ? `?page_token=${encodeURIComponent(token)}` : ""}`);
      if (!alive.current || version !== listVersion.current) return;
      setBroadcasts(previous => token ? [...new Map([...previous, ...result.items].map(item => [item.id, item])).values()] : result.items);
      setNextPage(result.next_page_token); setListLoaded(true);
    } catch (reason) { if (alive.current && version === listVersion.current) setError(reason as Error); }
    finally { if (alive.current && version === listVersion.current) setListLoading(false); }
  }
  useEffect(() => {
    setBroadcasts([]); setListLoaded(false); setNextPage(""); listVersion.current++;
    setSelected(new Map());
    if (!connected) return;
    void loadList();
    let disposed = false;
    void api<{ models: Model[] }>("/codex/models").then(result => {
      if (disposed || !alive.current) return;
      const available = result.models.filter(item => item.input_modalities?.includes("image"));
      setModels(available);
    }).catch(() => { if (!disposed) setModels([]); });
    return () => { disposed = true; listVersion.current++; };
  }, [connected, channelId]);

  async function retryConnection() {
    await perform("refresh", async () => {
      const data = await refresh();
      // A changed/new connection triggers the effect above. An unchanged one
      // still needs a fresh list request after the user fixes YouTube settings.
      if (alive.current && connected && data.connected && !data.reconnect_required && data.channel?.id === channelId) {
        await loadList();
      }
    });
  }

  async function configure(file?: File) {
    if (!file) return;
    await perform("configure", async () => {
      if (file.size > 32_000) throw new Error("請選擇 Google 下載的 OAuth JSON，檔案需小於 32 KB。");
      let data: unknown;
      try { data = JSON.parse(await file.text()); } catch { throw new Error("設定檔不是有效的 JSON，請重新選擇 Google 下載的檔案。"); }
      await api("/youtube/config", "PUT", data);
      await refresh();
      if (alive.current) setNotice("設定完成，現在可以連接你的 Google 帳號。");
    });
  }
  function login(playlists = false) {
    if (pendingAction.current) return;
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    void perform("login", async () => {
      try {
        const result = await api<{ url: string }>(`/youtube/login${playlists ? "?playlists=true" : ""}`, "POST");
        if (popup) popup.location.replace(result.url);
        if (alive.current) setLoginUrl(result.url);
        await refresh();
      } catch (reason) { popup?.close(); throw reason; }
    });
  }
  async function importVideo(item: Broadcast) {
    if (item.project_id) { onImport(item.project_id); return; }
    await perform(item.id, async () => {
      const result = await api<{ project_id: string }>(`/youtube/broadcasts/${item.id}/import`, "POST", {
        channel_id: channelId, auto_analyze: autoAnalyze, model, download_quality: quality,
      });
      if (alive.current) onImport(result.project_id);
    });
  }
  async function importSelected() {
    const choices = [...selected.values()];
    if (!choices.length) return;
    await perform("batch", async () => {
      const result = await api<{ added: number; existing: number; items: ImportRecord[] }>("/youtube/imports", "POST", {
        channel_id: channelId, auto_analyze: autoAnalyze, model, download_quality: quality,
        videos: choices.map(item => ({ id: item.id, title: item.title })),
      });
      if (!alive.current) return;
      setAccount(previous => previous ? { ...previous, imports: result.items } : previous);
      setSelected(new Map());
      setNotice(`已加入 ${result.added} 部，會依序匯入。${result.existing ? `另有 ${result.existing} 部已匯入或排隊中。` : ""}可以關閉視窗繼續剪輯。`);
    });
  }
  async function importQueueAction(id: string, action: "cancel" | "retry") {
    await perform(id, async () => {
      const data = await api<Account>(`/youtube/imports/${id}/${action}`, "POST");
      if (alive.current) setAccount(data);
    });
  }
  async function watch(enabled: boolean) {
    await perform("watch", async () => {
      await api("/youtube/watch", "PUT", { channel_id: channelId, enabled, auto_analyze: autoAnalyze, model, download_quality: quality });
      await refresh();
      if (alive.current) setNotice(enabled ? "已開啟：接下來結束的直播會自動匯入，剪輯仍由你確認。" : "已關閉自動匯入，已建立的任務會繼續。 ");
    });
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const invalid = !title.trim() ? "請填寫影片標題。" : /[<>]/.test(title + description) ? "標題與說明不可包含 < 或 >。" :
      new TextEncoder().encode(description).length > 5000 ? "說明過長，請縮短至 5000 位元組內。" : !audience ? "請選擇這部影片是否為兒童打造。" : "";
    setFieldError(invalid);
    if (invalid) { dialog.current?.querySelector<HTMLElement>(!title.trim() ? "#yt-title" : !audience ? "#yt-audience" : "#yt-description")?.focus(); return; }
    await perform("upload", async () => {
      const result = await api<UploadRecord>(`/youtube/uploads/${target!.job.id}`, "POST", {
        channel_id: channelId, title: title.trim(), description, privacy, made_for_kids: audience === "yes", notify_subscribers: notify,
        playlist_id: playlistId || null,
      });
      if (alive.current) setUploadId(result.id);
      await refresh();
    });
  }
  const imports = account?.imports ?? [];
  const queued = new Map(imports.filter(item => item.channel.id === channelId).map(item => [item.video_id, item]));
  const visible = broadcasts.map(item => ({ ...item, project_id: item.project_id || queued.get(item.id)?.project_id || null }))
    .filter(item => item.title.toLowerCase().includes(query.toLowerCase().trim()));
  const isQueued = (id: string) => { const item = queued.get(id); return !!item && importIsPending(item); };
  const selectable = (item: Broadcast) => item.available && !item.project_id && !isQueued(item.id);
  const availableVisible = visible.filter(selectable);
  const allSelected = availableVisible.length > 0 && availableVisible.every(item => selected.has(item.id));
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = !allSelected && availableVisible.some(item => selected.has(item.id));
  }, [allSelected, availableVisible, selected]);
  useEffect(() => {
    const imported = new Set(broadcasts.filter(item => item.project_id).map(item => item.id));
    for (const item of account?.imports ?? []) {
      if (item.channel.id === channelId && (item.project_id || importIsPending(item))) imported.add(item.video_id);
    }
    setSelected(previous => [...previous.keys()].some(key => imported.has(key))
      ? new Map([...previous].filter(([key]) => !imported.has(key))) : previous);
  }, [broadcasts, account?.imports, channelId]);
  function toggleSelection(item: Broadcast) {
    setSelected(previous => {
      const next = new Map(previous);
      if (next.has(item.id)) next.delete(item.id);
      else if (next.size < 100) next.set(item.id, item);
      return next;
    });
  }
  function toggleAll() {
    setSelected(previous => {
      const next = new Map(previous);
      for (const item of availableVisible) {
        if (allSelected) next.delete(item.id);
        else if (next.size < 100) next.set(item.id, item);
      }
      return next;
    });
  }
  const existing = account?.uploads.find(item => item.id === uploadId || item.export_id === target?.job.id && item.channel.id === channelId);
  function receipt(item: UploadRecord) {
    return <article className="yt-receipt" key={item.id} aria-label={`上傳紀錄：${item.title}`}>
      <div className="yt-row"><strong>{item.title}</strong><span className="yt-badge">{privacyLabels[item.privacy]}</span></div>
      <p>{item.channel.title} · <span role="status">{uploadLabels[item.status] ?? item.status}</span></p>
      {isWorking(item) && <progress max={100} value={item.progress} aria-label="YouTube 上傳進度" />}
      {item.error && <p className="yt-record-error">{item.error}</p>}
      {item.playlist_id && <p className={item.playlist_status === "failed" ? "yt-record-error" : undefined} role="status">
        {item.playlist_status === "added" ? "已加入播放清單" : item.playlist_status === "failed" ? "影片已上傳，尚未加入播放清單" : "完成後加入播放清單"}：{item.playlist_title || item.playlist_id}
        {item.playlist_error && <span className="yt-playlist-error">{item.playlist_error}</span>}</p>}
      <div className="yt-actions">
        {item.playlist_status === "failed" && item.status === "succeeded" && <button type="button" className="secondary"
          disabled={!!busy || !connected || !!account?.pending || item.channel.id !== channelId}
          onClick={() => account?.playlist_write_enabled ? void perform(item.id, async () => {
            await api(`/youtube/uploads/${item.id}/playlist/retry`, "POST"); await refresh();
          }) : login(true)}>{account?.playlist_write_enabled ? "重試加入播放清單" : "授權播放清單"}</button>}
        {isWorking(item) && <button type="button" className="secondary" disabled={!!busy} onClick={() => void perform(item.id, async () => { await api(`/youtube/uploads/${item.id}/pause`, "POST"); await refresh(); })}>暫停上傳</button>}
        {["failed", "paused"].includes(item.status) && <button type="button" className="primary" disabled={!!busy || !connected || item.channel.id !== channelId}
          onClick={() => void perform(item.id, async () => { await api(`/youtube/uploads/${item.id}/resume`, "POST"); await refresh(); })}>繼續上傳</button>}
        {item.video_id && <a className="secondary" href={`https://www.youtube.com/watch?v=${item.video_id}`} target="_blank" rel="noreferrer">在 YouTube 查看<ExternalLink size={15} aria-hidden="true" /></a>}
        {item.status === "needs_review" && <a className="secondary" href="https://studio.youtube.com/" target="_blank" rel="noreferrer">開啟 YouTube Studio<ExternalLink size={15} aria-hidden="true" /></a>}
        {item.status === "needs_review" && !item.video_id && <button type="button" className="secondary" disabled={!!busy || !connected || item.channel.id !== channelId}
          onClick={() => void perform(item.id, async () => { await api(`/youtube/uploads/${item.id}/restart`, "POST", { confirmed_no_video: true }); await refresh(); })}>已確認未上傳，重新開始</button>}
      </div>
    </article>;
  }

  return <dialog ref={dialog} className="yt-dialog" aria-labelledby="yt-dialog-title" onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === "Escape" && !historyOpen) { event.preventDefault(); event.stopPropagation(); onClose(); } }}>
    <header className="yt-heading"><div><span className="studio-kicker">YOUR CHANNEL, YOUR CLIPS</span><h2 id="yt-dialog-title"><SquarePlay size={24} aria-hidden="true" />我的 YouTube</h2>
      <p>直播交給 AI 找片段，剪好的成品由你確認上傳。</p></div><button type="button" className="icon-button" aria-label="關閉 YouTube 視窗" onClick={onClose}><X size={22} aria-hidden="true" /></button></header>
    <div className="yt-content">
      <button type="button" className="secondary" aria-haspopup="dialog" onClick={() => setHistoryOpen(true)}>YouTube 匯入歷史</button>
      {historyOpen && <YouTubeHistory onClose={() => setHistoryOpen(false)} onOpen={onImport} />}
      {error && <div ref={errorRef} tabIndex={-1} className="inline-error yt-message" role="alert"><p>{error.message}</p>
        <div className="yt-actions">{errorLink && <a className="secondary" href={errorLink.href} target="_blank" rel="noreferrer">{errorLink.label}<ExternalLink size={15} aria-hidden="true" /></a>}
          <button type="button" className="text-button" disabled={!!busy || listLoading} onClick={() => void retryConnection()}>重新整理連線</button></div></div>}
      {notice && <p className="yt-message yt-success" role="status"><Check size={17} aria-hidden="true" />{notice}</p>}
      {!account && !error && <p className="yt-loading" role="status"><LoaderCircle className="spin" size={20} aria-hidden="true" />正在讀取 YouTube 連線…</p>}
      {account && <>
        <ol className="yt-steps" aria-label="YouTube 剪輯流程"><li aria-current={!connected ? "step" : undefined}><span>1</span>連接頻道</li><li aria-current={connected && tab === "live" ? "step" : undefined}><span>2</span>挑選直播</li><li aria-current={connected && tab !== "live" ? "step" : undefined}><span>3</span>確認後上傳</li></ol>
        {!connected ? <section className="yt-connect" aria-label="連接 YouTube 帳號">
          <div className="yt-connect-icon"><Link2 size={28} aria-hidden="true" /></div>
          <h3>{account.reconnect_required ? "重新連接你的頻道" : "把你的直播帶進工作區"}</h3>
          <p>連接後，就能直接選取自己的直播存檔，並將成品上傳到同一個頻道。</p>
          {(account.error || account.reconnect_required) && <p className="inline-error" role="alert">{account.error || "Google 授權已失效，請重新登入。"}</p>}
          {!account.configured && <div className="yt-setup"><h4>首次連接 · 設定一次即可</h4><ol>
            <li>在 <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">Google Cloud <ExternalLink size={13} aria-hidden="true" /></a> 啟用 YouTube Data API v3。</li>
            <li>設定 OAuth 同意畫面、加入自己的測試帳號，再建立「桌面應用程式」用戶端並下載 JSON。</li>
            <li><label htmlFor="yt-config">選擇剛下載的設定檔</label><input id="yt-config" type="file" accept=".json,application/json" disabled={!!busy} onChange={event => void configure(event.target.files?.[0])} /></li>
          </ol><details><summary>遠端工作區／設定說明</summary><p>以 localhost 開啟工作區可使用桌面 OAuth。使用遠端網址時，請建立「網頁應用程式」OAuth，並將下列網址加入授權重新導向 URI：</p><code>{window.location.origin}/api/youtube/callback</code><p>設定檔和登入權杖保存在執行 BossCut 的裝置，不會顯示在瀏覽器儲存空間。</p></details></div>}
          {account.configured && !account.connected && !account.pending && <details className="yt-setup"><summary>更換 Google 設定檔</summary><label htmlFor="yt-config-replace">選擇新的 OAuth JSON</label><input id="yt-config-replace" type="file" accept=".json,application/json" disabled={!!busy} onChange={event => void configure(event.target.files?.[0])} /></details>}
          {account.reconnect_required && !account.pending && <button type="button" className="text-button" disabled={!!busy} onClick={() => void perform("disconnect", async () => { await api("/youtube/disconnect", "POST"); await refresh(); })}>更換頻道或設定</button>}
          {account.pending ? <div className="yt-login-wait" role="status"><p><LoaderCircle size={18} className="spin" aria-hidden="true" />請在 Google 視窗完成授權，此處會自動更新。</p>
            {loginUrl && <a className="secondary" href={loginUrl} target="_blank" rel="noreferrer">開啟 Google 授權頁<ExternalLink size={15} aria-hidden="true" /></a>}
            <button type="button" className="text-button" disabled={!!busy} onClick={() => void perform("cancel", async () => { await api("/youtube/login/cancel", "POST"); setLoginUrl(""); await refresh(); })}>取消登入</button></div>
            : <button type="button" className="primary" disabled={!account.configured || !!busy} onClick={() => login()}>{busy === "login" ? "正在開啟 Google…" : "使用 Google 連接"}<ArrowRight size={17} aria-hidden="true" /></button>}
        </section> : <>
          <div className="yt-channel"><div><span className="yt-connected-dot" /><strong>{account.channel!.title}</strong><span>已連接</span></div>
            <details><summary>帳號選項</summary><button type="button" className="text-button" disabled={!!busy || account.uploads.some(isWorking)} onClick={() => void perform("disconnect", async () => {
              const result = await api<Account & { message: string }>("/youtube/disconnect", "POST"); if (alive.current) { setAccount(result); setNotice(result.message); }
            })}>中斷連接</button><p>先暫停上傳即可中斷；成品會保留。</p></details></div>
          {account.pending && <div className="yt-playlist-access" role="status"><p>請在 Google 視窗完成播放清單授權，此處會自動更新。請選擇同一個頻道。</p>
            {loginUrl && <a className="text-button" href={loginUrl} target="_blank" rel="noreferrer">開啟 Google 授權頁</a>}
            <button type="button" className="text-button" disabled={!!busy} onClick={() => void perform("cancel", async () => {
              await api("/youtube/login/cancel", "POST"); setLoginUrl(""); await refresh();
            })}>取消授權</button></div>}
          {!account.pending && account.error && <p className="inline-error" role="alert">{account.error}</p>}
          <div className="yt-tabs" role="tablist" aria-label="YouTube 工具" onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=tab]"));
            const current = buttons.indexOf(event.target as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
            buttons[next].click(); buttons[next].focus();
          }}>
            <button type="button" role="tab" id="yt-live-tab" aria-controls="yt-panel" tabIndex={tab === "live" ? 0 : -1} aria-selected={tab === "live"} onClick={() => setTab("live")}>直播存檔</button>
            {target && <button type="button" role="tab" id="yt-upload-tab" aria-controls="yt-panel" tabIndex={tab === "upload" ? 0 : -1} aria-selected={tab === "upload"} onClick={() => setTab("upload")}>上傳這段成品</button>}
            <button type="button" role="tab" id="yt-history-tab" aria-controls="yt-panel" tabIndex={tab === "history" ? 0 : -1} aria-selected={tab === "history"} onClick={() => setTab("history")}>上傳紀錄{account.uploads.length > 0 ? ` · ${account.uploads.length}` : ""}</button>
          </div>
          <section id="yt-panel" role="tabpanel" aria-labelledby={`yt-${tab}-tab`}>
            {tab === "live" && <>
              <YouTubeImportQueue items={imports} busy={!!busy} channelId={channelId} onOpen={onImport}
                onCancel={id => void importQueueAction(id, "cancel")} onRetry={id => void importQueueAction(id, "retry")} />
              <div className="yt-list-toolbar"><label className="sr-only" htmlFor="yt-query">搜尋直播存檔</label><input id="yt-query" type="search" placeholder="搜尋已載入的直播…" value={query} onChange={event => setQuery(event.target.value)} />
                <button type="button" className="secondary" disabled={listLoading || !!busy} onClick={() => void loadList()}><RefreshCw size={16} className={listLoading ? "spin" : ""} aria-hidden="true" />重新整理直播</button></div>
              <DownloadQuality value={quality} onChange={value => setPreferences({ downloadQuality: value })} disabled={!!busy} />
              <div className="yt-analysis-option"><label><input type="checkbox" checked={autoAnalyze} disabled={!!busy} onChange={event => setPreferences({ importAutoAnalyze: event.target.checked })} />匯入後自動找片段</label>
                {autoAnalyze && <><label className="sr-only" htmlFor="yt-model">直播分析模型</label><select id="yt-model" value={model} disabled={!!busy || !models.length} onChange={event => setPreferences({ importModel: event.target.value })}><option value="">選擇 AI 模型</option>{models.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></>}
                {autoAnalyze && !chosenModel && <p>請先在 AI 帳號設定完成連接，或取消勾選以先匯入影片。</p>}
                {autoAnalyze && referenceTitle !== undefined && <p>搜尋時參考遊戲範例：{referenceTitle ?? "未使用"}。可在頂端「遊戲範例」變更。</p>}</div>
              <div className="yt-select-toolbar"><label><input ref={selectAll} type="checkbox" checked={allSelected} disabled={!!busy || !availableVisible.length}
                onChange={toggleAll} />全選目前清單</label><span>已選 {selected.size} 部 · 每次最多 100 部</span>
                {selected.size > 0 && <button type="button" className="text-button" disabled={!!busy} onClick={() => setSelected(new Map())}>清除選取</button>}</div>
              <div className="yt-broadcasts" aria-busy={listLoading}>
                {visible.map(item => <article className="yt-broadcast" key={item.id}>
                  <label className="yt-select-video"><input type="checkbox" aria-label={`選取直播：${item.title}`} checked={selected.has(item.id)}
                    disabled={!!busy || !selectable(item) || !selected.has(item.id) && selected.size >= 100} onChange={() => toggleSelection(item)} /></label>
                  <div className="yt-video-thumb">{item.privacy !== "private" ? <img src={`https://i.ytimg.com/vi/${item.id}/mqdefault.jpg`} alt="" loading="lazy" /> : <Film size={24} aria-hidden="true" />}<span>{time(item.duration)}</span></div>
                  <div className="yt-video-copy"><h3>{item.title}</h3><p>{item.ended_at ? new Date(item.ended_at).toLocaleDateString("zh-TW") : "直播已結束"} · {privacyLabels[item.privacy] ?? "狀態待確認"}{item.project_id ? " · 已建立專案" : item.import_history ? " · 曾匯入，專案已刪除" : ""}</p>{item.reason && <p className="yt-unavailable">{item.reason}</p>}</div>
                  <button type="button" className={item.project_id ? "secondary" : "primary"} disabled={!!busy || !item.project_id && (!item.available || isQueued(item.id) || autoAnalyze && !chosenModel)} onClick={() => void importVideo(item)} aria-label={`${item.project_id ? "開啟" : "匯入"}直播：${item.title}`}>
                    {busy === item.id ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : item.project_id ? <ArrowRight size={17} aria-hidden="true" /> : <Film size={17} aria-hidden="true" />}{item.project_id ? "開啟剪輯" : isQueued(item.id) ? "已排隊" : item.import_history ? "重新匯入" : "匯入直播"}</button>
                </article>)}
                {listLoading && <p className="yt-loading" role="status">正在讀取直播存檔…</p>}
                {!listLoading && listLoaded && !visible.length && <div className="yt-empty"><Film size={30} aria-hidden="true" /><h3>{query ? "沒有符合的直播" : "還沒有已結束的直播"}</h3><p>{query ? "換個關鍵字，或清除搜尋看看。" : "直播結束並完成存檔後，按重新整理即可選取。"}</p>{query && <button type="button" className="secondary" onClick={() => setQuery("")}>清除搜尋</button>}</div>}
              </div>
              {nextPage && <button type="button" className="secondary yt-more" disabled={listLoading || !!busy} onClick={() => void loadList(nextPage)}>載入更多直播</button>}
              <details className="yt-watch"><summary>自動匯入新直播 <span>{account.watch.enabled ? "已開啟" : "未開啟"}</span></summary><p>每 10 分鐘檢查一次，只匯入開啟後結束的直播。請讓 BossCut 保持運作；剪輯仍由你確認。</p>
                {account.watch.enabled && <p>目前設定：{qualityLabel(account.watch.download_quality)} · {account.watch.auto_analyze ? `匯入後自動分析 · ${account.watch.model}` : "只匯入影片"}</p>}
                <button type="button" className="secondary" disabled={!!busy || !account.watch.enabled && autoAnalyze && !chosenModel} onClick={() => void watch(!account.watch.enabled)}>{account.watch.enabled ? "關閉自動匯入" : "使用上方設定開啟"}</button>
                {account.watch.enabled && <button type="button" className="text-button" disabled={!!busy} onClick={() => void perform("sync", async () => { await api("/youtube/sync", "POST"); await refresh(); await loadList(); })}>立即檢查</button>}
                {account.watch.last_checked && <p>上次檢查：{new Date(account.watch.last_checked * 1000).toLocaleString("zh-TW")}</p>}{account.watch.error && <p className="inline-error">{account.watch.error}</p>}</details>
            </>}
            {tab === "upload" && target && (existing ? receipt(existing) : <form id="yt-upload-form" className="yt-upload-form" onSubmit={submit} noValidate>
              <div className="yt-export-summary"><Film size={25} aria-hidden="true" /><div><strong>已確認的剪輯成品</strong><p>{time(target.job.draft!.start)}–{time(target.job.draft!.victory + target.job.draft!.postroll)} · 片長 {time(target.job.draft!.victory + target.job.draft!.postroll - target.job.draft!.start)}</p></div></div>
              <label htmlFor="yt-title">影片標題</label><input id="yt-title" value={title} maxLength={100} required disabled={!!busy} onChange={event => { setTitle(event.target.value); setFieldError(""); }} aria-describedby="yt-field-error" />
              <label htmlFor="yt-description">說明 <span>（選填）</span></label><textarea id="yt-description" rows={3} value={description} maxLength={5000} disabled={!!busy} onChange={event => { setDescription(event.target.value); setFieldError(""); }} />
              <div className="yt-form-grid"><div><label htmlFor="yt-privacy">誰可以觀看？</label><select id="yt-privacy" value={privacy} disabled={!!busy} onChange={event => setPrivacy(event.target.value)}><option value="private">私人 · 只有你能看</option><option value="unlisted">不公開 · 知道連結即可觀看</option><option value="public">公開 · 所有人都能看</option></select></div>
                <div><label htmlFor="yt-audience">這部影片是否為兒童打造？</label><select id="yt-audience" value={audience} required disabled={!!busy} aria-describedby="yt-field-error" onChange={event => { setAudience(event.target.value); setFieldError(""); }}><option value="">請選擇</option><option value="no">否，並非為兒童打造</option><option value="yes">是，專為兒童打造</option></select></div></div>
              <YouTubePlaylistPicker channelId={channelId!} canWrite={!!account.playlist_write_enabled}
                disabled={!!busy || account.pending} value={playlistId} selectedTitle={playlistTitle}
                onChange={(id, name) => { setPlaylistId(id); setPlaylistTitle(name); }} onAuthorize={() => login(true)} />
              <details><summary>更多上傳選項</summary><label className="yt-check"><input type="checkbox" checked={notify} disabled={!!busy} onChange={event => setNotify(event.target.checked)} />通知訂閱者</label></details>
              <p className="yt-hint">尚未通過 YouTube API 審核的專案，上傳會被限制為私人影片。</p>
              {fieldError && <p id="yt-field-error" role="alert" className="inline-error">{fieldError}</p>}
            </form>)}
            {tab === "history" && (account.uploads.length ? <div className="yt-history">{account.uploads.map(receipt)}</div> : <div className="yt-empty"><Upload size={30} aria-hidden="true" /><h3>還沒有上傳紀錄</h3><p>完成剪輯後，到「成品」按「上傳 YouTube」。</p></div>)}
          </section>
        </>}
      </>}
    </div>
    {connected && tab === "upload" && target && !existing ? <footer className="yt-footer yt-footer-upload"><span>上傳至 <strong>{account!.channel!.title}</strong> · {privacyLabels[privacy]}</span><div className="yt-actions">
      <button type="button" className="secondary" onClick={onClose}>取消</button>
      <button type="submit" form="yt-upload-form" className="primary" disabled={!!busy || account!.pending}>{busy === "upload" ? <LoaderCircle size={17} className="spin" aria-hidden="true" /> : <Upload size={17} aria-hidden="true" />}{busy === "upload" ? "正在建立上傳…" : "確認並上傳"}</button>
    </div></footer> : connected && tab === "live" ? <footer className="yt-footer yt-footer-batch"><span>已選 <strong>{selected.size}</strong> 部 · 依序匯入</span><div className="yt-actions">
      <button type="button" className="secondary" onClick={onClose}><ArrowLeft size={16} aria-hidden="true" />回到工作區</button>
      <button type="button" className="primary" disabled={!!busy || !selected.size || autoAnalyze && !chosenModel} onClick={() => void importSelected()}>
        {busy === "batch" ? <LoaderCircle size={17} className="spin" aria-hidden="true" /> : <Film size={17} aria-hidden="true" />}{busy === "batch" ? "正在加入佇列…" : `匯入所選（${selected.size}）`}</button>
    </div></footer> : <footer className="yt-footer"><span>原片保留在本機 · 上傳剪好的成品</span><button type="button" className="secondary" onClick={onClose}><ArrowLeft size={16} aria-hidden="true" />回到工作區</button></footer>}
  </dialog>;
}
