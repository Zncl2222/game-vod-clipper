import { useEffect, useRef, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { api } from "../../lib/api";

type Playlist = { id: string; title: string; privacy: string; count: number };
const privacyLabels: Record<string, string> = { private: "私人", unlisted: "不公開", public: "公開" };

export default function YouTubePlaylistPicker({ channelId, canWrite, disabled, value, selectedTitle, onChange, onAuthorize }: {
  channelId: string; canWrite: boolean; disabled: boolean; value: string; selectedTitle: string;
  onChange: (value: string, title: string) => void; onAuthorize: () => void;
}) {
  const [items, setItems] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(false), [loaded, setLoaded] = useState(false);
  const [next, setNext] = useState(""), [error, setError] = useState("");
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
    if (canWrite) void load();
    return () => { version.current++; };
  }, [channelId, canWrite]);

  return <div className="yt-playlist-field" aria-busy={loading}>
    <div className="yt-playlist-label"><label htmlFor="yt-playlist">加入播放清單 <span>（選填）</span></label>
      {canWrite && <button type="button" className="text-button" disabled={disabled || loading} onClick={() => void load()}>
        <RefreshCw size={14} aria-hidden="true" />重新整理播放清單</button>}</div>
    <select id="yt-playlist" value={value} disabled={disabled || !canWrite || !loaded} aria-describedby="yt-playlist-hint"
      onChange={event => onChange(event.target.value, items.find(item => item.id === event.target.value)?.title ?? "")}>
      <option value="">不加入播放清單</option>
      {value && !items.some(item => item.id === value) && <option value={value}>{selectedTitle}</option>}
      {items.map(item => <option key={item.id} value={item.id}>{item.title} · {privacyLabels[item.privacy] ?? item.privacy} · {item.count} 部</option>)}
    </select>
    <p id="yt-playlist-hint" className="yt-hint">上傳完成後加入所選清單，影片觀看權限維持上方設定。</p>
    {!canWrite && <div className="yt-playlist-access"><p>授權後即可選擇這個頻道的播放清單；也可直接上傳、不加入清單。</p>
      <button type="button" className="secondary" disabled={disabled} onClick={onAuthorize}>授權播放清單</button></div>}
    {loading && <p className="yt-hint" role="status"><LoaderCircle size={14} className="spin" aria-hidden="true" />正在讀取播放清單…</p>}
    {error && <p className="inline-error" role="alert">播放清單讀取失敗：{error}
      <button type="button" className="text-button" disabled={disabled || loading} onClick={() => void load(next)}>重試讀取播放清單</button></p>}
    {canWrite && loaded && !items.length && !next && <p className="yt-hint">這個頻道還沒有播放清單。可先到 YouTube 建立，再重新整理。</p>}
    {next && <button type="button" className="text-button" disabled={disabled || loading} onClick={() => void load(next)}>載入更多播放清單</button>}
  </div>;
}
