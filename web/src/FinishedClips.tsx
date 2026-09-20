import { useState } from "react";
import { Download, Film, FolderOpen, Search, Upload } from "lucide-react";
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
        const thumb = project.thumbnails.reduce<Project["thumbnails"][number] | undefined>((closest, item) =>
          !closest || Math.abs(item.time - range.start) < Math.abs(closest.time - range.start) ? item : closest, undefined);
        return <article key={job.id} className={`finished-clip-card ${selected === job.id ? "is-selected" : ""}`}>
          <button type="button" aria-pressed={selected === job.id} aria-label={`編輯成品 #${number}`}
            className="finished-clip-open" onClick={() => onSelect(job.id)}>
            <span className="finished-clip-thumb">{thumb ? <img src={media(project, thumb.file)} alt="" loading="lazy" /> : <Film size={23} aria-hidden="true" />}</span>
            <span className="finished-clip-copy"><strong>成品 #{number}</strong><span>原片 {time(range.start)}–{time(range.victory + range.postroll)}</span>
              <small>片長 {time(range.victory + range.postroll - range.start)} · {selected === job.id ? "正在編輯" : job.edit_draft ? "已有儲存草稿" : "點選直接編輯"}</small></span>
          </button>
          <div className="finished-clip-actions"><span>原成品保留</span><a href={`/api/jobs/${job.id}/download`} download aria-label={`下載成品 #${number} MP4`}><Download size={14} aria-hidden="true" />下載 MP4</a>
            <button type="button" className="youtube-upload-button" aria-label={`上傳成品 #${number} 到 YouTube`} onClick={() => onUpload(job)}><Upload size={14} aria-hidden="true" />上傳 YouTube</button></div>
          <details className="export-location"><summary>檔案儲存位置</summary><code>clips/web/{project.id}/{job.id}.mp4</code></details>
        </article>;
      })}
    </div>
    {!exports.length && <div className="clip-empty"><FolderOpen size={28} aria-hidden="true" /><strong>這個專案還沒有成品</strong><p>完成核對與匯出後，片段會收在這裡，隨時可以接著剪。</p></div>}
    {!!exports.length && !items.length && <p className="clip-drawer-hint" role="status">找不到符合的成品，試試其他編號或時間。</p>}
  </section>;
}
