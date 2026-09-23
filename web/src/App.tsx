import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import BossReviewDock from "./BossReviewDock";
import MediaProgress from "./MediaProgress";
import FinishedClips from "./FinishedClips";
import EditorTools from "./EditorTools";
import { candidateDraftStorageKey, draftStorageKey, readCandidateDrafts, readWorkingDraft } from "./editorDrafts";
import { validSelection } from "./SelectionOverlay";
import { timelineWindow, type TimeWindow } from "./TimelineZoom";
import ClipWorkspace, { candidates } from "./ClipWorkspace";
import ChatPanel, { type EditorContext, type EditorChatHandle, type ChatHandle } from "./ChatPanel";
import ProjectLibrary from "./ProjectLibrary";
import LocalStorageUsage from "./LocalStorageUsage";
import ImportModal from "./ImportModal";
import YouTubeDialog, { type UploadTarget } from "./YouTubeDialog";
import { WelcomeScreen, WorkflowSteps, WorkspaceGuide } from "./WorkspaceGuide";
import { usePanelLayout, usePanelVisibility } from "./ResizableSidebars";
import { useWorkbenchSize } from "./ResizableWorkbench";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Clock3,
  FileJson,
  Film,
  HardDrive,
  LoaderCircle,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Play,
  Pause,
  Volume2,
  VolumeX,
  RotateCcw,
  Save,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Trophy,
  X,
  Youtube,
} from "lucide-react";
import {
  active,
  api,
  media,
  time,
  reviewCandidates,
  finishedClips,
  editableClipDraft,
  candidateExports,
  sameClipRange,
  type NumberedCandidate,
  type Draft,
  type Job,
  type Project,
  type State,
} from "./api";

