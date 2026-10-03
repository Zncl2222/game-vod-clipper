import { ArrowRight, LogIn } from "lucide-react";
import type { Connection } from "./AIConnection";

export default function CodexLoginReminder({ connection, onLogin }: {
  connection: Connection | null;
  onLogin: () => void;
}) {
  if (!connection || connection.available) return null;
  const pending = connection.login?.status === "pending";
  return <section className="codex-login-reminder" aria-labelledby="codex-login-title">
    <LogIn size={24} aria-hidden="true" />
    <div>
      <h2 id="codex-login-title">{pending ? "還差一步：完成 Codex 登入" : "使用 AI 前，記得登入你的 Codex 帳號"}</h2>
      <p>{pending ? "請在官方登入頁完成授權，回到這裡後會自動確認登入狀態。" : "使用你的 ChatGPT 帳號連接 Codex，就能讓 AI 尋找成功挑戰、協助調整剪輯。"}</p>
      <span>也可以先匯入影片、手動剪輯，稍後再登入。</span>
    </div>
    <button type="button" className="primary" onClick={onLogin} aria-controls="ai-chat-panel">
      {pending ? "查看登入步驟" : "使用 ChatGPT 登入"}<ArrowRight size={16} aria-hidden="true" />
    </button>
  </section>;
}
