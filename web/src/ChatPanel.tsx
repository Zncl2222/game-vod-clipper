import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from "react";
import { ArrowUp, Check, ChevronDown, MessageCircle, PanelRightClose, PanelRightOpen, Plus, Settings2, Sparkles, Square } from "lucide-react";
import AIConnection, { type Connection } from "./AIConnection";
import { active, currentAnalysis, api, apiError, time, type Draft, type Job } from "./api";
import AIActivity from "./AIActivity";
import AnalysisTask from "./AnalysisTask";
import ModelSettings, { type Model } from "./ModelSettings";

export type EditorContext = { analysis_generation?: number; project_id: string; title: string; duration: number; draft: Draft };
export type ChatAction = {
  kind: "set_draft" | "seek" | "select_candidate" | "export";
  candidate_id?: string | null;
  start: number | null;
  victory: number | null;
  postroll: number | null;
  seconds: number | null;
};
export type EditorChatHandle = {
  apply: (action: ChatAction, expected: EditorContext) => string;
};
export type ChatHandle = { search: () => Promise<void> };
type Message = { project_id?: string; analysis_generation?: number; id: string; role: "user" | "assistant"; content: string; model?: string; operation?: string; failed?: boolean };
type Reply = { type: string; reply?: string; model?: string; action?: ChatAction | null; project_id?: string; detail?: string };
const STORAGE = "bosscut:chat:v1";

function readMessages(): Message[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE) ?? "[]");
    return Array.isArray(value) ? value.filter((m) => m && typeof m.content === "string" && m.content.length <= 12000
      && typeof m.id === "string" && ["user", "assistant"].includes(m.role)).slice(-60) : [];
  } catch { return []; }
}