export default function App() {
  const [state, setState] = useState<State>({ projects: [], jobs: [] });
  const [selected, setSelected] = useState<string | null>(
    localStorage.getItem("bosscut:selected"),
  );
  const [connected, setConnected] = useState(false);
  const [modal, setModal] = useState(false);
  const [youtubeOpen, setYoutubeOpen] = useState(false);
  const [uploadTarget, setUploadTarget] = useState<UploadTarget | undefined>();
  const [guide, setGuide] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [error, setError] = useState("");
  const { libraryOpen, chatOpen, toggleLibrary, toggleChat, openChat } = usePanelVisibility();
  const layout = usePanelLayout(chatOpen, libraryOpen);
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [editorContext, setEditorContext] = useState<EditorContext | null>(null);
  const editorChat = useRef<EditorChatHandle>(null);
  const aiChat = useRef<ChatHandle>(null);
  const deletedProjects = useRef(new Set<string>());
  const deletedClips = useRef(new Set<string>());
  useEffect(() => {
    const stream = new EventSource("/api/events");
    stream.onmessage = (event) => {
      const incoming: State = JSON.parse(event.data);
      setState({ projects: incoming.projects.filter(project => !deletedProjects.current.has(project.id)),
        jobs: incoming.jobs.filter(job => !deletedProjects.current.has(job.project_id) && !deletedClips.current.has(job.id)) });
      setConnected(true);
    };
    stream.onerror = () => setConnected(false);
    return () => stream.close();
  }, []);
  const project =
    state.projects.find((p) => p.id === selected) ?? state.projects[0];
  useEffect(() => { setPreviewExpanded(false); setToolsOpen(false); }, [project?.id]);
  useEffect(() => {
    if (!previewExpanded) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) { event.preventDefault(); setPreviewExpanded(false); }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [previewExpanded]);
  function select(id: string) {
    setSelected(id);
    localStorage.setItem("bosscut:selected", id);
  }
  function renameProject(id: string, title: string) {
    setState(previous => ({ ...previous, projects: previous.projects.map(project => project.id === id ? { ...project, title } : project) }));
  }
  function deleteProject(id: string) {
    deletedProjects.current.add(id);
    setState(previous => ({ projects: previous.projects.filter(project => project.id !== id), jobs: previous.jobs.filter(job => job.project_id !== id) }));
    if (project?.id === id) {
      const next = state.projects.find(project => project.id !== id);
      setSelected(next?.id ?? null);
      setEditorContext(null);
      if (next) localStorage.setItem("bosscut:selected", next.id);
      else localStorage.removeItem("bosscut:selected");
    }
  }
  function deleteClip(projectId: string, id: string) {
    deletedClips.current.add(id);
    setState(previous => ({ ...previous, jobs: previous.jobs.filter(job => job.id !== id) }));
    try { localStorage.removeItem(draftStorageKey(projectId, id)); }
    catch { /* The server has already removed the clip. */ }
  }
  const projectJobs = state.jobs.filter((j) => j.project_id === project?.id);
  const mediaJobs = projectJobs.filter((job) => job.kind !== "analyze");
  const mediaJobStatus = mediaJobs.some(active) ? "處理中"
    : mediaJobs.some(job => ["failed", "interrupted"].includes(job.status) && !(job.kind === "prepare" && project?.ready)) ? "需處理" : "";
  const currentDraft = editorContext?.project_id === project?.id ? editorContext?.draft : project?.draft;
  const exported = !!currentDraft && projectJobs.some(job => job.kind === "export" && job.status === "succeeded" &&
    job.draft?.start === currentDraft.start && job.draft?.victory === currentDraft.victory && job.draft?.postroll === currentDraft.postroll);
  async function action(job: Job, command: "cancel" | "retry") {
    setError("");
    try {
      await api(`/jobs/${job.id}/${command}`, "POST");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div style={layout.style} className={`app ${chatOpen ? "chat-is-open" : ""} ${!libraryOpen ? "library-is-collapsed" : ""} ${project?.ready ? "has-editor" : ""} ${previewExpanded ? "preview-is-large" : ""} ${layout.resizing ? "is-resizing" : ""}`}>
      <a className="skip-link" href="#workspace-main">跳至剪輯工作區</a>
      {layout.handles}
      <aside className="sidebar" id="project-sidebar" aria-label="素材庫側欄">
        <div className="sidebar-heading">
        <a className="brand" href="/" aria-label="BossCut 首頁">
          <span className="brand-icon">
            <Scissors size={23} />
          </span>
          <span className="brand-wordmark">BossCut<small>EDITING STUDIO</small></span>
        </a>
        <button className="library-toggle" onClick={toggleLibrary} aria-expanded={libraryOpen} aria-controls="project-sidebar"
          aria-label={libraryOpen ? "收合素材庫側欄" : "展開素材庫側欄"} title={libraryOpen ? "收合素材庫側欄" : "展開素材庫側欄"}>
          {libraryOpen ? <PanelLeftClose size={18} aria-hidden="true" /> : <PanelLeftOpen size={18} aria-hidden="true" />}
        </button>
        </div>
        <div className="workspace-tag">
          <span className="tiny-dot" />
          個人剪輯工作區
          <HardDrive size={14} />
        </div>
        <button
          className="primary import-button"
          aria-label="匯入影片" title={!libraryOpen ? "匯入影片" : undefined}
          onClick={() => setModal(true)}
        >
          <Plus size={17} />
          <span>匯入影片</span>
        </button>
        <button type="button" className="youtube-library-button" aria-label="我的 YouTube" title="我的 YouTube" aria-haspopup="dialog"
          onClick={() => { setUploadTarget(undefined); setYoutubeOpen(true); }}><Youtube size={18} aria-hidden="true" /><span>我的 YouTube</span></button>
        <div className="nav-caption">
          素材庫{" "}
          <span>{state.projects.length.toString().padStart(2, "0")}</span>
        </div>
        <ProjectLibrary projects={state.projects} selected={project?.id} jobs={state.jobs}
          onSelect={select} onRenamed={renameProject} onDeleted={deleteProject} onError={setError} />
        <div className="sidebar-bottom">
          <button className="sidebar-guide" aria-label="使用指南與快捷鍵" title={!libraryOpen ? "使用指南與快捷鍵" : undefined} onClick={() => setGuide(true)}><CircleHelp size={17} /><span>使用指南與快捷鍵</span></button>
          <LocalStorageUsage refreshKey={state.jobs.filter(job => job.kind !== "analyze").map(job => `${job.id}:${job.status}`).sort().join("|")} />
          <span className={`connection ${connected ? "online" : ""}`}>
            <span className="tiny-dot" />
            {connected ? "工作區已連線" : "正在連接本機服務…"}
          </span>
          <span className="version">BOSSCUT STUDIO / 0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <WorkflowSteps ready={!!project?.ready} exported={exported} />
          <div className="topbar-right">
            {project?.ready && <button type="button" className="topbar-tools" aria-label="專案工具" title="草稿管理、Agent 匯入與處理紀錄" aria-haspopup="dialog"
              aria-controls="editor-tools" aria-describedby={mediaJobStatus ? "tools-job-status" : undefined} onClick={() => setToolsOpen(true)}>
              <SlidersHorizontal size={16} aria-hidden="true" />專案工具
              {mediaJobStatus && <span id="tools-job-status" className="tools-job-status">{mediaJobStatus}</span>}
            </button>}
            <button className="topbar-help" onClick={() => setGuide(true)}><CircleHelp size={16} />操作指南</button>
          </div>
        </header>
        <main id="workspace-main" tabIndex={-1}>
          {project?.ready && <h1 className="sr-only">{project.title} · 剪輯工作區</h1>}
          <div className="page-title">
            <div>
              <div className="eyebrow">YOUR PERSONAL EDITING ROOM</div>
              <h1>
                你的剪輯工作區<span>。</span>
              </h1>
              <p>讓每一次勝利，都有自己的精彩片段。</p>
            </div>
          </div>
          {error && !toolsOpen && (
            <div role="alert" className="notice error">
              {error}
              <button onClick={() => setError("")} aria-label="關閉錯誤">
                <X size={16} />
              </button>
            </div>
          )}
          {!connected && (
            <div role="status" className="notice">
              正在重新連接服務。已儲存的任務會保留，連線後將恢復進度。
            </div>
          )}
          {project?.youtube_analysis_error && <div role="status" className="notice">{project.youtube_analysis_error}</div>}
          {!project ? (
            <WelcomeScreen onImport={() => setModal(true)} onGuide={() => setGuide(true)} />
          ) : project.ready ? (
            <Editor
              key={`${project.id}:${project.editor_generation ?? project.analysis_generation ?? 0}`}
              previewExpanded={previewExpanded}
              onTogglePreview={() => setPreviewExpanded(value => !value)}
              onReset={async () => {
                const result = await api<{ project: Project }>(`/projects/${project.id}/reset-analysis`, "POST");
                localStorage.removeItem(`bosscut:draft:${project.id}`);
                setState(previous => ({ projects: previous.projects.map(p => p.id === result.project.id ? result.project : p),
                  jobs: previous.jobs.filter(j => j.project_id !== result.project.id || j.kind !== "analyze") }));
              }}
              onResetProgress={async () => {
                const result = await api<{ project: Project; jobs: Job[] }>(`/projects/${project.id}/reset-analysis-progress`, "POST");
                setState(previous => ({ projects: previous.projects.map(p => p.id === result.project.id ? result.project : p),
                  jobs: [...result.jobs, ...previous.jobs.filter(j => j.project_id !== result.project.id)] }));
              }}
              project={project}
              jobs={projectJobs}
              toolsOpen={toolsOpen}
              onCloseTools={() => setToolsOpen(false)}
              toolError={error}
              onJobAction={action}
              chatRef={editorChat}
              onSearch={async () => { await aiChat.current?.search(); }}
              onRecheck={async (candidateId, start, end) => {
                if (!aiChat.current) throw new Error("AI 助理尚未就緒，請稍後再試。");
                return aiChat.current.reviewCandidate(candidateId, start, end);
              }}
              onContext={setEditorContext}
              onError={setError}
            />
          ) : (
            <div className="preparing" role="status">
              {projectJobs.some(active) ? <LoaderCircle className="spin" size={36} /> : <CircleHelp size={36} />}
              <h2>{project.title}</h2>
              <p>{projectJobs.some(active) ? "依序下載原片、製作預覽與時間軸縮圖。" : "素材尚未就緒，請查看下方處理紀錄。"}</p>
              {mediaJobs.filter(job => job.kind === "prepare" && active(job)).slice(0, 1).map(job =>
                <MediaProgress key={job.id} status={job.status} stage={job.stage} detail={job.media_progress} />)}
              <small>{projectJobs.some(active) ? "準備完成後會自動開啟剪輯。你可以先處理其他專案。" : "若工作中斷，可按「重試」接著準備影片。"}</small>
            </div>
          )}
          {!project?.ready && mediaJobs.length > 0 && <ProcessingHistory jobs={mediaJobs} ready={false} onAction={action} />}
          <footer>
            為完整的 Boss 勝利而設計。
            <span>搜尋與聊天共用 AI · 候選結果仍需人工確認</span>
          </footer>
        </main>
      </div>
      <ChatPanel
        clips={project?.ready ? <FinishedClips key={project.id} project={project} jobs={projectJobs}
          onUpload={job => { setUploadTarget({ job, project }); setYoutubeOpen(true); }}
          onDeleted={id => deleteClip(project.id, id)}
          selected={editorContext?.project_id === project.id ? editorContext.clip_id : null}
          onSelect={id => {
            editorChat.current?.loadClip(id);
            if (window.matchMedia("(max-width: 900px)").matches && chatOpen) toggleChat();
          }} /> : undefined}
        clipCount={project ? finishedClips(project.id, projectJobs).length : 0}
        jobs={projectJobs}
        searchRef={aiChat}
        onSearchError={(message) => { setError(message); openChat(); }}
        open={chatOpen}
        onToggle={toggleChat}
        context={project?.ready ? (editorContext?.project_id === project.id && (editorContext.analysis_generation ?? 0) === (project.analysis_generation ?? 0)
          ? editorContext : { project_id: project.id, title: project.title, duration: project.duration!, draft: project.draft!, analysis_generation: project.analysis_generation ?? 0 }) : null}
        onAction={(action, expected) => editorChat.current?.apply(action, expected) ?? "影片已切換，未套用操作。"}
      />
      {modal && (
        <ImportModal
          onYouTube={() => { setModal(false); setUploadTarget(undefined); setYoutubeOpen(true); }}
          onClose={() => setModal(false)}
          onImport={(id) => {
            select(id);
            setModal(false);
          }}
        />
      )}
      {guide && <WorkspaceGuide onClose={() => setGuide(false)} />}
      {youtubeOpen && <YouTubeDialog target={uploadTarget} onClose={() => setYoutubeOpen(false)}
        onImport={id => { select(id); setYoutubeOpen(false); }} />}
    </div>
  );
}

function ProcessingHistory({ jobs, ready, onAction }: {
  jobs: Job[]; ready: boolean; onAction: (job: Job, command: "cancel" | "retry") => Promise<void>;
}) {
  if (!jobs.length) return <p className="editor-tools-empty">尚無處理紀錄。</p>;
  return <details className="workspace-details jobs-details" open={jobs.some(active) || undefined}>
    <summary><Clock3 size={16} aria-hidden="true" />處理紀錄 <span>{jobs.length} 項</span></summary>
    <section className="jobs-panel">
      <div className="section-title"><Clock3 size={16} aria-hidden="true" /><h2>處理紀錄</h2><span>關閉分頁後，背景工作仍會繼續</span></div>
      {jobs.map(job => <div key={job.id} className="job-row">
        <div className={`job-symbol ${job.status === "succeeded" ? "success" : ""}`}>
          {active(job) ? <LoaderCircle size={17} className="spin" aria-hidden="true" />
            : job.status === "succeeded" ? <Check size={17} aria-hidden="true" /> : <CircleHelp size={17} aria-hidden="true" />}
        </div>
        <div className="job-info">
          <strong>{job.kind === "prepare" ? "準備預覽" : `匯出剪輯 · 版本 ${job.draft?.revision}`}</strong>
          <small>{job.error || ({ succeeded: "已完成", failed: "處理失敗", cancelled: "已取消", interrupted: "服務曾中斷，請重試" }[job.status] ?? job.stage)}</small>
          {active(job) && job.kind === "prepare" && <MediaProgress status={job.status} stage={job.stage} detail={job.media_progress} label="準備影片進度" />}
        </div>
        {active(job) && <>
          {job.kind !== "prepare" && <div className="progress-track"><div style={{ width: `${job.progress}%` }} /></div>}
          <button className="text-button" onClick={() => onAction(job, "cancel")}>取消</button>
        </>}
        {["failed", "cancelled", "interrupted"].includes(job.status) && !(job.kind === "prepare" && ready) &&
          <button className="secondary" onClick={() => onAction(job, "retry")}><RotateCcw size={14} aria-hidden="true" />重試</button>}
        {job.kind === "export" && job.status === "succeeded" &&
          <a className="secondary" href={`/api/jobs/${job.id}/download`}><ArrowDownToLine size={14} aria-hidden="true" />下載 MP4</a>}
      </div>)}
    </section>
  </details>;
}

function Editor({
  project,
  jobs,
  onError,
  chatRef,
  onContext,
  onSearch,
  onRecheck,
  onReset,
  onResetProgress,
  previewExpanded,
  onTogglePreview,
  toolsOpen,
  onCloseTools,
  toolError,
  onJobAction,
}: {
  project: Project;
  jobs: Job[];
  onError: (message: string) => void;
  chatRef: Ref<EditorChatHandle>;
  onSearch: () => Promise<void>;
  onRecheck: (candidateId: string, start: number, end: number) => Promise<string>;
  onReset: () => Promise<void>;
  onResetProgress: () => Promise<void>;
  previewExpanded: boolean;
  toolsOpen: boolean;
  onCloseTools: () => void;
  toolError: string;
  onJobAction: (job: Job, command: "cancel" | "retry") => Promise<void>;
  onTogglePreview: () => void;
  onContext: (context: EditorContext) => void;
}) {
  const duration = project.duration!;
  const [draft, setDraft] = useState<Draft>(() => readWorkingDraft(project.id, null, project.draft!));
  const workingDraft = useRef(draft);
  workingDraft.current = draft;
  const candidateCacheKey = candidateDraftStorageKey(project.id, project.editor_generation ?? project.analysis_generation ?? 0);
  const candidateDrafts = useRef<Map<string, Draft> | null>(null);
  if (!candidateDrafts.current) candidateDrafts.current = readCandidateDrafts(candidateCacheKey);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [editingExportId, setEditingExportId] = useState<string | null>(null);
  const selectionGeneration = useRef(0);
  const editorIdentity = useRef({ clipId: editingExportId, generation: 0 });
  editorIdentity.current = { clipId: editingExportId, generation: selectionGeneration.current };
  const finished = finishedClips(project.id, jobs);
  const liveClipIds = useRef(new Set<string>());
  liveClipIds.current = new Set(finished.map(job => job.id));
  const currentRangeExported = finished.some(job => sameClipRange(job.draft!, draft));
  const draftCandidate = reviewCandidates(project, jobs).find(candidate => candidate.id === draft.candidate_id);
  const candidatePreviouslyExported = !!draftCandidate && candidateExports(project.id, draftCandidate, jobs).length > 0;
  const editingExport = finished.find(job => job.id === editingExportId);
  const savedDrafts = useRef(new Map<string | null, Draft>());
  const serverBaseline = editingExport ? editableClipDraft(editingExport) : project.draft!;
  const acknowledged = savedDrafts.current.get(editingExportId);
  const baseline = acknowledged && acknowledged.revision > serverBaseline.revision ? acknowledged : serverBaseline;
  type Snapshot = { draft: Draft; view: TimeWindow; current: number; selectedClip: string | null };
  const snapshots = useRef(new Map<string | null, Snapshot>());
  const pendingSave = useRef<{ clipId: string | null; revision: number } | null>(null);
  const [timelineView, setTimelineView] = useState<TimeWindow>(() => validSelection(draft, duration)
    ? timelineWindow(draft.start - 5, draft.victory + draft.postroll - draft.start + 10, duration)
    : { from: 0, to: duration });
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const initialSourceTime = useRef(validSelection(draft, duration) ? draft.start : 0);
  const [selectedClip, setSelectedClip] = useState<string | null>(() => draft.origin === "agent"
    ? candidates(project, jobs).find(j => j.result!.start === draft.start && j.result!.victory === draft.victory && j.result!.postroll === draft.postroll)?.id ?? null : null);
  const selectedSegment = draftCandidate?.id ?? null;
  const seenCandidates = useRef(new Set<string>());
  const candidateBaseline = useRef<string | null>(!draft.reviewed && draft.revision === 0 && JSON.stringify(draft) === JSON.stringify(project.draft) ? JSON.stringify(draft) : null);
  const [current, setCurrent] = useState(0);
  const [busy, setBusy] = useState(false);
  const [resetting, setResetting] = useState(false);
  const resetPending = useRef(false);
  async function reset(progressOnly: boolean) {
    if (resetPending.current) return;
    resetPending.current = true;
    setResetting(true);
    onError("");
    try { await (progressOnly ? onResetProgress() : onReset()); }
    catch (e) { onError((e as Error).message); }
    finally { resetPending.current = false; setResetting(false); }
  }
  const [savedMessage, setSavedMessage] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const previewPanel = useRef<HTMLElement>(null);
  const workbenchSize = useWorkbenchSize(previewPanel, previewExpanded);
  useEffect(() => {
    if (previewExpanded) previewPanel.current?.scrollIntoView({ block: "start" });
  }, [previewExpanded]);
  const stopAt = useRef<number | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const [aiFeedback, setAiFeedback] = useState<{ text: string; fields: string[]; id: number } | null>(null);
  const feedbackSequence = useRef(0);
  useEffect(() => {
    if (!aiFeedback) return;
    const timer = window.setTimeout(() => setAiFeedback(null), 4000);
    return () => window.clearTimeout(timer);
  }, [aiFeedback]);
  function markAI(text: string, fields: string[]) {
    setAiFeedback({ text, fields, id: ++feedbackSequence.current });
  }
  const end = draft.victory + draft.postroll;
  const valid =
    [draft.start, draft.victory, draft.postroll].every(Number.isFinite) &&
    draft.start >= 0 &&
    draft.start < draft.victory &&
    draft.postroll >= 5 &&
    draft.postroll <= 10 &&
    end <= duration;
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  useEffect(() => {
    if (editingExportId && !editingExport) return;
    try {
      localStorage.setItem(draftStorageKey(project.id, editingExportId), JSON.stringify(draft));
      if (!editingExportId && draft.candidate_id) {
        candidateDrafts.current!.set(draft.candidate_id, draft);
        localStorage.setItem(candidateCacheKey, JSON.stringify(Object.fromEntries(candidateDrafts.current!)));
      }
    }
    catch { onError("無法暫存瀏覽器草稿；離開前請按「儲存草稿」。"); }
  }, [draft, project.id, editingExportId, editingExport, candidateCacheKey, onError]);
  useEffect(() => {
    onContext({ project_id: project.id, title: project.title, duration, draft, clip_id: editingExportId,
      selection_generation: selectionGeneration.current, analysis_generation: project.analysis_generation ?? 0 });
  }, [draft, editingExportId, project.id, project.title, project.analysis_generation, duration, onContext]);
  useImperativeHandle(chatRef, () => ({
    loadClip: id => {
      switchWorkspace(id);
      focusTiming();
    },
    apply(action, expected) {
      if (resetPending.current || resetting) return "影片正在重置，未套用舊操作。";
      if ((expected.analysis_generation ?? 0) !== (project.analysis_generation ?? 0)) return "影片已重置，未套用舊操作。";
      if (expected.project_id !== project.id) return "影片已切換，未套用操作。";
      if ((expected.clip_id ?? null) !== editingExportId || (expected.selection_generation ?? 0) !== selectionGeneration.current)
        return "編輯對象已切換，未套用舊操作。請重新送出需求。";
      if (action.kind === "select_candidate") {
        const segment = reviewCandidates(project, jobs).find(c => c.id === action.candidate_id);
        if (!segment) return "候選片段已不存在，請重新選取。";
        const selectedDraft = selectSegment(segment)!;
        markAI(`正在編輯片段 #${segment.number}，預覽與匯出使用同一區間`, ["seek"]);
        return `已選取 #${segment.number} · ${time(selectedDraft.start)}–${time(selectedDraft.victory + selectedDraft.postroll)}`;
      }
      if (action.kind === "seek") {
        if (action.seconds === null || !Number.isFinite(action.seconds) || action.seconds < 0 || action.seconds > duration) return "時間無效，未跳轉。";
        seek(action.seconds);
        markAI(`AI 已將預覽定位到 ${time(action.seconds)}`, ["seek"]);
        return `已跳到 ${time(action.seconds)}`;
      }
      if (JSON.stringify(expected.draft) !== JSON.stringify(draft)) return "你已修改草稿，未覆蓋新的設定。請再送出一次需求。";
      if (action.kind === "export") {
        if (!valid) return "請先修正剪輯時間範圍，再要求匯出。";
        if (busy || jobs.some(j => j.kind === "export" && active(j))) return "影片正在儲存或匯出，請等候完成。";
        void save(true);
        return "正在儲存草稿並提交 FFmpeg 剪輯，結果會顯示在成品區。";
      }
      const { start, victory, postroll } = action;
      if (start === null || victory === null || postroll === null ||
          ![start, victory, postroll].every(Number.isFinite) || start < 0 || start >= victory ||
          postroll < 5 || postroll > 10 || victory + postroll > duration) return "時間範圍無效，未修改草稿。";
      change({ start, victory, postroll, origin: "agent" });
      markAI("AI 已更新剪輯設定，變動欄位已標示", [
        ...(start !== draft.start ? ["start"] : []),
        ...(victory !== draft.victory ? ["victory"] : []),
        ...(postroll !== draft.postroll ? ["postroll"] : []),
      ]);
      return `已更新草稿 · ${time(start)} → ${time(victory)} · 收尾 ${postroll} 秒`;
    },
  }));
  function switchWorkspace(clipId: string | null) {
    if (clipId === editingExportId || resetPending.current) return;
    const job = clipId ? finished.find(item => item.id === clipId) : null;
    if (clipId && !job) { onError("這個成品已不存在，請重新整理清單。"); return; }
    snapshots.current.set(editingExportId, { draft, view: timelineView, current, selectedClip });
    const base = job ? editableClipDraft(job) : project.draft!;
    const known = savedDrafts.current.get(clipId);
    const nextBase = known && known.revision > base.revision ? known : base;
    const previous = snapshots.current.get(clipId);
    // SSE may announce our saved revision before the PUT response arrives. Keep
    // newer local edits on that in-flight base until the response rebases them.
    const ownSavePending = pendingSave.current?.clipId === clipId && pendingSave.current?.revision === previous?.draft.revision;
    const restored = previous && (previous.draft.revision === nextBase.revision || ownSavePending) ? previous : null;
    const nextDraft = restored?.draft ?? readWorkingDraft(project.id, clipId, nextBase);
    video.current?.pause();
    selectionGeneration.current++;
    editorIdentity.current = { clipId, generation: selectionGeneration.current };
    setEditingExportId(clipId);
    setDraft(nextDraft);
    setSelectedClip(restored?.selectedClip ?? null);
    setTimelineView(restored?.view ?? (validSelection(nextDraft, duration)
      ? timelineWindow(nextDraft.start - 5, nextDraft.victory + nextDraft.postroll - nextDraft.start + 10, duration)
      : { from: 0, to: duration }));
    setSavedMessage("");
    setAiFeedback(null);
    candidateBaseline.current = null;
    seek(restored?.current ?? (validSelection(nextDraft, duration) ? nextDraft.start : 0));
    previewPanel.current?.scrollIntoView({ block: "start" });
    previewPanel.current?.querySelector<HTMLButtonElement>(".source-workspace-button")?.focus({ preventScroll: true });
  }
  useEffect(() => {
    // Deletion can arrive through our dialog or a different browser tab.
    const cached = new Set([editingExportId, ...snapshots.current.keys(), ...savedDrafts.current.keys()]);
    if (editingExportId && !liveClipIds.current.has(editingExportId)) switchWorkspace(null);
    for (const id of cached) {
      if (!id || liveClipIds.current.has(id)) continue;
      snapshots.current.delete(id);
      savedDrafts.current.delete(id);
      try { localStorage.removeItem(draftStorageKey(project.id, id)); } catch { /* Cache only. */ }
    }
  }, [jobs, editingExportId]);
  function change(values: Partial<Draft>) {
    setAiFeedback(null);
    setSelectedClip(null);
    setDraft(d => {
      const timingChanged = (["start", "victory", "postroll"] as const).some(key => values[key] !== undefined && values[key] !== d[key]);
      return { ...d,
        ...(timingChanged && values.origin === undefined ? { origin: "manual" as const, manually_adjusted: true } : {}),
        ...values, reviewed: false };
    });
    setSavedMessage("");
  }
  function candidateSaved(id: string, previousRevision: number, revision: number) {
    const rebase = (value: Draft) => value.candidate_id === id && (value.candidate_revision ?? 0) === previousRevision
      ? { ...value, candidate_revision: revision } : value;
    setDraft(rebase);
    for (const [key, cached] of candidateDrafts.current!) candidateDrafts.current!.set(key, rebase(cached));
    try { localStorage.setItem(candidateCacheKey, JSON.stringify(Object.fromEntries(candidateDrafts.current!))); }
    catch { /* Saved candidate corrections remain available on the server. */ }
    for (const [key, snapshot] of snapshots.current) snapshots.current.set(key, { ...snapshot, draft: rebase(snapshot.draft) });
    // A range save may finish while a different source/clip workspace is open.
    for (const target of [null, ...finished.map(job => job.id)]) {
      try {
        const key = draftStorageKey(project.id, target);
        const saved = JSON.parse(localStorage.getItem(key) ?? "null");
        if (saved) localStorage.setItem(key, JSON.stringify(rebase(saved)));
      } catch { /* The candidate correction itself is already saved on the server. */ }
    }
  }
  function seek(seconds: number) {
    if (video.current) {
      stopAt.current = null;
      initialSourceTime.current = Math.max(0, Math.min(duration, seconds));
      video.current.currentTime = initialSourceTime.current;
      setCurrent(video.current.currentTime);
    }
  }
  function playRange(start: number, finish: number) {
    seek(start);
    stopAt.current = finish;
    void video.current
      ?.play()
      .catch(() => onError("無法播放預覽，請確認瀏覽器支援此影片。"));
  }
  useEffect(() => {
    function keydown(e: KeyboardEvent) {
      if (
        (e.target as HTMLElement).closest(
          "input, textarea, select, button, a, video, [contenteditable], [role=slider], [role=separator], [role=group], dialog",
        ) ||
        document.querySelector("dialog[open]") ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      )
        return;
      if (e.key.toLowerCase() === "i") {
        change({ start: current });
        e.preventDefault();
      }
      if (e.key.toLowerCase() === "o") {
        change({ victory: current });
        e.preventDefault();
      }
      if (e.key === "ArrowLeft") {
        seek(current - 1 / 30);
        e.preventDefault();
      }
      if (e.key === "ArrowRight") {
        seek(current + 1 / 30);
        e.preventDefault();
      }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [current, duration]);
  async function save(exportNow = false) {
    if (pendingSave.current) return;
    if (exportNow && !valid) { onError("請先修正剪輯時間範圍，再匯出。"); return; }
    const target = editingExportId, generation = selectionGeneration.current, submitted = draft;
    pendingSave.current = { clipId: target, revision: submitted.revision };
    setBusy(true);
    onError("");
    try {
      const saved = await api<Draft>(
        target ? `/projects/${project.id}/clips/${target}/draft` : `/projects/${project.id}/draft`,
        "PUT",
        submitted,
      );
      if (!mounted.current || (target && !liveClipIds.current.has(target))) return;
      savedDrafts.current.set(target, saved);
      // The response belongs to the submitted workspace, even if the user switched.
      const snapshot = snapshots.current.get(target);
      if (snapshot) snapshots.current.set(target, { ...snapshot, draft: {
        ...snapshot.draft, revision: saved.revision,
      } });
      if (editorIdentity.current.clipId === target) {
        setDraft(currentDraft => ({ ...currentDraft, revision: saved.revision }));
        setSavedMessage(JSON.stringify(submitted) === JSON.stringify(workingDraft.current) ? "草稿已儲存" : "草稿已儲存，仍有新的修改");
      }
      try {
        const pending = JSON.parse(localStorage.getItem(draftStorageKey(project.id, target)) ?? "null");
        localStorage.setItem(draftStorageKey(project.id, target), JSON.stringify({ ...(pending ?? saved), revision: saved.revision }));
      } catch { /* The acknowledged server draft remains available on reload. */ }
      if (exportNow) {
        await api(`/projects/${project.id}/exports`, "POST", {
          revision: saved.revision,
          ...(target ? { source_job_id: target } : {}),
        });
        if (editorIdentity.current.clipId === target && editorIdentity.current.generation === generation)
          setSavedMessage(target ? "已加入匯出佇列，原成品保留" : "已加入匯出佇列");
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      pendingSave.current = null;
      setBusy(false);
    }
  }
  async function importAgent(file?: File) {
    if (!file) return;
    onError("");
    const expected = { ...editorIdentity.current }, expectedDraft = workingDraft.current;
    try {
      if (file.size > 100_000) throw new Error("Agent JSON 檔案過大。");
      const data = JSON.parse(await file.text());
      if (!mounted.current) return;
      if (editorIdentity.current.clipId !== expected.clipId || editorIdentity.current.generation !== expected.generation ||
          JSON.stringify(workingDraft.current) !== JSON.stringify(expectedDraft))
        throw new Error("編輯對象或草稿已變更，未套用匯入結果。請在要調整的片段重新匯入。");
      if (data.project_id !== project.id)
        throw new Error("Agent 結果的 project_id 與目前影片不符。");
      const candidate = data.draft ?? data;
      if (
        ![candidate.start, candidate.victory, candidate.postroll].every(
          (x) => typeof x === "number" && Number.isFinite(x),
        ) ||
        candidate.start < 0 ||
        candidate.start >= candidate.victory ||
        candidate.postroll < 5 ||
        candidate.postroll > 10 ||
        candidate.victory + candidate.postroll > duration
      )
        throw new Error("Agent 時間點無效或超出來源範圍。");
      change({
        start: candidate.start,
        victory: candidate.victory,
        postroll: candidate.postroll,
        origin: "agent",
        candidate_id: null, candidate_revision: null, manually_adjusted: false,
      });
      seek(candidate.start);
    } catch (e) {
      if (mounted.current) onError((e as Error).message);
    }
  }
  const searchingId = jobs.find(j => j.kind === "analyze" && active(j))?.id;
  useEffect(() => {
    if (searchingId) candidateBaseline.current = editingExportId || draft.reviewed || draft.candidate_id ? null : JSON.stringify(draft);
  }, [searchingId]);
  function selectClip(job: Job, navigate = true) {
    if (!candidates(project, [job]).length) return;
    const result = job.result!;
    const candidate = reviewCandidates(project, jobs).find(segment => segment.victory !== null && sameClipRange(
      { start: segment.start, victory: segment.victory, postroll: segment.postroll ?? 8 },
      { start: result.start!, victory: result.victory!, postroll: result.postroll }));
    if (navigate && candidate) {
      selectSegment(candidate);
      setSelectedClip(job.id);
      return;
    }
    if (navigate) video.current?.pause();
    setDraft(d => ({ ...d, start: result.start!, victory: result.victory!, postroll: result.postroll, origin: "agent", reviewed: false,
      candidate_id: candidate?.id ?? null, candidate_revision: candidate?.manual_edit?.revision ?? null, manually_adjusted: false }));
    setSelectedClip(job.id);
    setSavedMessage("");
    setTimelineView(timelineWindow(result.start! - 5, result.victory! + result.postroll - result.start! + 10, duration));
    if (navigate) seek(result.start!);
    markAI("候選片段已放入時間軸，可直接預覽與拖曳調整。", ["start", "victory", "postroll"]);
  }
  function selectSegment(segment: NumberedCandidate, seconds?: number) {
    if (resetPending.current) return;
    video.current?.pause();
    if (!editingExportId && draft.candidate_id === segment.id) {
      seek(seconds ?? draft.start);
      return draft;
    }
    if (!editingExportId && draft.candidate_id) candidateDrafts.current!.set(draft.candidate_id, draft);
    // Candidate selection always edits the source workspace. Keep any completed
    // clip's independent draft intact so returning to it restores its changes.
    const sourceBase = savedDrafts.current.get(null) ?? project.draft!;
    const sourceDraft = editingExportId
      ? snapshots.current.get(null)?.draft ?? readWorkingDraft(project.id, null, sourceBase) : draft;
    if (editingExportId) snapshots.current.set(editingExportId, { draft, view: timelineView, current, selectedClip });
    const postroll = Math.max(5, Math.min(10, segment.postroll ?? 8));
    const victory = segment.victory ?? Math.min(duration - postroll, Math.max(segment.start + 1 / 30, segment.end - postroll));
    const cached = candidateDrafts.current!.get(segment.id);
    const next: Draft = cached && (cached.candidate_revision ?? 0) >= (segment.manual_edit?.revision ?? 0)
      ? { ...cached, revision: sourceDraft.revision }
      : { ...sourceDraft, title: "", start: segment.start, victory, postroll, reviewed: false,
        candidate_id: segment.id, candidate_revision: segment.manual_edit?.revision ?? 0,
        manually_adjusted: !!segment.manual_edit, origin: segment.manual_edit || segment.verification !== "verified" ? "manual" : "agent" };
    selectionGeneration.current++;
    editorIdentity.current = { clipId: null, generation: selectionGeneration.current };
    setEditingExportId(null);
    setDraft(next);
    setSelectedClip(null);
    setSavedMessage("");
    setAiFeedback(null);
    candidateBaseline.current = null;
    // Keep the time scale stable during pointer scrubbing.
    if (seconds === undefined) setTimelineView(timelineWindow(next.start - 5, next.victory + next.postroll - next.start + 10, duration));
    seek(seconds ?? next.start);
    return next;
  }
  function focusTiming() {
    const input = previewPanel.current?.querySelector<HTMLInputElement>(".workbench-time-field input");
    input?.scrollIntoView({ block: "nearest" });
    input?.focus({ preventScroll: true });
  }
  useEffect(() => {
    const candidate = candidates(project, jobs)[0];
    if (!candidate || seenCandidates.current.has(candidate.id)) return;
    seenCandidates.current.add(candidate.id);
    if (!editingExportId && candidateBaseline.current === JSON.stringify(draft) && !draft.reviewed) selectClip(candidate, false);
  }, [jobs, project.id]);
  return (
    <>
      {aiFeedback && <div className="ai-editor-feedback" role="status" key={aiFeedback.id}><Sparkles size={14} />{aiFeedback.text}</div>}
      <div className="editor-grid">
        <section ref={previewPanel} style={workbenchSize.style} aria-label="影片與選取範圍" className={`preview-panel ${workbenchSize.dragging ? "is-adjusting-height" : ""} ${aiFeedback?.fields.includes("seek") ? "ai-target" : ""}`}>
          <div className="preview-stage">
          <div className="panel-heading">
            <span>
              <Film size={16} />
              <strong title={project.title}>{project.title}</strong>
            </span>
            <div className="preview-display-controls">
              <button type="button" className="source-workspace-button" aria-pressed={!editingExportId}
                onClick={() => switchWorkspace(null)} title="回到原片，繼續使用完整編輯台">
                <ArrowLeft size={15} aria-hidden="true" />{editingExportId ? "回到原片" : "原片編輯台"}
              </button>
              {project.width && project.height && <span className="resolution">{project.width} × {project.height}</span>}
              <button type="button" className="preview-expand" aria-pressed={previewExpanded}
                onClick={onTogglePreview} title={previewExpanded ? "退出劇院模式（Esc）" : "放大影片並保留剪輯拉條"}>
                {previewExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                {previewExpanded ? "返回工作區" : "劇院模式"}
              </button>
            </div>
          </div>
          <div className="video-wrap">
            <video
              ref={video}
              src={media(project, "preview.mp4")}
              poster={
                project.thumbnails[0]
                  ? media(project, project.thumbnails[0].file)
                  : undefined
              }
              aria-label="原片預覽"
              muted={muted}
              onLoadedMetadata={() => seek(initialSourceTime.current)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onEnded={() => setPlaying(false)}
              playsInline
              preload="metadata"
              onError={() => onError("預覽影片載入失敗，請確認服務仍在運作。")}
              onTimeUpdate={() => {
                const v = video.current!;
                setCurrent(v.currentTime);
                if (
                  stopAt.current !== null &&
                  v.currentTime >= stopAt.current
                ) {
                  v.pause();
                  stopAt.current = null;
                }
              }}
            />
            <span className="preview-badge">{editingExport ? `成品 #${finished.findIndex(job => job.id === editingExport.id) + 1} · 編輯中` : draftCandidate ? `片段 #${draftCandidate.number} · 編輯中` : "原片 · 編輯中"}</span>
          </div>
          <div className="transport">
            <button className="icon-button transport-play" aria-label={playing ? "暫停原片" : "播放原片"}
              onClick={() => { if (playing) video.current?.pause(); else void video.current?.play().catch(() => onError("無法播放預覽，請確認瀏覽器支援此影片。")); }}>
              {playing ? <Pause size={17} /> : <Play size={17} />}
            </button>
            <div className="frame-controls">
              <button
                className="icon-button"
                onClick={() => seek(current - 1 / 30)}
                title="前一預覽格"
                aria-label="前一預覽格"
              >
                <ArrowLeft size={16} />
              </button>
              <span className="mono">
                {time(current, true)} <em>/ {time(duration)}</em>
              </span>
              <button
                className="icon-button"
                onClick={() => seek(current + 1 / 30)}
                title="後一預覽格"
                aria-label="後一預覽格"
              >
                <ArrowRight size={16} />
              </button>
            </div>
            {!previewExpanded && <button className="text-button precision-button" onClick={() => {
              previewPanel.current?.querySelector<HTMLInputElement>("#start")?.focus();
            }}><SlidersHorizontal size={14} />精確調整</button>}
            <button className="icon-button" aria-label={muted ? "開啟原片聲音" : "將原片靜音"} onClick={() => setMuted(value => !value)}>
              {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </button>
            <select
              aria-label="播放速度"
              defaultValue="1"
              onChange={(e) => {
                if (video.current)
                  video.current.playbackRate = Number(e.target.value);
              }}
            >
              <option value="0.5">0.5×</option>
              <option value="1">1×</option>
              <option value="1.5">1.5×</option>
              <option value="2">2×</option>
            </select>
          </div>
          </div>
          {workbenchSize.divider}
          <div id="clip-workbench-panel" className="preview-editing" role="region" aria-label="剪輯與候選檢查區" tabIndex={0}>
          <ClipWorkspace project={project} jobs={jobs} draft={draft} selected={selectedClip}
            view={timelineView} onViewChange={setTimelineView}
            selectedSegment={selectedSegment} onSelectSegment={selectSegment} onError={onError}
            onRecheck={onRecheck}
            candidateActions={<BossReviewDock jobs={jobs} segmentCount={reviewCandidates(project, jobs).length} onSearch={onSearch} onReset={() => reset(false)} resetting={resetting} onError={onError} />}
            onCandidateSaved={candidateSaved}
            onSelect={selectClip} onChange={change} onPlay={playRange} onSeek={seek} current={current}
            onResetProgress={() => reset(true)} resetting={resetting} highlightedFields={aiFeedback?.fields} />
          </div>
          <div className="compact-export" role="group" aria-label="片段命名與匯出">
            <div className="export-review">
            <div className="clip-name-field">
              <label htmlFor="clip-title">片段名稱 <span>選填</span></label>
              <input id="clip-title" type="text" maxLength={100} value={draft.title ?? ""}
                placeholder="例如：瑪蓮妮亞・無傷通關" aria-describedby="clip-title-help"
                onChange={event => change({ title: event.target.value })} />
              <small id="clip-title-help" className="sr-only">隨草稿儲存，匯出後用於成品名稱與下載檔名。</small>
            </div>
            <div className="active-edit-target" role="group" aria-label="目前編輯與匯出區間">
              <strong>{editingExport ? `正在編輯成品 #${finished.findIndex(job => job.id === editingExport.id) + 1}`
                : draftCandidate ? `正在編輯 #${draftCandidate.number}` : "目前剪輯"}</strong>
              <span>{time(draft.start, true)} → {time(end, true)}</span>
              <button type="button" onClick={focusTiming}>調整時間</button>
            </div>
            </div>
            <div className="export-action-group">
            <button
              className="primary export-button"
              aria-describedby="export-help"
              disabled={
                !valid ||
                busy ||
                jobs.some((j) => j.kind === "export" && active(j))
              }
              onClick={() => save(true)}
            >
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <ArrowDownToLine size={16} />
              )}
              {busy ? "正在提交…" : jobs.some(j => j.kind === "export" && active(j)) ? "正在匯出…" : editingExportId ? "另存新成品" : "匯出 MP4"}
            </button>
            <p className="export-help" id="export-help">{!valid ? "請先修正剪輯時間範圍" : editingExportId ? "保留原成品，不覆寫原檔" : "MP4 影片 · 含原片音訊"}</p>
            </div>
            <div className="export-status-row">
              <div className="draft-status" role="status"><span className={`tiny-dot ${currentRangeExported ? "is-exported" : ""}`} />
                {savedMessage || (dirty ? "修改已暫存於此瀏覽器" : "草稿已儲存")}
              </div>
              <span className="draft-duration">片長 {time(Math.max(0, end - draft.start))} · 收尾 {draft.postroll} 秒</span>
              <p className={`export-range-status ${currentRangeExported ? "is-exported" : ""}`} role="status">
                {currentRangeExported ? <><Check size={14} aria-hidden="true" />目前區間已匯出</>
                  : candidatePreviouslyExported ? "此片段曾匯出，目前區間有修改" : "匯出會自動儲存目前區間"}
              </p>
            </div>
          </div>
        </section>
      </div>
      <EditorTools open={toolsOpen} onClose={onCloseTools} error={toolError} onClearError={() => onError("")}>
        <details className="editor-settings workspace-details" open><summary>手動操作與草稿管理</summary>
          <div className="quick-actions">
            <button
              onClick={() =>
                change({ start: Math.round(current * 1000) / 1000 })
              }
            >
              <Scissors size={14} />
              設為開始<kbd>I</kbd>
            </button>
            <button
              onClick={() =>
                change({ victory: Math.round(current * 1000) / 1000 })
              }
            >
              <Trophy size={14} />
              設為勝利<kbd>O</kbd>
            </button>
            <span />
            <button
              disabled={!valid}
              onClick={() => { onCloseTools(); playRange(draft.start, Math.min(end, draft.start + 10)); }}
            >
              播放開頭
            </button>
            <button
              disabled={!valid}
              onClick={() => { onCloseTools(); playRange(Math.max(draft.start, end - 10), end); }}
            >
              播放結尾
            </button>
          </div>

          <div className="timeline-footer">
            <span>
              <span className="tiny-dot" />
              {savedMessage ||
                (dirty ? "修改已暫存於此瀏覽器" : "草稿已儲存")}{" "}
              · 版本 {draft.revision}
            </span>
            <button
              className="text-button"
              onClick={() => {
                setDraft(baseline);
                setSavedMessage("已還原儲存版本");
              }}
            >
              <RotateCcw size={14} />
              還原
            </button>
            <button
              className="secondary"
              disabled={busy || !valid}
              onClick={() => save()}
            >
              <Save size={14} />
              儲存草稿
            </button>
          </div>
        </details>
      <details className="workspace-details">
      <summary><FileJson size={16} /> 進階 Agent 匯入／匯出</summary>
      <div className="agent-strip">
        <div className="agent-icon">
          <Sparkles size={20} />
        </div>
        <div>
          <strong>讓你原本的 Agent 一起剪輯</strong>
          <p>取得任務資料，依 Skill 分析後匯入時間點。匯入後仍需檢查影片。</p>
        </div>
        <a
          className="text-button"
          href={`/api/projects/${project.id}/review-packet`}
          target="_blank"
          rel="noreferrer"
        >
          <FileJson size={15} />
          任務 JSON
        </a>
        <button
          className="secondary"
          onClick={() => importInput.current?.click()}
        >
          <Plus size={14} />
          匯入 Agent 結果
        </button>
        <input
          ref={importInput}
          hidden
          type="file"
          accept=".json,application/json"
          aria-label="匯入 Agent JSON"
          onChange={(e) => {
            void importAgent(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      </details>
      <ProcessingHistory jobs={jobs.filter(job => job.kind !== "analyze")} ready={project.ready} onAction={onJobAction} />
      </EditorTools>
    </>
  );
}
