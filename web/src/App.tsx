import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import BossReviewDock from "./BossReviewDock";
import ClipWorkspace, { candidates } from "./ClipWorkspace";
import ChatPanel, { type EditorContext, type EditorChatHandle, type ChatHandle } from "./ChatPanel";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clapperboard,
  Clock3,
  FileJson,
  Film,
  FolderOpen,
  HardDrive,
  LoaderCircle,
  Plus,
  RotateCcw,
  Save,
  Scissors,
  ShieldCheck,
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
  type NumberedCandidate,
  type Draft,
  type Job,
  type Project,
  type Source,
  type State,
} from "./api";

export default function App() {
  const [state, setState] = useState<State>({ projects: [], jobs: [] });
  const [selected, setSelected] = useState<string | null>(
    localStorage.getItem("bosscut:selected"),
  );
  const [connected, setConnected] = useState(false);
  const [modal, setModal] = useState(false);
  const [error, setError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [editorContext, setEditorContext] = useState<EditorContext | null>(null);
  const editorChat = useRef<EditorChatHandle>(null);
  const aiChat = useRef<ChatHandle>(null);
  useEffect(() => {
    const stream = new EventSource("/api/events");
    stream.onmessage = (event) => {
      setState(JSON.parse(event.data));
      setConnected(true);
    };
    stream.onerror = () => setConnected(false);
    return () => stream.close();
  }, []);
  const project =
    state.projects.find((p) => p.id === selected) ?? state.projects[0];
  function select(id: string) {
    setSelected(id);
    localStorage.setItem("bosscut:selected", id);
  }
  const projectJobs = state.jobs.filter((j) => j.project_id === project?.id);
  const mediaJobs = projectJobs.filter((job) => job.kind !== "analyze");
  async function action(job: Job, command: "cancel" | "retry") {
    try {
      await api(`/jobs/${job.id}/${command}`, "POST");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className={`app ${chatOpen ? "chat-is-open" : ""} ${project?.ready ? "has-editor" : ""}`}>
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="BossCut 首頁">
          <span className="brand-icon">
            <Scissors size={23} />
          </span>
          BossCut<span className="poc">POC</span>
        </a>
        <div className="workspace-tag">
          <span className="tiny-dot" />
          個人剪輯工作區
          <HardDrive size={14} />
        </div>
        <button
          className="primary import-button"
          onClick={() => setModal(true)}
        >
          <Plus size={17} />
          匯入影片
        </button>
        <div className="nav-caption">
          素材庫{" "}
          <span>{state.projects.length.toString().padStart(2, "0")}</span>
        </div>
        <nav className="project-list" aria-label="影片專案">
          {state.projects.map((p) => (
            <button
              key={p.id}
              onClick={() => select(p.id)}
              className={`project-card ${p.id === project?.id ? "selected" : ""}`}
            >
              <span className="project-icon">
                {p.ready ? (
                  <Film size={18} />
                ) : (
                  <LoaderCircle size={18} className="spin" />
                )}
              </span>
              <span>
                <strong>{p.title}</strong>
                <small>
                  {p.ready ? `${time(p.duration!)} · 待人工檢查` : "準備素材中"}
                </small>
              </span>
            </button>
          ))}
          {!state.projects.length && (
            <p className="library-empty">
              你的下一場勝利，
              <br />
              就從一支影片開始。
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <ShieldCheck size={19} />
            <div>
              <strong>原始影片留在本機</strong>
              <p>預覽與剪輯於此裝置處理</p>
            </div>
          </div>
          <span className={`connection ${connected ? "online" : ""}`}>
            <span className="tiny-dot" />
            {connected ? "工作區已連線" : "正在連接本機服務…"}
          </span>
          <span className="version">BOSSCUT STUDIO / 0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作區
            <ChevronRight size={14} />
            <span>勝利剪輯</span>
          </div>
          <div className="topbar-right">
            <span className="local-pill">
              <HardDrive size={13} />
              LOCAL FIRST
            </span>
            <span className="avatar">YOU</span>
          </div>
        </header>
        <main>
          <div className="page-title">
            <div>
              <div className="eyebrow">MAKE THE WIN YOURS</div>
              <h1>
                每一次勝利，都值得留下<span>。</span>
              </h1>
              <p>找到成功的那一次，保留完整戰鬥與勝利時刻。</p>
            </div>
            <div className="step-indicator">
              <span className="done">1</span>匯入
              <i />
              <span className={project?.ready ? "done" : ""}>2</span>調整
              <i />
              <span>3</span>匯出
            </div>
          </div>
          {error && (
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
          {!project ? (
            <div className="empty-workspace">
              <div className="empty-art">
                <div className="film-line" />
                <div className="empty-play">
                  <Clapperboard size={42} strokeWidth={1.4} />
                </div>
                <div className="film-line" />
                <span className="win-tag">
                  <Trophy size={14} /> YOUR NEXT VICTORY
                </span>
              </div>
              <span className="eyebrow">A CLEAN CUT. A COMPLETE FIGHT.</span>
              <h2>把漫長實況，變成值得重播的一戰。</h2>
              <p>
                匯入本機影片或 YouTube 網址，
                <br />
                預覽、調整時間，再把勝利帶走。
              </p>
              <button className="primary" onClick={() => setModal(true)}>
                <Plus size={17} />
                建立第一個剪輯
              </button>
              <div className="empty-features">
                <span>
                  <Film size={16} />
                  流暢預覽
                </span>
                <span>
                  <Scissors size={16} />
                  精細調整
                </span>
                <span>
                  <ShieldCheck size={16} />
                  本機匯出
                </span>
              </div>
            </div>
          ) : project.ready ? (
            <Editor
              key={`${project.id}:${project.analysis_generation ?? 0}`}
              onReset={async () => {
                const result = await api<{ project: Project }>(`/projects/${project.id}/reset-analysis`, "POST");
                localStorage.removeItem(`bosscut:draft:${project.id}`);
                setState(previous => ({ projects: previous.projects.map(p => p.id === result.project.id ? result.project : p),
                  jobs: previous.jobs.filter(j => j.project_id !== result.project.id || j.kind !== "analyze") }));
              }}
              project={project}
              jobs={projectJobs}
              chatRef={editorChat}
              onSearch={async () => { await aiChat.current?.search(); }}
              onContext={setEditorContext}
              onError={setError}
            />
          ) : (
            <div className="preparing">
              <LoaderCircle
                className={projectJobs.some(active) ? "spin" : ""}
                size={36}
              />
              <h2>{project.title}</h2>
              <p>準備可拖曳的預覽影片與時間軸縮圖。</p>
              <small>長影片需要較多時間，可以離開此頁，稍後回來查看。</small>
            </div>
          )}
          {mediaJobs.length > 0 && (
            <details className="workspace-details jobs-details" open={mediaJobs.some(active) || undefined}>
            <summary><Clock3 size={16} /> 處理紀錄 <span>{mediaJobs.length} 項</span></summary>
            <section className="jobs-panel">
              <div className="section-title">
                <Clock3 size={16} />
                <h2>處理紀錄</h2>
                <span>關閉分頁後，背景工作仍會繼續</span>
              </div>
              {mediaJobs.map((job) => (
                <div key={job.id} className="job-row">
                  <div
                    className={`job-symbol ${job.status === "succeeded" ? "success" : ""}`}
                  >
                    {active(job) ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : job.status === "succeeded" ? (
                      <Check size={17} />
                    ) : (
                      <CircleHelp size={17} />
                    )}
                  </div>
                  <div className="job-info">
                    <strong>
                      {job.kind === "prepare"
                        ? "準備預覽"
                        : `匯出剪輯 · 版本 ${job.draft?.revision}`}
                    </strong>
                    <small>
                      {job.error ||
                        ({
                          succeeded: "已完成",
                          failed: "處理失敗",
                          cancelled: "已取消",
                          interrupted: "服務曾中斷，請重試",
                        }[job.status] ??
                          job.stage)}
                    </small>
                  </div>
                  {active(job) && (
                    <>
                      <div className={`progress-track ${job.kind === "analyze" ? "analysis-track is-running" : ""}`}>
                        <div style={job.kind === "analyze" ? undefined : { width: `${job.progress}%` }} />
                      </div>
                      <button
                        className="text-button"
                        onClick={() => action(job, "cancel")}
                      >
                        取消
                      </button>
                    </>
                  )}
                  {["failed", "cancelled", "interrupted"].includes(
                    job.status,
                  ) &&
                    !(job.kind === "prepare" && project?.ready) && (
                      <button
                        className="secondary"
                        onClick={() => action(job, "retry")}
                      >
                        <RotateCcw size={14} />
                        重試
                      </button>
                    )}
                  {job.kind === "export" && job.status === "succeeded" && (
                    <a
                      className="secondary"
                      href={`/api/jobs/${job.id}/download`}
                    >
                      <ArrowDownToLine size={14} />
                      下載 MP4
                    </a>
                  )}
                </div>
              ))}
            </section>
            </details>
          )}
          <footer>
            為完整的 Boss 勝利而設計。
            <span>搜尋與聊天共用 AI · 候選結果仍需人工確認</span>
          </footer>
        </main>
      </div>
      <ChatPanel
        jobs={projectJobs}
        searchRef={aiChat}
        onSearchError={(message) => { setError(message); setChatOpen(true); }}
        open={chatOpen}
        onToggle={() => setChatOpen((value) => !value)}
        context={project?.ready ? (editorContext?.project_id === project.id && (editorContext.analysis_generation ?? 0) === (project.analysis_generation ?? 0)
          ? editorContext : { project_id: project.id, title: project.title, duration: project.duration!, draft: project.draft!, analysis_generation: project.analysis_generation ?? 0 }) : null}
        onAction={(action, expected) => editorChat.current?.apply(action, expected) ?? "影片已切換，未套用操作。"}
      />
      {modal && (
        <ImportModal
          onClose={() => setModal(false)}
          onImport={(id) => {
            select(id);
            setModal(false);
          }}
        />
      )}
    </div>
  );
}

function ImportModal({
  onClose,
  onImport,
}: {
  onClose: () => void;
  onImport: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<"local" | "youtube">("local");
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
    api<Source[]>("/sources")
      .then(setSources)
      .catch((e) => setError(e.message));
  }, []);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ project: Project }>("/projects", "POST", {
        kind,
        source: kind === "local" ? source : url,
      });
      onImport(result.project.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog ref={dialog} onCancel={onClose} className="import-modal">
      <form onSubmit={submit}>
        <div className="modal-heading">
          <div className="modal-icon">
            <FolderOpen size={23} />
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="關閉匯入視窗"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <h2>帶入你的下一場勝利</h2>
        <p>選擇來源，我們會在本機準備預覽。</p>
        <div className="tabs">
          <button
            type="button"
            className={kind === "local" ? "tab active" : "tab"}
            onClick={() => setKind("local")}
          >
            <HardDrive size={16} />
            本機影片
          </button>
          <button
            type="button"
            className={kind === "youtube" ? "tab active" : "tab"}
            onClick={() => setKind("youtube")}
          >
            <Youtube size={17} />
            YouTube 網址
          </button>
        </div>
        {kind === "local" ? (
          <>
            <label htmlFor="source">選擇影片</label>
            <select
              id="source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              required
            >
              <option value="">選擇本機素材…</option>
              {sources.map((s) => (
                <option value={s.path} key={s.path}>
                  {s.name} · {(s.size / 1024 / 1024).toFixed(0)} MB
                </option>
              ))}
            </select>
            <p className="field-help">
              顯示專案 downloads/ 與 clips/ 內的影片。將新影片放入 downloads/
              後重新開啟此視窗，無需上傳。
            </p>
          </>
        ) : (
          <>
            <label htmlFor="youtube">公開影片網址</label>
            <input
              id="youtube"
              type="url"
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
            <p className="field-help">
              請使用有權處理且平台允許取得的來源。下載受平台限制，若無法取得，請改用本機原始錄影。POC
              不支援正在直播或需登入的影片。
            </p>
          </>
        )}
        <label htmlFor="mode">工作模式</label>
        <select id="mode">
          <option>人工／Codex CLI 輔助剪輯</option>
        </select>
        <div className="subtle-note">
          <Sparkles size={16} />
          <span>匯入後可啟動 Codex 分析，或帶入外部 Agent 的時間點。</span>
        </div>
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        <button disabled={busy} className="primary modal-submit" type="submit">
          {busy ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <Plus size={16} />
          )}
          {busy ? "建立任務中…" : "建立剪輯專案"}
        </button>
      </form>
    </dialog>
  );
}

function Editor({
  project,
  jobs,
  onError,
  chatRef,
  onContext,
  onSearch,
  onReset,
}: {
  project: Project;
  jobs: Job[];
  onError: (message: string) => void;
  chatRef: Ref<EditorChatHandle>;
  onSearch: () => Promise<void>;
  onReset: () => Promise<void>;
  onContext: (context: EditorContext) => void;
}) {
  const duration = project.duration!;
  const [draft, setDraft] = useState<Draft>(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(`bosscut:draft:${project.id}`) ?? "null",
      );
      return saved?.revision === project.draft!.revision
        ? saved
        : project.draft!;
    } catch {
      return project.draft!;
    }
  });
  const [selectedClip, setSelectedClip] = useState<string | null>(() => draft.origin === "agent"
    ? candidates(project, jobs).find(j => j.result!.start === draft.start && j.result!.victory === draft.victory && j.result!.postroll === draft.postroll)?.id ?? null : null);
  const [selectedSegment, setSelectedSegment] = useState<string | null>(null);
  const seenCandidates = useRef(new Set<string>());
  const candidateBaseline = useRef<string | null>(!draft.reviewed && draft.revision === 0 && JSON.stringify(draft) === JSON.stringify(project.draft) ? JSON.stringify(draft) : null);
  const [current, setCurrent] = useState(0);
  const [busy, setBusy] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const video = useRef<HTMLVideoElement>(null);
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
  const dirty = JSON.stringify(draft) !== JSON.stringify(project.draft);
  useEffect(() => {
    localStorage.setItem(`bosscut:draft:${project.id}`, JSON.stringify(draft));
  }, [draft, project.id]);
  useEffect(() => {
    onContext({ project_id: project.id, title: project.title, duration, draft, analysis_generation: project.analysis_generation ?? 0 });
  }, [draft, project.id, project.title, onContext]);
  useImperativeHandle(chatRef, () => ({
    apply(action, expected) {
      if ((expected.analysis_generation ?? 0) !== (project.analysis_generation ?? 0)) return "影片已重置，未套用舊操作。";
      if (expected.project_id !== project.id) return "影片已切換，未套用操作。";
      if (action.kind === "select_candidate") {
        const segment = reviewCandidates(project, jobs).find(c => c.id === action.candidate_id);
        if (!segment) return "候選片段已不存在，請重新選取。";
        selectSegment(segment);
        markAI(`已選取片段 #${segment.number}，可在時間軸預覽與核對`, ["seek"]);
        return `已選取 #${segment.number} · ${time(segment.start)}–${time(segment.end)}`;
      }
      if (action.kind === "seek") {
        if (action.seconds === null || !Number.isFinite(action.seconds) || action.seconds < 0 || action.seconds > duration) return "時間無效，未跳轉。";
        seek(action.seconds);
        markAI(`AI 已將預覽定位到 ${time(action.seconds)}`, ["seek"]);
        return `已跳到 ${time(action.seconds)}`;
      }
      if (JSON.stringify(expected.draft) !== JSON.stringify(draft)) return "你已修改草稿，未覆蓋新的設定。請再送出一次需求。";
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
  function change(values: Partial<Draft>) {
    setAiFeedback(null);
    setSelectedClip(null);
    setDraft((d) => ({ ...d, ...values, reviewed: false }));
    setSavedMessage("");
  }
  function seek(seconds: number) {
    if (video.current) {
      stopAt.current = null;
      video.current.currentTime = Math.max(0, Math.min(duration, seconds));
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
          "input, textarea, select, button, a, video",
        ) ||
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
    setBusy(true);
    onError("");
    try {
      const saved = await api<Draft>(
        `/projects/${project.id}/draft`,
        "PUT",
        draft,
      );
      setDraft(saved);
      setSavedMessage("草稿已儲存");
      if (exportNow) {
        await api(`/projects/${project.id}/exports`, "POST", {
          revision: saved.revision,
        });
        setSavedMessage("已加入匯出佇列");
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function importAgent(file?: File) {
    if (!file) return;
    try {
      if (file.size > 100_000) throw new Error("Agent JSON 檔案過大。");
      const data = JSON.parse(await file.text());
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
      });
      seek(candidate.start);
    } catch (e) {
      onError((e as Error).message);
    }
  }
  const searchingId = jobs.find(j => j.kind === "analyze" && active(j))?.id;
  useEffect(() => {
    if (searchingId) candidateBaseline.current = draft.reviewed ? null : JSON.stringify(draft);
  }, [searchingId]);
  function selectClip(job: Job, navigate = true) {
    if (!candidates(project, [job]).length) return;
    const result = job.result!;
    if (navigate) video.current?.pause();
    setDraft(d => ({ ...d, start: result.start!, victory: result.victory!, postroll: result.postroll, origin: "agent", reviewed: false }));
    setSelectedClip(job.id);
    setSavedMessage("");
    if (navigate) seek(result.start!);
    markAI("候選片段已放入時間軸，可直接預覽與拖曳調整。", ["start", "victory", "postroll"]);
  }
  function selectSegment(segment: NumberedCandidate) {
    video.current?.pause();
    setSelectedSegment(segment.id);
    seek(segment.start);
  }
  useEffect(() => {
    const candidate = candidates(project, jobs)[0];
    if (!candidate || seenCandidates.current.has(candidate.id)) return;
    seenCandidates.current.add(candidate.id);
    if (candidateBaseline.current === JSON.stringify(draft) && !draft.reviewed) selectClip(candidate, false);
  }, [jobs, project.id]);
  return (
    <>
      {aiFeedback && <div className="ai-editor-feedback" role="status" key={aiFeedback.id}><Sparkles size={14} />{aiFeedback.text}</div>}
      <div className="editor-grid">
        <section aria-label="影片與選取範圍" className={`preview-panel ${aiFeedback?.fields.includes("seek") ? "ai-target" : ""}`}>
          <div className="panel-heading">
            <span>
              <Film size={16} />
              <strong title={project.title}>{project.title}</strong>
            </span>
            <span className="resolution">
              {project.width} × {project.height}
            </span>
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
              controls
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
            <span className="preview-badge">720P PREVIEW</span>
          </div>
          <div className="transport">
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
          <BossReviewDock jobs={jobs} onSearch={onSearch} onReset={onReset} onError={onError} />
          <ClipWorkspace project={project} jobs={jobs} draft={draft} selected={selectedClip}
            selectedSegment={selectedSegment} onSelectSegment={selectSegment} onError={onError}
            onSelect={selectClip} onChange={change} onPlay={playRange} onSeek={seek} current={current} />
          <div className="compact-export">            <label className="review-checkbox">
              <input
                type="checkbox"
                checked={draft.reviewed}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, reviewed: e.target.checked }))
                }
              />
              <span>
                我已完整看過：只有成功挑戰，包含勝利。
              </span>
            </label>
            <button
              className="primary export-button"
              disabled={
                !valid ||
                !draft.reviewed ||
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
              匯出 MP4
            </button>
            <p className="export-help">原片重新編碼 · 保留原始音訊內容</p>
          </div>
        </section>
        <details className="editor-settings workspace-details"><summary>精確時間與手動調整</summary>
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
              onClick={() =>
                playRange(draft.start, Math.min(end, draft.start + 10))
              }
            >
              播放開頭
            </button>
            <button
              disabled={!valid}
              onClick={() => playRange(Math.max(draft.start, end - 10), end)}
            >
              播放結尾
            </button>
          </div>
        <aside className="inspector">
          <div className="inspector-heading">
            <Scissors size={17} />
            <h2>剪輯設定</h2>
            <span className="badge">
              {draft.origin === "agent" ? "AGENT" : "MANUAL"}
            </span>
          </div>
          <div className="inspector-body">
            <div className="clip-name">
              <span className="clip-icon">
                <Trophy size={18} />
              </span>
              <div>
                <strong>成功挑戰片段</strong>
                <small>保留一場完整且連續的勝利</small>
              </div>
            </div>
            <label className="time-label" htmlFor="start">
              <span className="marker start" />
              開始時間<span>{time(draft.start)}</span>
            </label>
            <div className="number-field">
              <input
                id="start"
                className={aiFeedback?.fields.includes("start") ? "ai-target" : undefined}
                type="number"
                min="0"
                max={duration}
                step="0.001"
                value={draft.start}
                onChange={(e) => change({ start: Number(e.target.value) })}
              />
              <span>秒</span>
              <button onClick={() => seek(draft.start)} aria-label="跳到開始">
                <ChevronRight size={17} />
              </button>
            </div>
            <label className="time-label" htmlFor="victory">
              <span className="marker victory" />
              勝利時間<span>{time(draft.victory)}</span>
            </label>
            <div className="number-field">
              <input
                id="victory"
                className={aiFeedback?.fields.includes("victory") ? "ai-target" : undefined}
                type="number"
                min="0"
                max={duration}
                step="0.001"
                value={draft.victory}
                onChange={(e) => change({ victory: Number(e.target.value) })}
              />
              <span>秒</span>
              <button onClick={() => seek(draft.victory)} aria-label="跳到勝利">
                <ChevronRight size={17} />
              </button>
            </div>
            <label className="time-label" htmlFor="postroll">
              勝利後收尾<span>{draft.postroll} 秒</span>
            </label>
            <input
              id="postroll"
              className={`postroll ${aiFeedback?.fields.includes("postroll") ? "ai-target" : ""}`}
              type="range"
              min="5"
              max="10"
              step="1"
              value={draft.postroll}
              onChange={(e) => change({ postroll: Number(e.target.value) })}
            />
            <div className="range-labels">
              <span>5 秒</span>
              <span>10 秒</span>
            </div>
            <div className="duration-summary">
              <span>預計片段長度</span>
              <strong>{time(Math.max(0, end - draft.start))}</strong>
              <small>結束於 {time(end)}</small>
            </div>
            {!valid && (
              <p role="alert" className="inline-error">
                請讓開始早於勝利，並確保收尾未超出原片。
              </p>
            )}
          </div>
        </aside>
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
                setDraft(project.draft!);
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
      </div>
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
    </>
  );
}
