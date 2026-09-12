import { useEffect, useId, useRef, useState } from "react";
import * as ContextMenu from "@radix-ui/react-context-menu";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Copy, Film, FolderOpen, Info, LoaderCircle, MoreHorizontal, Pencil, Trash2, X } from "lucide-react";
import { active, api, time, type Job, type Project } from "./api";

type Action = "open" | "rename" | "copy" | "info" | "delete";
type Details = Project & { source?: string | null; url?: string | null; created?: number };
const actions = [
  { id: "open", label: "開啟專案", icon: FolderOpen },
  { id: "rename", label: "重新命名…", icon: Pencil },
  { id: "copy", label: "複製來源位置", icon: Copy },
  { id: "info", label: "專案資訊…", icon: Info },
  { id: "delete", label: "刪除專案…", icon: Trash2 },
] as const;

function MenuItems({ kind, project, onAction }: { kind: "context" | "dropdown"; project: Project; onAction: (action: Action) => void }) {
  const Menu = kind === "context" ? ContextMenu : DropdownMenu;
  return <>
    <Menu.Label className="project-menu-title">{project.title}</Menu.Label>
    {actions.map(({ id, label, icon: Icon }) => <span key={id}>
      {id === "delete" && <Menu.Separator className="project-menu-divider" />}
      <Menu.Item className={`project-menu-item ${id === "delete" ? "danger" : ""}`} onSelect={() => onAction(id)}>
        <Icon size={14} /><span>{label}</span>{id === "rename" && <kbd>F2</kbd>}
      </Menu.Item>
    </span>)}
  </>;
}

function ProjectEntry({ project, selected, onSelect, onAction, dialogOpen }: {
  project: Project; selected: boolean; onSelect: () => void; onAction: (action: Action) => void; dialogOpen: boolean;
}) {
  return <ContextMenu.Root>
    <ContextMenu.Trigger asChild>
      <div className={`project-entry ${selected ? "is-selected" : ""}`}>
        <button className={`project-card ${selected ? "selected" : ""}`} onClick={onSelect} title={project.title}
          aria-current={selected ? "page" : undefined}
          onKeyDown={event => { if (event.key === "F2") { event.preventDefault(); onAction("rename"); } }}>
          <span className="project-icon">{project.ready ? <Film size={18} /> : <LoaderCircle size={18} className="spin" />}</span>
          <span><strong>{project.title}</strong><small>{project.ready ? `${time(project.duration!)} · 待人工檢查` : "準備素材中"}</small></span>
        </button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild><button className="project-more" aria-label={`${project.title} 的專案選單`} title="專案選單"><MoreHorizontal size={17} /></button></DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="project-menu" align="start" side="bottom" sideOffset={6} collisionPadding={10}
              onCloseAutoFocus={event => { if (dialogOpen) event.preventDefault(); }}>
              <MenuItems kind="dropdown" project={project} onAction={onAction} />
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </ContextMenu.Trigger>
    <ContextMenu.Portal>
      <ContextMenu.Content className="project-menu" collisionPadding={10}
        onCloseAutoFocus={event => { if (dialogOpen) event.preventDefault(); }}>
        <MenuItems kind="context" project={project} onAction={onAction} />
      </ContextMenu.Content>
    </ContextMenu.Portal>
  </ContextMenu.Root>;
}

function ProjectDialog({ project, action, jobs, onClose, onRenamed, onDeleted }: {
  project: Project; action: "rename" | "info" | "delete"; jobs: Job[]; onClose: () => void;
  onRenamed: (id: string, title: string) => void; onDeleted: (id: string) => void;
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
      }
      onClose();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  const source = details?.source || details?.url;
  return <dialog ref={dialog} className="project-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={submit}>
      <div className={`project-dialog-symbol ${action === "delete" ? "danger" : ""}`}>
        {action === "delete" ? <Trash2 size={22} /> : action === "rename" ? <Pencil size={22} /> : <Info size={22} />}
      </div>
      <button type="button" className="project-dialog-close" aria-label="關閉專案視窗" disabled={busy} onClick={onClose}><X size={18} /></button>
      <h2 id={titleId}>{action === "rename" ? "重新命名專案" : action === "delete" ? "刪除專案？" : "專案資訊"}</h2>
      <p id={descriptionId}>{action === "rename" ? "取個容易辨識的名稱，方便下次繼續剪輯。" : project.title}</p>
      {action === "rename" && <label className="project-name-label">專案名稱
        <input ref={input} autoFocus value={name} onChange={event => setName(event.target.value)} maxLength={120} required disabled={busy} />
      </label>}
      {action === "delete" && <div className="project-delete-details">
        <p>此專案的草稿、候選片段與任務紀錄將被移除，無法復原。</p>
        {!!pending && <p className="project-delete-pending">會先停止 {pending} 個下載、分析或匯出任務。</p>}
        <p>原始影片與已產生的檔案會保留在磁碟上。</p>
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
        {action !== "info" && <button type="submit" className={action === "delete" ? "project-delete-button" : "primary"}
          disabled={busy || (action === "rename" && !name.trim())}>
          {busy && <LoaderCircle size={15} className="spin" />}{busy ? "處理中…" : action === "delete" ? "刪除專案" : "儲存名稱"}
        </button>}
      </div>
    </form>
  </dialog>;
}

export default function ProjectLibrary({ projects, selected, jobs, onSelect, onRenamed, onDeleted, onError }: {
  projects: Project[]; selected?: string; jobs: Job[]; onSelect: (id: string) => void;
  onRenamed: (id: string, title: string) => void; onDeleted: (id: string) => void; onError: (message: string) => void;
}) {
  const [dialog, setDialog] = useState<{ id: string; action: "rename" | "info" | "delete" } | null>(null);
  const [notice, setNotice] = useState("");
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
    <nav className="project-list" aria-label="影片專案">
      {projects.map(project => <ProjectEntry key={project.id} project={project} selected={project.id === selected}
        onSelect={() => onSelect(project.id)} onAction={action => void act(project, action)} dialogOpen={!!dialog} />)}
      {!projects.length && <p className="library-empty">你的下一場勝利，<br />就從一支影片開始。</p>}
    </nav>
    {!!notice && <div className="project-notice" role="status"><Copy size={13} />{notice}</div>}
    {dialog && focusedProject && <ProjectDialog key={`${dialog.id}:${dialog.action}`} project={focusedProject} action={dialog.action}
      jobs={jobs.filter(job => job.project_id === dialog.id)} onClose={() => setDialog(null)} onRenamed={onRenamed} onDeleted={onDeleted} />}
  </>;
}
