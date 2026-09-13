import { useState } from "react";
import { active, time, type Job, type Project } from "./api";

export default function FinishedClips({ project, jobs, onSeek }: {
  project: Project; jobs: Job[]; onSeek: (seconds: number) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const local = jobs.filter(j => j.project_id === project.id);
  const exports = local.filter(j => j.kind === "export" && j.status === "succeeded" && j.draft);
  const encoding = local.find(j => j.kind === "export" && active(j));
  const clip = exports.find(j => j.id === selected) ?? exports[0];
  const index = exports.findIndex(j => j.id === clip?.id);
  return <section className="finished-clips" aria-label="成品片段">
    <div className="candidate-heading"><h2>成品片段 <span>{exports.length}</span></h2>
      <span>{encoding ? `正在匯出 · ${Math.round(encoding.progress)}%` : "每支成品保留原片時間"}</span></div>
    {!!exports.length && <div className="finished-clip-list" role="group" aria-label="成品片段清單">
      {exports.map((job, i) => <button key={job.id} aria-pressed={job.id === clip?.id}
        onClick={() => { setSelected(job.id); onSeek(job.draft!.start); }}>
        <strong>成品 #{i + 1}</strong><span>{time(job.draft!.start)}–{time(job.draft!.victory + job.draft!.postroll)}</span>
      </button>)}
    </div>}
    {clip ? <section className="finished-clip-player" aria-label="成品切換播放器">
      <video key={clip.id} controls preload="metadata" src={`/api/jobs/${clip.id}/download`} aria-label={`成品預覽 #${index + 1}`} />
      <div className="finished-clip-controls">
        <label>切換成品<select aria-label="切換成品" value={clip.id} onChange={e => setSelected(e.target.value)}>
          {exports.map((j, i) => <option key={j.id} value={j.id}>#{i + 1} · {time(j.draft!.start)}–{time(j.draft!.victory + j.draft!.postroll)} · {j.draft!.origin === "agent" ? "AI" : "手動"}</option>)}
        </select></label>
        <p>原片 {time(clip.draft!.start)}–{time(clip.draft!.victory + clip.draft!.postroll)} · 收尾 {clip.draft!.postroll} 秒</p>
        <details className="export-location"><summary>檔案儲存位置</summary>
          <code>clips/web/{project.id}/{clip.id}.mp4</code>
          <p>影片已存於後端專案資料夾。按「下載 MP4」另存到這台電腦。</p>
        </details>
        <div><button disabled={index <= 0} onClick={() => setSelected(exports[index - 1].id)}>上一段</button>
          <button disabled={index >= exports.length - 1} onClick={() => setSelected(exports[index + 1].id)}>下一段</button>
          <a href={`/api/jobs/${clip.id}/download`} download>下載 MP4</a></div>
      </div>
    </section> : <p className="candidate-empty">完成剪輯後，每支成品會標示原片範圍，並可在這裡切換播放。</p>}
  </section>;
}
