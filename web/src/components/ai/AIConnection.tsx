import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { Check, Copy, ExternalLink, LogOut } from "lucide-react";
import { api } from "../../lib/api";

type Login = { status: string; url?: string; userCode?: string };
export type Connection = {
  available: boolean;
  detail: string;
  model: string;
  email?: string;
  plan?: string;
  auth_mode?: string;
  login?: Login;
};

export type ConnectionHandle = { login: () => void };

export default function AIConnection({ onChange, ref }: { onChange?: (value: Connection) => void; ref?: Ref<ConnectionHandle> }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const [copied, setCopied] = useState(false);
  const performing = useRef(false);
  const pending = connection?.login?.status === "pending";
  const needsLogin = !!connection && !connection.available;

  async function refresh() {
    const status = await api<Connection>("/codex");
    setConnection(status);
    setError("");
    onChange?.(status);
    window.dispatchEvent(new Event("bosscut:ai-connection"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    const checkOnReturn = () => {
      if (document.visibilityState === "visible" && !performing.current) refresh().catch((e) => setError(e.message));
    };
    window.addEventListener("focus", checkOnReturn);
    return () => window.removeEventListener("focus", checkOnReturn);
  }, []);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      refresh().catch((e) => setError(e.message));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pending]);
  useImperativeHandle(ref, () => ({ login: () => { if (!pending) void perform("chatgptDeviceCode"); } }));

  async function perform(action: string) {
    if (performing.current) return;
    performing.current = true;
    setBusy(action);
    setError("");
    setReply("");
    setCopied(false);
    try {
      if (action === "test") {
        const result = await api<{ reply: string; model: string }>("/codex/test", "POST");
        setReply(`${result.model}：${result.reply}`);
      } else if (action === "cancel") {
        await api("/codex/login/cancel", "POST");
      } else if (action === "logout") {
        await api("/codex/logout", "POST");
      } else if (action !== "refresh") {
        const login = await api<Login>("/codex/login", "POST", { method: action });
        setConnection(previous => previous ? { ...previous, login } : previous);
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      performing.current = false;
      setBusy("");
    }
  }

  return (
    <section className="codex-panel ai-connection" aria-label="AI 帳號與連線" aria-busy={!!busy}>
      <div className="codex-heading">
        <div>
          <h2>AI 帳號與連線</h2>
          <p>{needsLogin ? "記得先登入，才能使用 AI 搜尋與對話。使用你的 ChatGPT 帳號即可連接 Codex。" : "在這裡管理你的 Codex 帳號與 AI 連線。"}</p>
        </div>
        <span className="badge" role="status">{connection?.available ? "Codex 已連接" : pending ? "等待完成登入" : connection ? "尚未登入" : "確認中"}</span>
      </div>
      {connection?.detail !== "尚未連接 ChatGPT 帳號。" && <p>{connection?.detail ?? "正在確認帳號…"}</p>}
      {connection?.email && <p>{connection.email} · {connection.plan}</p>}
      <div className="ai-connection-actions">
        {!pending ? <button type="button" className={connection?.available ? "secondary" : "primary"} disabled={!!busy || !connection} onClick={() => perform("chatgptDeviceCode")}>
          {busy === "chatgptDeviceCode" ? "正在取得驗證碼…" : connection?.available ? "重新連接 ChatGPT" : "使用 ChatGPT 登入"}
        </button> : <button type="button" className="secondary" disabled={!!busy} onClick={() => perform("cancel")}>取消登入</button>}
        {connection?.available && !pending && <button type="button" className="secondary" disabled={!!busy} onClick={() => perform("test")}>
          {busy === "test" ? "等待 AI 回應（最多 60 秒）…" : "測試 AI 文字回應"}
        </button>}
        <button type="button" className="secondary" disabled={!!busy} onClick={() => perform("refresh")}>重新整理狀態</button>
        {connection?.available && !pending && <button type="button" className="secondary" disabled={!!busy} onClick={() => perform("logout")}>
          <LogOut size={15} aria-hidden="true" />{busy === "logout" ? "正在登出…" : "登出 Codex"}
        </button>}
      </div>
      {(needsLogin || pending) && <ol className="codex-login-steps" aria-label="Codex 登入步驟">
        <li><strong>{pending ? "登入要求已送出" : "取得登入驗證碼"}</strong><p>{pending ? "接著依下方指引，在官方頁面完成授權。" : "按下「使用 ChatGPT 登入」，取得這次登入的驗證碼。"}</p></li>
        <li><strong>前往官方頁面完成登入</strong>
          <p>{pending && !connection?.login?.userCode ? "開啟下方的官方登入頁，使用你的 ChatGPT 帳號完成授權。" : "開啟官方登入頁，使用你的 ChatGPT 帳號登入並輸入驗證碼。"}</p>
          {pending && connection?.login?.userCode && <div className="codex-device-code">
            <span>裝置驗證碼</span><strong>{connection.login.userCode}</strong>
            <button type="button" className="secondary" onClick={async () => {
              try { await navigator.clipboard.writeText(connection.login!.userCode!); setCopied(true); }
              catch { setError("無法複製驗證碼，請手動選取上方驗證碼。"); }
            }}>{copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}{copied ? "已複製" : "複製驗證碼"}</button>
          </div>}
          {pending && connection?.login?.url && <a className="primary codex-official-login" href={connection.login.url} target="_blank" rel="noreferrer">
            前往 OpenAI 官方登入頁<ExternalLink size={15} aria-hidden="true" /><span className="sr-only">（在新分頁開啟）</span>
          </a>}
        </li>
        <li><strong>回到工作區，等待連接完成</strong><p role={pending ? "status" : undefined}>完成授權後會自動確認，顯示「Codex 已連接」就可以開始使用 AI。</p></li>
      </ol>}
      {connection?.login?.status === "failed" && <p className="inline-error" role="alert">登入未完成或已過期，請按「使用 ChatGPT 登入」重新取得驗證碼。</p>}
      <details className="codex-login-help"><summary>登入遇到問題？其他登入方式與說明</summary>
        <p>若帳號未開啟裝置碼授權，可於 ChatGPT 安全設定啟用。完成後重新取得驗證碼再試一次。</p>
        <div className="ai-connection-actions">
          <button type="button" className="secondary" disabled={!!busy || pending || !connection} onClick={() => perform("chatgpt")}>瀏覽器登入（後端在本機）</button>
        </div>
        <p>登入由官方 Codex 管理，與執行工作區的 Codex CLI 共用帳號。也可以在該環境執行 codex login。</p>
      </details>
      {connection?.available && <p className="codex-disclosure">文字測試會使用少量 AI 額度，只發送一則短訊息。</p>}
      {reply && <p className="ai-reply" role="status">{reply}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </section>
  );
}
