import { useEffect, useState } from "react";
import { api } from "./api";

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

export default function AIConnection({ onChange }: { onChange?: (value: Connection) => void }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const pending = connection?.login?.status === "pending";

  async function refresh() {
    const status = await api<Connection>("/codex");
    setConnection(status);
    onChange?.(status);
    window.dispatchEvent(new Event("bosscut:ai-connection"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      refresh().catch((e) => setError(e.message));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pending]);

  async function perform(action: string) {
    setBusy(action);
    setError("");
    setReply("");
    try {
      if (action === "test") {
        const result = await api<{ reply: string; model: string }>("/codex/test", "POST");
        setReply(`${result.model}：${result.reply}`);
      } else if (action === "cancel") {
        await api("/codex/login/cancel", "POST");
      } else if (action !== "refresh") {
        await api("/codex/login", "POST", { method: action });
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="codex-panel ai-connection" aria-label="AI 帳號與連線">
      <div className="codex-heading">
        <div>
          <h2>AI 帳號與連線</h2>
          <p>連接自己的 ChatGPT 帳號，先確認 AI 能回應，再開始剪輯。</p>
        </div>
        <span className="badge">{connection?.available ? "帳號已連接" : "尚未連接"}</span>
      </div>
      <p>{connection?.detail ?? "正在確認帳號…"}</p>
      {connection?.email && <p>{connection.email} · {connection.plan}</p>}
      <div className="ai-connection-actions">
        {!pending && <>
          <button className="secondary" disabled={!!busy} onClick={() => perform("chatgptDeviceCode")}>
            {connection?.available ? "重新連接 ChatGPT" : "使用 ChatGPT 登入"}
          </button>
          <button className="secondary" disabled={!!busy} onClick={() => perform("chatgpt")}>
            瀏覽器登入（後端在本機）
          </button>
        </>}
        <button className="secondary" disabled={!!busy} onClick={() => perform("refresh")}>重新整理狀態</button>
        <button className="primary" disabled={!!busy || pending || !connection?.available} onClick={() => perform("test")}>
          {busy === "test" ? "等待 AI 回應（最多 60 秒）…" : "測試 AI 文字回應"}
        </button>
      </div>
      {pending && <div role="status">
        <p>開啟官方登入頁完成授權，完成後此處會自動更新。</p>
        {connection.login?.userCode && <p>裝置驗證碼：<strong>{connection.login.userCode}</strong></p>}
        <a href={connection.login?.url} target="_blank" rel="noreferrer">前往 OpenAI 官方登入頁</a>
        <button className="secondary" disabled={!!busy} onClick={() => perform("cancel")}>取消登入</button>
      </div>}
      {connection?.login?.status === "failed" && <p role="alert">登入未完成或已過期，請重新連接。</p>}
      <p className="codex-disclosure">
        登入由官方 Codex 管理，與後端環境的 Codex CLI 共用帳號。遠端容器請使用裝置驗證碼登入；
        若帳號未開啟裝置碼授權，可於 ChatGPT 安全設定啟用，或在後端執行 codex login。
        文字測試只發送一則短訊息，會使用少量 AI 額度，不讀取影片、不抽幀、不剪片。
      </p>
      {reply && <p className="ai-reply" role="status">{reply}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
    </section>
  );
}