export default function ChatPanel({ context, onAction, open, onToggle, jobs, searchRef, onSearchError }: {
  context: EditorContext | null;
  onAction: (action: ChatAction, context: EditorContext) => string;
  open: boolean;
  onToggle: () => void;
  jobs: Job[];
  searchRef: Ref<ChatHandle>;
  onSearchError: (message: string) => void;
}) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState(() => localStorage.getItem("bosscut:chat-model") ?? "");
  const [modelError, setModelError] = useState("");
  const [effort, setEffort] = useState(() => localStorage.getItem("bosscut:effort") ?? "");
  const selectedModel = models.find(m => m.id === model);
  const supportedEfforts = selectedModel?.supported_efforts ?? [];
  const effectiveEffort = supportedEfforts.includes(effort) ? effort : "";
  useEffect(() => { localStorage.setItem("bosscut:effort", effort); }, [effort]);
  const [mode, setMode] = useState<"chat" | "edit">("chat");
  const [messages, setMessages] = useState<Message[]>(readMessages);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState(false);
  const [searchStart, setSearchStart] = useState(0);
  const [showSearchHistory, setShowSearchHistory] = useState(false);
  const [searchEnd, setSearchEnd] = useState(0);
  const taskArea = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  const historyEnd = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const panelToggle = useRef<HTMLButtonElement>(null);
  const previousOpen = useRef(open);
  useEffect(() => {
    if (previousOpen.current !== open) {
      (open ? composer.current : panelToggle.current)?.focus({ preventScroll: true });
    }
    previousOpen.current = open;
  }, [open]);
  const account = useRef<string | undefined>(undefined);
  const currentContext = useRef(context);
  currentContext.current = context;
  const previousGeneration = useRef(context?.analysis_generation ?? 0);
  const restoredMessageIds = useRef(new Set(messages.map((message) => message.id)));
  const searches = jobs.filter(currentAnalysis);
  const analysis = searches.find(active) ?? searches[0];
  useEffect(() => {
    setMode(context ? "edit" : "chat");
    setSearchStart(0);
    setShowSearchHistory(false);
    setSearchEnd(context?.duration ?? 0);
  }, [context?.project_id]);
  useEffect(() => {
    const generation = context?.analysis_generation ?? 0;
    if (generation > 0 && generation !== previousGeneration.current) {
      controller.current?.abort();
      setMessages(previous => previous.filter(m => m.project_id !== context?.project_id || m.analysis_generation === generation));
      setInput("");
      setError("");
      setSearchStart(0);
      setSearchEnd(context?.duration ?? 0);
      setShowSearchHistory(false);
    }
    previousGeneration.current = generation;
  }, [context?.project_id, context?.analysis_generation]);
  useImperativeHandle(searchRef, () => ({ search: async () => { setMode("edit"); await send(true); } }));
  const searchValid = !!context && Number.isFinite(searchStart) && Number.isFinite(searchEnd)
    && searchStart >= 0 && searchStart < searchEnd && searchEnd <= context.duration;

  useLayoutEffect(() => {
    const element = composer.current;
    if (!element) return;
    function resize() {
      if (!element || !element.clientWidth) return;
      element.style.height = "auto";
      const height = Math.min(108, Math.max(26, element.scrollHeight));
      element.style.height = `${height}px`;
      element.style.overflowY = element.scrollHeight > 108 ? "auto" : "hidden";
    }
    resize();
    let width = element.clientWidth;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth !== width) { width = element.clientWidth; resize(); }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [input, open]);

  async function loadModels() {
    setModelError("");
    try {
      const data = await api<{ models: Model[] }>("/codex/models");
      setModels(data.models);
      setModel((current) => data.models.some((m) => m.id === current) ? current :
        (data.models.find((m) => m.is_default) ?? data.models[0])?.id ?? "");
      if (!data.models.length) setModelError("尚無可選模型，請檢查登入狀態後重新整理。");
    } catch (e) { setModelError((e as Error).message); }
  }
  useEffect(() => {
    if (connection?.available) void loadModels();
  }, [connection?.available, connection?.email, connection?.auth_mode]);
  useEffect(() => {
    const identity = connection ? `${connection.auth_mode}:${connection.email ?? ""}` : undefined;
    if (account.current && identity && account.current !== identity) {
      controller.current?.abort();
      setMessages([]);
      setInput("");
    }
    if (identity) account.current = identity;
  }, [connection]);
  useEffect(() => { if (model) localStorage.setItem("bosscut:chat-model", model); }, [model]);
  useEffect(() => {
    try { sessionStorage.setItem(STORAGE, JSON.stringify(messages.slice(-60))); } catch { /* Storage may be full. */ }
    historyEnd.current?.scrollIntoView({ behavior: "instant", block: "nearest" });
  }, [messages, busy, error, modelError]);
  useEffect(() => () => controller.current?.abort(), []);

  async function send(search = false) {
    const reportError = (message: string) => { setError(message); if (search) onSearchError(message); };
    const text = search ? `搜尋 ${time(searchStart)}–${time(searchEnd)} 的成功挑戰。` : input.trim();
    if (!text || busy) return;
    if (!model || !connection?.available) {
      reportError("請先連接 AI 帳號並選擇模型。"); setSettings(true); return;
    }
    if ((search || mode === "edit") && !context) { reportError("先選擇已就緒的影片，或切換一般聊天。"); return; }
    if (search && (!searchValid || (analysis && active(analysis)))) {
      reportError(!searchValid ? "請設定原片內的搜尋範圍。" : "此影片正在搜尋，可在任務卡片取消或等待完成。"); return;
    }
    const snapshot = search || mode === "edit" ? context : null;
    const messageContext = snapshot ? { project_id: snapshot.project_id, analysis_generation: snapshot.analysis_generation ?? 0 } : {};
    const stale = () => !!snapshot && (currentContext.current?.project_id !== snapshot.project_id
      || (currentContext.current?.analysis_generation ?? 0) !== (snapshot.analysis_generation ?? 0));
    const requestIdentity = account.current;
    const userId = crypto.randomUUID();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setInput("");
    setMessages((previous) => [...previous.slice(-58), { id: userId, role: "user", content: text, ...messageContext }]);
    // Bound context by both turns and text size; the visible transcript stays intact.
    const history = messages.filter((m) => !m.failed && (!snapshot?.analysis_generation || (m.project_id === snapshot.project_id && m.analysis_generation === snapshot.analysis_generation))).slice(-24).map(({ role, content }) => ({ role, content }));
    while (history.reduce((size, m) => size + m.content.length, 0) > 24000) history.shift();
    try {
      const response = await fetch("/api/codex/chat", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: abort.signal,
        body: JSON.stringify({ message: text, model, effort: effectiveEffort || null, history, request_id: userId,
          intent: search ? "search" : "message", search_start: search ? searchStart : null,
          search_end: search ? searchEnd : null,
          context: snapshot ? { project_id: snapshot.project_id, analysis_generation: snapshot.analysis_generation ?? 0, draft: {
            start: snapshot.draft.start, victory: snapshot.draft.victory, postroll: snapshot.draft.postroll,
          } } : null }),
      });
      if (!response.ok) {
        const failure = await response.json().catch(() => null);
        throw new Error(apiError("/codex/chat", response.status, failure?.detail));
      }
      if (!response.body) throw new Error("沒有收到回應，請重試。");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let received = false;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;
        for (const line of lines) {
          if (!line.trim()) continue;
          const event: Reply = JSON.parse(line);
          if (event.type === "error") throw new Error(event.detail ?? "AI 回應失敗。");
          if (event.type === "reply" && event.reply && !received) {
            received = true;
            if (stale()) continue;
            let operation: string | undefined;
            if (event.action && snapshot && event.project_id === snapshot.project_id) {
              operation = onAction(event.action, snapshot);
            }
            setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: "assistant",
              content: event.reply!, model: event.model, operation, ...messageContext }]);
          }
        }
        if (done) break;
      }
      if (!received) throw new Error("連線中斷，尚未收到完整回應，請重試。");
    } catch (e) {
      const cancelled = abort.signal.aborted;
      if (requestIdentity === account.current && !stale()) {
        reportError(cancelled ? "已停止回應。你可以修改訊息後再送出。" : (e as Error).message);
        setInput((draft) => draft || text);
        setMessages((previous) => previous.map((m) => m.id === userId ? { ...m, failed: true } : m));
      }
    } finally {
      controller.current = null;
      setBusy(false);
      if (!search) composer.current?.focus();
    }
  }

  return <>
    <button ref={panelToggle} className="chat-mobile-toggle" onClick={onToggle} aria-expanded={open} aria-controls="ai-chat-panel" title={open ? "收合 AI 側欄" : "展開 AI 側欄"}>
      <PanelRightOpen size={18} aria-hidden="true" />{open ? "回到工作區" : "AI 對話"}
    </button>
    <aside id="ai-chat-panel" className={`chat-panel ${open ? "is-open" : ""}`} aria-label="AI 對話">
      <header className="chat-header">
        <div className="chat-mark"><Sparkles size={18} /></div>
        <div><h2>你的 AI 夥伴</h2><span><i className={connection?.available ? "online" : ""} />{connection?.available ? "已連接 · 隨時聊聊" : "連接帳號開始對話"}</span></div>
        <button className="chat-icon" title="新對話" aria-label="新對話" disabled={busy || !messages.length} onClick={() => { setMessages([]); setError(""); setInput(""); }}><Plus size={18} /></button>
        <button className="chat-icon" title="帳號設定" aria-label="帳號設定" aria-expanded={settings} onClick={() => setSettings(!settings)}><Settings2 size={18} /></button>
        <button className="chat-close chat-icon" aria-label="關閉 AI 對話" title="收合 AI 側欄" aria-expanded={open} aria-controls="ai-chat-panel" onClick={onToggle}><PanelRightClose size={18} aria-hidden="true" /></button>
      </header>
      <div className={`chat-settings ${settings ? "expanded" : ""}`} inert={!settings}>
        <AIConnection onChange={setConnection} />
      </div>
      <div className="chat-mode" role="group" aria-label="對話模式">
        <button aria-pressed={mode === "chat"} disabled={busy} onClick={() => setMode("chat")}><MessageCircle size={14} />一般聊天</button>
        <button aria-pressed={mode === "edit"} disabled={busy} onClick={() => setMode("edit")}><Sparkles size={14} />剪輯助理</button>
      </div>
      {mode === "edit" && <div className="chat-context"><span className="tiny-dot" /><span title={context?.title}>{context ? `目前影片 · ${context.title}` : "請先選擇已就緒的影片"}</span></div>}
      <div className="chat-messages" role="log" aria-label="對話紀錄" aria-live="polite">
        {!messages.length && <div className="chat-welcome">
          <div className="chat-welcome-icon"><Sparkles size={28} strokeWidth={1.4} /></div>
          <span className="eyebrow">YOUR CREATIVE COMPANION</span>
          <h3>{mode === "chat" ? "想聊些什麼？" : "用一句話，調整你的剪輯。"}</h3>
          <p>{mode === "chat" ? "聊遊戲、整理直播靈感，或一起想個好標題。" : "找出成功的那場挑戰、微調時間，或整理值得留下的片段。你掌握最後的剪輯決定。"}</p>
          <div className="chat-suggestions">
            {(mode === "chat" ? ["幫我想三個有趣的直播標題", "陪我聊聊最近玩的遊戲"] : ["搜尋整部影片的成功挑戰", "把勝利後收尾改成 8 秒", "匯出目前已確認的片段"]).map((text) => <button key={text} onClick={() => { setInput(text); composer.current?.focus(); }}>{text}<ArrowUp size={13} /></button>)}
          </div>
          {!connection?.available && <button className="primary" onClick={() => setSettings(true)}>連接 AI 帳號</button>}
        </div>}
        {messages.map((message) => <article key={message.id} className={`chat-message ${message.role} ${message.failed ? "failed" : ""} ${!restoredMessageIds.current.has(message.id) ? "is-new" : ""}`}>
          <span className="chat-message-author">{message.role === "user" ? "你" : message.model ?? "AI"}{message.failed && " · 未完成"}</span>
          <div className="chat-message-body">{message.content}</div>
          {message.operation && <div className="chat-operation"><Check size={13} />{message.operation}</div>}
        </article>)}
        {busy && <div className="chat-thinking" role="status"><span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" />正在回應…</div>}
        <div ref={taskArea}>
          {analysis && <AIActivity job={analysis} onInspect={() => taskArea.current?.querySelector(".assistant-task")?.scrollIntoView({ block: "nearest" })} />}
          {searches.length > 1 &&
            <button className="text-button" aria-expanded={showSearchHistory} onClick={() => setShowSearchHistory(!showSearchHistory)}>
              {showSearchHistory ? "收起較早的搜尋紀錄" : "查看較早的搜尋紀錄"}
            </button>}
          {searches.slice(0, showSearchHistory ? 3 : 1).reverse().map((job) =>
            <AnalysisTask key={job.id} job={job} onError={setError}
              onSeek={(seconds) => { if (context) onAction({ kind: "seek", seconds, start: null, victory: null, postroll: null }, context); }}
              onApply={(result) => {
                if (!context || job.project_id !== context.project_id || (result.project_id && result.project_id !== context.project_id)) { setError("請先選擇對應影片。"); return; }
                setError("");
                const outcome = onAction({ kind: "set_draft", start: result.start, victory: result.victory, postroll: result.postroll, seconds: null }, context);
                setMessages((previous) => [...previous, { id: crypto.randomUUID(), role: "assistant", content: outcome, model: result.model }]);
              }} />)}
        </div>
        {error && <p className="chat-error" role="alert">{error}</p>}
        {modelError && <p className="chat-error" role="alert">{modelError} <button disabled={busy} onClick={loadModels}>重新整理模型</button></p>}
        <div ref={historyEnd} />
      </div>
      <div className="chat-bottom">
        {mode === "edit" && context && <div className="chat-search-controls">
          <button type="button" className="chat-search-button" aria-label="一鍵搜尋成功挑戰"
            title={`搜尋 ${time(searchStart)}–${time(searchEnd)} 的成功挑戰`}
            disabled={busy || !connection?.available || !model || !searchValid || (!!analysis && active(analysis))}
            onClick={() => void send(true)}><Sparkles size={13} />搜尋成功挑戰</button>
          <details className="chat-search-options"><summary title="設定搜尋範圍">範圍 <ChevronDown size={12} /></summary>
            <div className="chat-search-popover">
              <strong>搜尋範圍 · 預設全片</strong><p>逐段搜尋，再密集檢查整場挑戰與起訖。長片可能需要較久，可隨時停止並接續。</p>
              <div className="chat-search-fields"><label>搜尋起點（秒）<input type="number" min={0} max={context.duration} value={searchStart} disabled={busy} aria-invalid={!searchValid} aria-describedby={!searchValid ? "search-range-error" : undefined} onChange={(e) => setSearchStart(Number(e.target.value))} /></label>
              <label>搜尋終點（秒）<input type="number" min={0} max={context.duration} value={searchEnd} disabled={busy} aria-invalid={!searchValid} aria-describedby={!searchValid ? "search-range-error" : undefined} onChange={(e) => setSearchEnd(Number(e.target.value))} /></label></div>
              {!searchValid && <p id="search-range-error" className="inline-error" role="alert">起點必須早於終點，且介於 0 到 {context.duration} 秒之間。</p>}
              <small>與聊天使用同一模型，抽樣畫面會送交 AI。</small>
              <button type="button" className="text-button" onClick={(e) => e.currentTarget.closest("details")?.removeAttribute("open")}>完成設定</button>
            </div>
          </details>
        </div>}
        <form className="chat-composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <textarea ref={composer} aria-label="輸入訊息" placeholder={mode === "chat" ? "問問題、聊想法，什麼都可以…" : "例如：把收尾調整成 8 秒…"}
            value={input} maxLength={4000} rows={1} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
          <div className="chat-composer-tools">
            <ModelSettings models={models} model={model} effort={effectiveEffort} disabled={busy}
              connected={!!connection?.available} onModelChange={setModel} onEffortChange={setEffort} />
            {busy ? <button type="button" className="chat-send" aria-label="停止回應" onClick={() => controller.current?.abort()}><Square size={14} fill="currentColor" /></button> :
              <button type="submit" className="chat-send" aria-label="送出訊息" disabled={!input.trim() || !model || !connection?.available || (mode === "edit" && !context)}><ArrowUp size={19} /></button>}
          </div>
        </form>
        <p className="chat-footnote">{connection?.auth_mode === "apiKey" ? "API 用量另外計費" : "使用你的 Codex 額度"} · Shift + Enter 換行</p>
      </div>
    </aside>
  </>;
}
