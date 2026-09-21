import { useState } from "react";
import { Check, ChevronDown, Download, Film, FolderOpen, Pencil, Search, Upload } from "lucide-react";
import { active, finishedClips, media, time, type Job, type Project } from "./api";

export default function FinishedClips({ project, jobs, selected, onSelect, onUpload }: {
  project: Project; jobs: Job[]; selected?: string | null; onSelect: (id: string) => void; onUpload: (job: Job) => void;
}) {
  const [query, setQuery] = useState("");
  const exports = finishedClips(project.id, jobs);
  const encoding = jobs.find(job => job.project_id === project.id && job.kind === "export" && active(job));
  const items = exports.map((job, index) => ({ job, number: index + 1 }))
    .filter(({ job, number }) => `成品 #${number} ${time(job.draft!.start)} ${time(job.draft!.victory + job.draft!.postroll)}`.includes(query.trim()));
  return <section className="finished-clips clip-drawer" aria-label="成品片段">
    <div className="clip-drawer-heading"><FolderOpen size={19} aria-hidden="true" /><h2>本專案的成品</h2><span>{exports.length} 段</span></div>
    <p className="clip-drawer-hint">點選影片直接編輯，上方可隨時回到原片。</p>
    {encoding && <p className="clip-encoding" role="status">正在匯出 · {Math.round(encoding.progress)}%</p>}
    {!!exports.length && <label className="clip-search"><Search size={15} aria-hidden="true" />
      <input aria-label="搜尋成品片段" placeholder="搜尋編號或原片時間…" value={query} onChange={event => setQuery(event.target.value)} />
    </label>}
    <div className="finished-clip-list" role="group" aria-label="成品片段清單">
      {items.map(({ job, number }) => {
        const range = job.draft!;
        const end = range.victory + range.postroll;
        const isSelected = selected === job.id;
        const thumb = project.thumbnails.reduce<Project["thumbnails"][number] | undefined>((closest, item) =>
          !closest || Math.abs(item.time - range.start) < Math.abs(closest.time - range.start) ? item : closest, undefined);
        return <article key={job.id} className={`finished-clip-card ${isSelected ? "is-selected" : ""}`}>
          <button type="button" aria-pressed={isSelected} aria-label={`編輯成品 #${number}`}
            className="finished-clip-open" onClick={() => onSelect(job.id)}>
            <span className="finished-clip-summary">
              <span className="finished-clip-thumb">{thumb ? <img src={media(project, thumb.file)} alt="" loading="lazy" /> : <Film size={24} aria-hidden="true" />}</span>
              <span className="finished-clip-copy">
                <span className="finished-clip-title"><strong>成品 #{number}</strong>
                  {isSelected ? <span className="finished-clip-status"><Check size={12} aria-hidden="true" />編輯中</span>
                    : job.edit_draft && <span className="finished-clip-status">已存草稿</span>}
                </span>
                <span className="finished-clip-meta">MP4 · 片長 {time(end - range.start)}</span>
              </span>
              <Pencil className="finished-clip-edit-icon" size={16} aria-hidden="true" />
            </span>
            {range.manually_adjusted && <span className="manual-adjustment-badge"><Pencil size={12} aria-hidden="true" />已手動調整</span>}
            <span className="finished-clip-range"><span>原片範圍</span><span>{time(range.start)} – {time(end)}</span></span>
          </button>
          <div className="finished-clip-actions">
            <a className="finished-clip-action" href={`/api/jobs/${job.id}/download`} download aria-label={`下載成品 #${number} MP4`}><Download size={16} aria-hidden="true" />下載 MP4</a>
            <button type="button" className="finished-clip-action finished-clip-action-primary" aria-label={`上傳成品 #${number} 到 YouTube`} aria-haspopup="dialog"
              onClick={() => onUpload(job)}><Upload size={16} aria-hidden="true" />上傳 YouTube</button>
          </div>
          <details className="finished-clip-details">
            <summary><FolderOpen size={14} aria-hidden="true" />檔案儲存位置<ChevronDown className="finished-clip-details-chevron" size={14} aria-hidden="true" /></summary>
            <div><p>編輯會另存新成品，原檔保留。</p><code>clips/web/{project.id}/{job.id}.mp4</code></div>
          </details>
        </article>;
      })}
    </div>
    {!exports.length && <div className="clip-empty"><FolderOpen size={28} aria-hidden="true" /><strong>這個專案還沒有成品</strong><p>完成核對與匯出後，片段會收在這裡，隨時可以接著剪。</p></div>}
    {!!exports.length && !items.length && <p className="clip-drawer-hint" role="status">找不到符合的成品，試試其他編號或時間。</p>}
  </section>;
}
