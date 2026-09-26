import { useDeferredValue, useEffect, useId, useRef, useState } from "react";
import * as ContextMenu from "@radix-ui/react-context-menu";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Copy, Eraser, FolderOpen, Info, LoaderCircle, MoreHorizontal, Pencil, Search, Trash2, X } from "lucide-react";
import { active, api, finishedClips, publishedClips, time, type Job, type Project } from "./api";

type Action = "open" | "rename" | "copy" | "info" | "clean" | "delete";
type DialogAction = "rename" | "info" | "clean" | "delete";
type Details = Project & { source?: string | null; url?: string | null; created?: number };
const actions = [
  { id: "open", label: "開啟專案", icon: FolderOpen },
  { id: "rename", label: "重新命名…", icon: Pencil },
  { id: "copy", label: "複製來源位置", icon: Copy },
  { id: "info", label: "專案資訊…", icon: Info },
  { id: "clean", label: "移除已上傳的成品…", icon: Eraser },
  { id: "delete", label: "刪除專案…", icon: Trash2 },
] as const;

function MenuItems({ kind, project, published, onAction }: {
  kind: "context" | "dropdown"; project: Project; published: number; onAction: (action: Action) => void;
}) {
  const Menu = kind === "context" ? ContextMenu : DropdownMenu;
  return <>
    <Menu.Label className="project-menu-title">{project.title}</Menu.Label>
    {actions.map(({ id, label, icon: Icon }) => <span key={id}>
      {(id === "clean" || id === "delete") && <Menu.Separator className="project-menu-divider" />}
      <Menu.Item className={`project-menu-item ${id === "clean" || id === "delete" ? "danger" : ""}`}
        disabled={id === "clean" && !published} onSelect={() => onAction(id)}>
        <Icon size={14} /><span>{label}</span>{id === "rename" && <kbd>F2</kbd>}{id === "clean" && <kbd>{published}</kbd>}
      </Menu.Item>
    </span>)}
  </>;
}

function ProjectEntry({ project, selected, onSelect, onAction, dialogOpen, jobs }: {
  project: Project; selected: boolean; onSelect: () => void; onAction: (action: Action) => void; dialogOpen: boolean; jobs: Job[];
}) {
  const running = jobs.find(active);
  const prepare = jobs.find(job => job.kind === "prepare");
  const stopped = !project.ready && !!prepare && ["failed", "cancelled", "interrupted"].includes(prepare.status);
  const clipCount = finishedClips(project.id, jobs).length;
  const exported = clipCount > 0;
  const published = publishedClips(project.id, jobs).length;
  const status = running ? ({ prepare: "準備素材中", analyze: "AI 搜尋中", export: "匯出中" }[running.kind])
    : exported ? "已有成品" : project.ready ? (project.draft?.reviewed ? "已核對" : "待核對") : stopped ? "準備失敗 · 需處理" : "尚未就緒";
  return <ContextMenu.Root>
    <ContextMenu.Trigger asChild>
      <div className={`project-entry ${selected ? "is-selected" : ""}`}>
        <button className={`project-card ${selected ? "selected" : ""}`} onClick={onSelect} title={project.title}
          aria-current={selected ? "page" : undefined}
          onKeyDown={event => { if (event.key === "F2") { event.preventDefault(); onAction("rename"); } }}>
          <span className="project-icon">{running ? <LoaderCircle size={18} className="spin" /> : <FolderOpen size={18} />}</span>
          <span><strong>{project.title}</strong><small>{project.ready ? `${time(project.duration!)} · ${clipCount} 個成品${running ? ` · ${status}` : ""}` : status}</small></span>
        </button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild><button className="project-more" aria-label={`${project.title} 的專案選單`} title="專案選單"><MoreHorizontal size={17} /></button></DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="project-menu" align="start" side="bottom" sideOffset={6} collisionPadding={10}
              onCloseAutoFocus={event => { if (dialogOpen) event.preventDefault(); }}>
              <MenuItems kind="dropdown" project={project} published={published} onAction={onAction} />
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </ContextMenu.Trigger>
    <ContextMenu.Portal>
      <ContextMenu.Content className="project-menu" collisionPadding={10}
        onCloseAutoFocus={event => { if (dialogOpen) event.preventDefault(); }}>
        <MenuItems kind="context" project={project} published={published} onAction={onAction} />
      </ContextMenu.Content>
    </ContextMenu.Portal>
  </ContextMenu.Root>;
}

