import { useEffect, useRef, useState } from "react";
import { ChartNoAxesColumnIncreasing, ChevronDown, RefreshCw } from "lucide-react";
import { api, type RateLimits, type TokenUsage, type UsageSummary } from "../../lib/api";
import "../../styles/usage.css";

const number = (value: number) => value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
const compact = (value: number) => new Intl.NumberFormat("zh-TW", { notation: "compact", maximumFractionDigits: 1 }).format(value);
const date = (value: number) => new Date(value * 1000).toLocaleString("zh-TW", {
  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
});

function validTokens(value: TokenUsage | undefined) {
  return !!value && [value.total_tokens, value.input_tokens, value.output_tokens,
    value.cached_input_tokens, value.reasoning_output_tokens].every(count => Number.isFinite(count) && count >= 0);
}

function checkUsage(data: UsageSummary) {
  const latest = data?.latest_analysis;
  if (!validTokens(data?.total) || (data.project && !validTokens(data.project)) ||
    (latest && (!validTokens(latest.tokens) || (latest.quota_change && !Array.isArray(latest.quota_change.windows))))) {
    throw new Error("Token 紀錄格式異常，請更新後端並重新整理。");
  }
  return data;
}

function checkQuota(data: RateLimits) {
  if (typeof data?.available !== "boolean" || !Array.isArray(data.buckets) ||
    !data.buckets.every(bucket => bucket && typeof bucket.name === "string" && Array.isArray(bucket.windows) &&
      bucket.windows.every(window => window && Number.isFinite(window.used_percent) &&
        (window.window_minutes === null || Number.isFinite(window.window_minutes)) &&
        (window.resets_at === null || Number.isFinite(window.resets_at))))) {
    throw new Error("額度資料格式異常，請更新後端並重新整理。");
  }
  return data;
}

function windowName(minutes: number | null) {
  if (minutes === 10080) return "週額度";
  if (minutes === null) return "用量視窗";
  if (minutes % 1440 === 0) return `${number(minutes / 1440)} 天額度`;
  if (minutes % 60 === 0) return `${number(minutes / 60)} 小時額度`;
  return `${number(minutes)} 分鐘額度`;
}

function TokenDetails({ label, usage }: { label: string; usage: TokenUsage }) {
  return <section className="usage-token-card" aria-label={label}>
    <div><span>{label}</span><strong>{number(usage.total_tokens)} <small>tokens</small></strong></div>
    <dl><div><dt>輸入</dt><dd>{number(usage.input_tokens)}</dd></div>
      <div><dt>輸出</dt><dd>{number(usage.output_tokens)}</dd></div></dl>
    <p>含快取輸入 {number(usage.cached_input_tokens)} · 推理輸出 {number(usage.reasoning_output_tokens)}</p>
  </section>;
}

