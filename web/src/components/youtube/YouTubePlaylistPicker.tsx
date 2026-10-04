import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Plus, RefreshCw } from "lucide-react";
import { api } from "../../lib/api";

type Playlist = { id: string; title: string; privacy: string; count: number };
const privacyLabels: Record<string, string> = { private: "私人", unlisted: "不公開", public: "公開" };
const createOption = ":create:";

export default function YouTubePlaylistPicker({ channelId, canWrite, disabled, value, selectedTitle, onChange, onAuthorize, onCreatingChange }: {
  channelId: string; canWrite: boolean; disabled: boolean; value: string; selectedTitle: string;
  onChange: (value: string, title: string) => void; onAuthorize: () => void;
  onCreatingChange: (active: boolean) => void;
}) {
  const [items, setItems] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(false), [loaded, setLoaded] = useState(false);
  const [next, setNext] = useState(""), [error, setError] = useState("");
  const [showCreator, setShowCreator] = useState(false), [creating, setCreating] = useState(false);
  const [title, setTitle] = useState(""), [privacy, setPrivacy] = useState("private");
  const [titleError, setTitleError] = useState(""), [createError, setCreateError] = useState(""), [notice, setNotice] = useState("");
  const picker = useRef<HTMLSelectElement>(null), titleInput = useRef<HTMLInputElement>(null);
  const pendingCreate = useRef(false);
  const version = useRef(0);

  async function load(token = "") {
    const request = ++version.current;
    setLoading(true); setError("");
    try {
      const result = await api<{ items: Playlist[]; next_page_token: string }>(
        `/youtube/playlists?channel_id=${encodeURIComponent(channelId)}${token ? `&page_token=${encodeURIComponent(token)}` : ""}`);
      if (request !== version.current) return;
      // Keep a chosen item visible while refreshing or paging; the server checks
      // ownership and availability again before starting an upload.
      setItems(previous => [...new Map([...(token ? previous : previous.filter(item => item.id === value)), ...result.items]
        .map(item => [item.id, item])).values()]);
      setNext(result.next_page_token); setLoaded(true);
    } catch (reason) { if (request === version.current) setError((reason as Error).message); }
    finally { if (request === version.current) setLoading(false); }
  }
  useEffect(() => {
    version.current++; setItems([]); setLoaded(false); setNext(""); setError(""); setLoading(false);
    setShowCreator(false); setCreating(false); setTitle(""); setPrivacy("private");
    setTitleError(""); setCreateError(""); setNotice(""); pendingCreate.current = false;
    onCreatingChange(false);
    if (canWrite) void load();
    return () => { version.current++; onCreatingChange(false); };
  }, [channelId, canWrite]);
  useEffect(() => { if (showCreator) titleInput.current?.focus(); }, [showCreator]);

  function openCreator() {
    setTitle(""); setPrivacy("private"); setTitleError(""); setCreateError(""); setNotice("");
    setShowCreator(true); onCreatingChange(true);
  }
  function closeCreator() {
    setShowCreator(false); onCreatingChange(false);
    window.requestAnimationFrame(() => picker.current?.focus());
  }
  async function create() {
    if (disabled || !canWrite || pendingCreate.current) return;
    const name = title.trim();
    const invalid = !name ? "請填寫播放清單名稱。" : name.length > 150 ? "播放清單名稱最多 150 個字元。" :
      [...name].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) ? "播放清單名稱不可包含控制字元。" : "";
    setTitleError(invalid); setCreateError("");
    if (invalid) { titleInput.current?.focus(); return; }
    const request = ++version.current;
    pendingCreate.current = true; setCreating(true); setLoading(false); setError("");
    try {
      const result = await api<Playlist>("/youtube/playlists", "POST", { channel_id: channelId, title: name, privacy });
      if (request !== version.current) return;
      setItems(previous => [result, ...previous.filter(item => item.id !== result.id)]);
      setLoaded(true); setError(""); onChange(result.id, result.title);
      setNotice(`已建立並選取「${result.title}」。`); closeCreator();
    } catch (reason) {
      if (request === version.current) setCreateError((reason as Error).message);
    } finally {
      if (request === version.current) { pendingCreate.current = false; setCreating(false); }
    }
  }

  return <div className="yt-playlist-field" aria-busy={loading || creating}>
    <div className="yt-playlist-label"><label htmlFor="yt-playlist">加入播放清單 <span>（選填）</span></label>
      {canWrite && <button type="button" className="text-button" disabled={disabled || loading || creating} onClick={() => void load()}>
        <RefreshCw size={14} aria-hidden="true" />重新整理播放清單</button>}</div>
    <select ref={picker} id="yt-playlist" value={value} disabled={disabled || !canWrite || loading || showCreator} aria-describedby="yt-playlist-hint"
      onChange={event => {
        if (event.target.value === createOption) { openCreator(); return; }
        setNotice(""); onChange(event.target.value, items.find(item => item.id === event.target.value)?.title ?? "");
      }}>
      <option value="">不加入播放清單</option>
      {value && !items.some(item => item.id === value) && <option value={value}>{selectedTitle}</option>}
      {items.map(item => <option key={item.id} value={item.id}>{item.title} · {privacyLabels[item.privacy] ?? item.privacy} · {item.count} 部</option>)}
      {canWrite && <option value={createOption}>＋新增播放清單</option>}
    </select>
    {showCreator && <fieldset className="yt-playlist-create" disabled={disabled || creating}
      onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (!creating) closeCreator(); }
        if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
          event.preventDefault(); event.stopPropagation(); if (!event.nativeEvent.isComposing) void create();
        }
      }}>
      <legend>新增播放清單</legend>
      <label htmlFor="yt-playlist-title">播放清單名稱 <span>（必填）</span></label>
      <input ref={titleInput} id="yt-playlist-title" value={title} maxLength={150} required
        aria-invalid={!!titleError} aria-describedby={titleError ? "yt-playlist-title-error" : undefined}
        onChange={event => { setTitle(event.target.value); setTitleError(""); setCreateError(""); }} />
      {titleError && <p id="yt-playlist-title-error" className="inline-error" role="alert">{titleError}</p>}
      <label htmlFor="yt-playlist-create-privacy">播放清單觀看權限</label>
      <select id="yt-playlist-create-privacy" value={privacy} onChange={event => setPrivacy(event.target.value)}>
        <option value="private">私人 · 只有你能看</option><option value="unlisted">不公開 · 知道連結即可觀看</option><option value="public">公開 · 所有人都能看</option>
      </select>
      <p className="yt-hint">建立後會自動選取這個清單。</p>
      {createError && <p className="inline-error" role="alert">建立播放清單失敗：{createError}</p>}
      <div className="yt-actions"><button type="button" className="secondary" onClick={closeCreator}>取消新增</button>
        <button type="button" className="primary" onClick={() => void create()}>
          {creating ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
          {creating ? "正在建立清單…" : "建立並選取"}</button></div>
    </fieldset>}
    {notice && <p className="yt-hint" role="status">{notice}</p>}
    <p id="yt-playlist-hint" className="yt-hint">上傳完成後加入所選清單，影片觀看權限維持上方設定。</p>
    {!canWrite && <div className="yt-playlist-access"><p>授權後即可選擇這個頻道的播放清單；也可直接上傳、不加入清單。</p>
      <button type="button" className="secondary" disabled={disabled} onClick={onAuthorize}>授權播放清單</button></div>}
    {loading && <p className="yt-hint" role="status"><LoaderCircle size={14} className="spin" aria-hidden="true" />正在讀取播放清單…</p>}
    {error && <p className="inline-error" role="alert">播放清單讀取失敗：{error}
      <button type="button" className="text-button" disabled={disabled || loading || creating} onClick={() => void load(next)}>重試讀取播放清單</button></p>}
    {canWrite && loaded && !items.length && !next && <p className="yt-hint">這個頻道還沒有播放清單。從上方選單選擇「＋新增播放清單」即可建立。</p>}
    {next && <button type="button" className="text-button" disabled={disabled || loading || creating} onClick={() => void load(next)}>載入更多播放清單</button>}
  </div>;
}