function ProjectDialog({ project, action, jobs, onClose, onRenamed, onDeleted, onClipsRemoved, onNotice }: {
  project: Project; action: DialogAction; jobs: Job[]; onClose: () => void;
  onRenamed: (id: string, title: string) => void; onDeleted: (id: string) => void;
  onClipsRemoved: (projectId: string, ids: string[]) => void; onNotice: (message: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [name, setName] = useState(project.title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [details, setDetails] = useState<Details | null>(null);
  const pending = jobs.filter(active).length;
  const published = publishedClips(project.id, jobs);
  const danger = action === "delete" || action === "clean";
  useEffect(() => {
    dialog.current?.showModal();
    if (action === "rename") input.current?.select();
    else cancel.current?.focus();
  }, [action]);
  useEffect(() => {
    if (action !== "info") return;
    let disposed = false;
    api<Details>(`/projects/${project.id}`).then(value => { if (!disposed) setDetails(value); })
      .catch(reason => { if (!disposed) setError(reason.message); });
    return () => { disposed = true; };
  }, [action, project.id]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      if (action === "rename") {
        const changed = await api<Project>(`/projects/${project.id}`, "PATCH", { title: name.trim() });
        onRenamed(project.id, changed.title);
      } else if (action === "delete") {
        await api(`/projects/${project.id}`, "DELETE");
        onDeleted(project.id);
      } else if (action === "clean") {
        const result = await api<{ deleted: string[]; bytes: number }>(`/projects/${project.id}/clips/remove-published`, "POST");
        onClipsRemoved(project.id, result.deleted);
        onNotice(result.deleted.length ? `已移除 ${result.deleted.length} 個已上傳的成品，釋放 ${(result.bytes / 1e6).toFixed(1)} MB` : "沒有可移除的成品");
      }
      onClose();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  const source = details?.source || details?.url;
  return <dialog ref={dialog} className="project-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={submit}>
      <div className={`project-dialog-symbol ${danger ? "danger" : ""}`}>
        {action === "delete" ? <Trash2 size={22} /> : action === "clean" ? <Eraser size={22} /> : action === "rename" ? <Pencil size={22} /> : <Info size={22} />}
      </div>
      <button type="button" className="project-dialog-close" aria-label="關閉專案視窗" disabled={busy} onClick={onClose}><X size={18} /></button>
      <h2 id={titleId}>{{ rename: "重新命名專案", delete: "刪除專案？", clean: "移除已上傳的成品？", info: "專案資訊" }[action]}</h2>
      <p id={descriptionId}>{action === "rename" ? "取個容易辨識的名稱，方便下次繼續剪輯。" : project.title}</p>
      {action === "rename" && <label className="project-name-label">專案名稱
        <input ref={input} autoFocus value={name} onChange={event => setName(event.target.value)} maxLength={120} required disabled={busy} />
      </label>}
      {action === "delete" && <div className="project-delete-details">
        <p>此專案的草稿、候選片段與任務紀錄將被移除，無法復原。</p>
        {!!pending && <p className="project-delete-pending">會先停止 {pending} 個下載、分析或匯出任務。</p>}
        <p>原始影片與已產生的檔案會保留在磁碟上。</p>
      </div>}
      {action === "clean" && <div className="project-delete-details">
        {published.length ? <>
          <p>將刪除 {published.length} 個成品的本機 MP4 與成品紀錄，無法復原：</p>
          <ul>{published.map(job => <li key={job.id}>{job.draft!.title?.trim() || `成品 ${time(job.draft!.start)}`}
            {job.youtube_upload?.playlist_title && <> · {job.youtube_upload.playlist_title}</>}</li>)}</ul>
          <p>只包含已上傳成功且已加入播放清單（或上傳時未指定播放清單）的成品。YouTube 上的影片、原片與其他成品都會保留。</p>
        </> : <p>目前沒有已上傳並確認加入播放清單的成品。</p>}
      </div>}
      {action === "info" && <>
        <dl className="project-info-grid">
          <div><dt>狀態</dt><dd>{project.ready ? "可以剪輯" : "準備素材中"}</dd></div>
          <div><dt>片長</dt><dd>{project.duration ? time(project.duration) : "尚未取得"}</dd></div>
          <div><dt>解析度</dt><dd>{project.width && project.height ? `${project.width} × ${project.height}` : "尚未取得"}</dd></div>
          <div><dt>已完成匯出</dt><dd>{jobs.filter(job => job.kind === "export" && job.status === "succeeded").length} 支</dd></div>
        </dl>
        <div className="project-source"><span>來源位置</span><code>{source ?? (details ? "尚未取得來源" : "載入中…")}</code>
          {source && <button type="button" className="text-button" onClick={async () => {
            try { await navigator.clipboard.writeText(source); setCopied(true); }
            catch { setError("無法自動複製，請選取上方來源位置手動複製。"); }
          }}><Copy size={13} />{copied ? "已複製" : "複製來源位置"}</button>}
        </div>
      </>}
      {error && <p role="alert" className="project-dialog-error">{error}</p>}
      <div className="project-dialog-actions">
        <button ref={cancel} type="button" className="secondary" disabled={busy} onClick={onClose}>{action === "info" ? "關閉" : "取消"}</button>
        {action !== "info" && <button type="submit" className={danger ? "project-delete-button" : "primary"}
          disabled={busy || (action === "rename" && !name.trim()) || (action === "clean" && !published.length)}>
          {busy && <LoaderCircle size={15} className="spin" />}{busy ? "處理中…" : { delete: "刪除專案", clean: `移除 ${published.length} 個成品`, rename: "儲存名稱" }[action]}
        </button>}
      </div>
    </form>
  </dialog>;
}

export default function ProjectLibrary({ projects, selected, jobs, onSelect, onRenamed, onDeleted, onClipsRemoved, onError }: {
  projects: Project[]; selected?: string; jobs: Job[]; onSelect: (id: string) => void;
  onRenamed: (id: string, title: string) => void; onDeleted: (id: string) => void;
  onClipsRemoved: (projectId: string, ids: string[]) => void; onError: (message: string) => void;
}) {
  const [dialog, setDialog] = useState<{ id: string; action: DialogAction } | null>(null);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase());
  const filtered = projects.filter(project => project.title.toLocaleLowerCase().includes(deferredQuery));
  const focusedProject = projects.find(project => project.id === dialog?.id);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(""), 2500); return () => clearTimeout(timer); }, [notice]);
  async function act(project: Project, action: Action) {
    if (action === "open") { onSelect(project.id); return; }
    if (action === "copy") {
      try {
        const details = await api<Details>(`/projects/${project.id}`);
        const source = details.source || details.url;
        if (!source) throw new Error("來源尚未就緒，請稍後再試。");
        await navigator.clipboard.writeText(source);
        setNotice("已複製來源位置");
      } catch (reason) { onError((reason as Error).message); }
      return;
    }
    setDialog({ id: project.id, action });
  }
  return <>
    {!!projects.length && <div className="library-search"><Search size={15} aria-hidden="true" />
      <input aria-label="搜尋素材庫" placeholder="搜尋影片…" value={query} onChange={event => setQuery(event.target.value)} />
      {query && <button aria-label="清除素材搜尋" onClick={() => setQuery("")}><X size={14} /></button>}
    </div>}
    <nav className="project-list" aria-label="影片專案">
      {filtered.map(project => <ProjectEntry key={project.id} project={project} selected={project.id === selected} jobs={jobs.filter(job => job.project_id === project.id)}
        onSelect={() => onSelect(project.id)} onAction={action => void act(project, action)} dialogOpen={!!dialog} />)}
      {!!projects.length && !filtered.length && <p className="library-empty" role="status">找不到符合的影片。<br />試試其他名稱，或清除搜尋。</p>}
      {!projects.length && <p className="library-empty">你的下一場勝利，<br />就從一支影片開始。</p>}
    </nav>
    {!!notice && <div className="project-notice" role="status">{notice.startsWith("已複製") ? <Copy size={13} /> : <Eraser size={13} />}{notice}</div>}
    {dialog && focusedProject && <ProjectDialog key={`${dialog.id}:${dialog.action}`} project={focusedProject} action={dialog.action}
      jobs={jobs.filter(job => job.project_id === dialog.id)} onClose={() => setDialog(null)} onRenamed={onRenamed} onDeleted={onDeleted}
      onClipsRemoved={onClipsRemoved} onNotice={setNotice} />}
  </>;
}