export default function UsagePanel({ projectId, accountKey, refreshKey, visible }: {
  projectId?: string; accountKey: string; refreshKey: string; visible: boolean;
}) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [quota, setQuota] = useState<RateLimits | null>(null);
  const [usageError, setUsageError] = useState("");
  const [quotaError, setQuotaError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const sequence = useRef(0);

  async function refresh() {
    const request = ++sequence.current;
    setBusy(true);
    const local = api<UsageSummary>(`/codex/usage${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`)
      .then(checkUsage)
      .then(data => { if (request === sequence.current) { setUsage(data); setUsageError(""); } })
      .catch((error: Error) => { if (request === sequence.current) { setUsage(null); setUsageError(error.message); } });
    const remote = api<RateLimits>("/codex/rate-limits")
      .then(checkQuota)
      .then(data => { if (request === sequence.current) { setQuota(data); setQuotaError(""); } })
      .catch((error: Error) => { if (request === sequence.current) { setQuota(null); setQuotaError(error.message); } });
    await Promise.all([local, remote]);
    if (request === sequence.current) setBusy(false);
  }

  useEffect(() => {
    // Invalidate old-project/account requests even while the drawer is hidden.
    sequence.current++;
    setUsage(null); setQuota(null); setUsageError(""); setQuotaError("");
    return () => { sequence.current++; };
  }, [projectId, accountKey]);
  useEffect(() => {
    if (visible) void refresh();
    return () => { sequence.current++; };
  }, [refreshKey, projectId, accountKey, visible]);
  useEffect(() => {
    if (!visible) return;
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 30_000);
    return () => window.clearInterval(timer);
  }, [visible, projectId, accountKey]);

  const weekly = quota?.available ? (quota.buckets.find(bucket => bucket.id === "codex") ?? quota.buckets[0])
    ?.windows.find(window => window.window_minutes === 10080) : undefined;
  const latest = usage?.latest_analysis;
  const change = latest?.quota_change;

  return <details className="usage-panel" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><ChartNoAxesColumnIncreasing size={15} aria-hidden="true" /><span>用量與額度</span>
      <span className="usage-summary">{usage ? `${compact(usage.total.total_tokens)} tokens` : "Token 用量"}
        {weekly && ` · 週已用 ${number(weekly.used_percent)}%`}</span>
      <ChevronDown className={open ? "is-open" : ""} size={14} aria-hidden="true" /></summary>
    <div className="usage-content">
      <div className="usage-heading"><strong>Token 用量</strong>
        <button type="button" className="usage-refresh" disabled={busy} onClick={() => void refresh()}>
          <RefreshCw size={13} aria-hidden="true" />{busy ? "更新中…" : "更新用量"}</button></div>
      {usage ? <><TokenDetails label="本機累積" usage={usage.total} />
        {usage.project && <TokenDetails label="目前影片累積" usage={usage.project} />}</> :
        <p role="status">{usageError || "正在讀取 Token 紀錄…"}</p>}
      <section className="usage-quota" aria-label="Codex 訂閱額度">
        <h3>Codex 訂閱額度{quota?.plan && <span>{quota.plan}</span>}</h3>
        {quota?.available ? <>
          {quota.buckets.map(bucket => <div key={bucket.id} className="usage-bucket">
            {(quota.buckets.length > 1 || bucket.id !== "codex") && <h4>{bucket.name}</h4>}
            {bucket.windows.map(window => <div key={window.id} className="usage-window">
              <div><span>{windowName(window.window_minutes)}</span><strong>已用 {number(window.used_percent)}%</strong></div>
              <progress max={100} value={Math.min(100, window.used_percent)} aria-label={`${bucket.name} ${windowName(window.window_minutes)}已用`} />
              <p>剩餘 {number(Math.max(0, 100 - window.used_percent))}% · {window.resets_at ? `${date(window.resets_at)} 重置` : "尚無重置時間"}</p>
            </div>)}
          </div>)}
          <p className="usage-note">帳號整體用量 · {date(quota.fetched_at)} 更新（本地時間）</p>
        </> : <p role="status">{quotaError || quota?.detail || "正在讀取訂閱額度…"}</p>}
      </section>
      {latest && <section className="usage-estimate" aria-label="最近一次分析用量">
        <h3>最近一次分析</h3>
        <p>本次任務新增 {number(latest.tokens.total_tokens)} tokens</p>
        {change?.windows.length ? change.windows.map((window, index) => <p key={index}>
          {window.bucket_id !== "codex" && `${window.bucket_name} · `}{windowName(window.window_minutes)}：
          {window.status === "estimated" ? `約 +${number(window.percentage_points!)} 個百分點` :
            window.status === "reset" ? "期間額度已重置或調整，無法估算" : "缺少可比較的快照"}
        </p>) : <p>{change?.status === "account_changed" ? "分析期間帳號或方案變更，無法估算。" :
          latest.status === "running" || latest.status === "queued" ? "分析結束後顯示額度差值。" :
            change?.status === "pending" ? "正在更新本次分析的額度差值…" :
            change ? "本次未取得完整額度快照，無法估算。" : "舊任務未記錄額度快照，無法回推。"}</p>}
        <p className="usage-note">差值為分析期間的帳號用量估算；其他 Codex 工作與官方更新延遲也會影響數字。Token 無法直接換算訂閱百分比。</p>
      </section>}
      <details className="usage-notes"><summary>統計範圍與計算方式</summary>
        <p className="usage-note">總量為輸入加輸出；快取與推理已包含在內。包含本機已記錄的分析、聊天與連線測試；舊聊天及未回報用量的中斷回合不計入。刪除影片或重設分析仍保留累積用量。</p>
      </details>
    </div>
  </details>;
}
