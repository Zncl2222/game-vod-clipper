import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, CircleCheck, Download, Film, FolderOpen, LoaderCircle, Pencil, Search, Trash2, Upload } from "lucide-react";
import { active, api, ApiError, finishedClips, media, time, type Job, type Project } from "./api";

function DeleteClipDialog({ projectId, job, name, onClose, onDeleted }: {
  projectId: string; job: Job; name: string; onClose: () => void; onDeleted: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId(), descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal();
    cancel.current?.focus();
    return () => {
      element?.close();
      requestAnimationFrame(() => (previous?.isConnected ? previous : document.getElementById("clips-tab"))?.focus({ preventScroll: true }));
    };
  }, []);
  async function remove(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      await api(`/projects/${projectId}/clips/${job.id}`, "DELETE");
      onDeleted(job.id);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) onDeleted(job.id);
      else setError((reason as Error).message);
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="project-dialog clip-delete-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={remove}>
      <div className="project-dialog-symbol danger"><Trash2 size={22} aria-hidden="true" /></div>
      <h2 id={titleId}>刪除成品？</h2>
      <div id={descriptionId}>
        <p>將刪除「{name}」的本機 MP4、成品紀錄與編輯草稿，無法復原。</p>
        <p>原片和其他成品會保留，已上傳的 YouTube 影片不受影響。</p>
      </div>
      {error && <p role="alert" className="project-dialog-error">{error}</p>}
      <div className="project-dialog-actions">
        <button ref={cancel} type="button" className="secondary" disabled={busy} onClick={onClose}>取消</button>
        <button type="submit" className="project-delete-button" disabled={busy}>
          {busy && <LoaderCircle size={15} className="spin" aria-hidden="true" />}{busy ? "刪除中…" : "刪除成品"}
        </button>
      </div>
    </form>
  </dialog>;
}

export default function FinishedClips({ project, jobs, selected, onSelect, onUpload, onDeleted }: {
  project: Project; jobs: Job[]; selected?: string | null; onSelect: (id: string) => void; onUpload: (job: Job) => void;
  onDeleted: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [removing, setRemoving] = useState<{ job: Job; name: string } | null>(null);
  const [notice, setNotice] = useState("");
  const exports = finishedClips(project.id, jobs);
  const encoding = jobs.find(job => job.project_id === project.id && job.kind === "export" && active(job));
  const items = exports.map((job, index) => ({ job, number: index + 1 }))
    .filter(({ job, number }) => `${job.draft!.title ?? ""} 成品 #${number} ${time(job.draft!.start)} ${time(job.draft!.victory + job.draft!.postroll)}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <section className="finished-clips clip-drawer" aria-label="成品片段">
    <div className="clip-drawer-heading"><FolderOpen size={19} aria-hidden="true" /><h2>本專案的成品</h2><span>{exports.length} 段</span></div>
    <p className="clip-drawer-hint">編輯可調整名稱與時間；選錯的成品可直接刪除。</p>
    {notice && <p className="clip-encoding" role="status">{notice}</p>}
    {encoding && <p className="clip-encoding" role="status">正在匯出 · {Math.round(encoding.progress)}%</p>}
    {!!exports.length && <label className="clip-search"><Search size={15} aria-hidden="true" />
      <input aria-label="搜尋成品片段" placeholder="搜尋名稱、編號或原片時間…" value={query} onChange={event => setQuery(event.target.value)} />
    </label>}
    <div className="finished-clip-list" role="group" aria-label="成品片段清單">
      {items.map(({ job, number }) => {
        const range = job.draft!;
        const name = range.title?.trim() || `成品 #${number}`;
        const end = range.victory + range.postroll;
        const isSelected = selected === job.id;
        const thumb = project.thumbnails.reduce<Project["thumbnails"][number] | undefined>((closest, item) =>
          !closest || Math.abs(item.time - range.start) < Math.abs(closest.time - range.start) ? item : closest, undefined);
        return <article key={job.id} className={`finished-clip-card ${isSelected ? "is-selected" : ""}`}>
          <button type="button" aria-pressed={isSelected} aria-label={`開啟成品 #${number}：${name}`}
            className="finished-clip-open" onClick={() => onSelect(job.id)}>
            <span className="finished-clip-summary">
              <span className="finished-clip-thumb">{thumb ? <img src={media(project, thumb.file)} alt="" loading="lazy" /> : <Film size={24} aria-hidden="true" />}</span>
              <span className="finished-clip-copy">
                <span className="finished-clip-title"><strong>{name}</strong>
                  {isSelected ? <span className="finished-clip-status"><Check size={12} aria-hidden="true" />編輯中</span>
                    : job.edit_draft && <span className="finished-clip-status">已存草稿</span>}
                </span>
                <span className="finished-clip-meta">MP4 · 片長 {time(end - range.start)}</span>
              </span>
            </span>
            {range.manually_adjusted && <span className="manual-adjustment-badge"><Pencil size={12} aria-hidden="true" />已手動調整</span>}
            {job.youtube_upload?.published && <span className="clip-published-badge"
              title={job.youtube_upload.playlist_title ? `已上傳並加入「${job.youtube_upload.playlist_title}」，可刪除本機檔案` : "已上傳 YouTube，可刪除本機檔案"}>
              <CircleCheck size={12} aria-hidden="true" />{job.youtube_upload.playlist_title ? "已上傳・已在播放清單" : "已上傳 YouTube"}・可刪除</span>}
            <span className="finished-clip-range"><span>原片範圍</span><span>{time(range.start)} – {time(end)}</span></span>
          </button>
          <div className="finished-clip-actions">
            <button type="button" className="finished-clip-action" aria-label={`編輯成品 #${number}`} onClick={() => onSelect(job.id)}>
              <Pencil size={16} aria-hidden="true" />編輯片段</button>
            <button type="button" className="finished-clip-action finished-clip-delete" aria-label={`刪除成品 #${number}`} aria-haspopup="dialog"
              onClick={() => { setNotice(""); setRemoving({ job, name }); }}><Trash2 size={16} aria-hidden="true" />刪除</button>
            <a className="finished-clip-action" href={`/api/jobs/${job.id}/download`} download aria-label={`下載成品 #${number} MP4`}><Download size={16} aria-hidden="true" />下載 MP4</a>
            <button type="button" className="finished-clip-action finished-clip-action-primary" aria-label={`上傳成品 #${number} 到 YouTube`} aria-haspopup="dialog"
              onClick={() => onUpload(job)}><Upload size={16} aria-hidden="true" />上傳 YouTube</button>
          </div>
          <details className="finished-clip-details">
            <summary><FolderOpen size={14} aria-hidden="true" />檔案儲存位置<ChevronDown className="finished-clip-details-chevron" size={14} aria-hidden="true" /></summary>
            <div><p>編輯會另存新成品，原檔保留。</p><code>{job.output_path ?? `clips/web/${project.id}/${job.id}.mp4`}</code></div>
          </details>
        </article>;
      })}
    </div>
    {!exports.length && <div className="clip-empty"><FolderOpen size={28} aria-hidden="true" /><strong>這個專案還沒有成品</strong><p>完成核對與匯出後，片段會收在這裡，隨時可以接著剪。</p></div>}
    {!!exports.length && !items.length && <p className="clip-drawer-hint" role="status">找不到符合的成品，試試其他編號或時間。</p>}
    {removing && <DeleteClipDialog projectId={project.id} {...removing} onClose={() => setRemoving(null)}
      onDeleted={id => { onDeleted(id); setRemoving(null); setNotice(`已刪除「${removing.name}」`); }} />}
  </section>;
}
