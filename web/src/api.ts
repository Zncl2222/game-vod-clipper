export type Draft = {
  start: number;
  victory: number;
  postroll: number;
  reviewed: boolean;
  revision: number;
  origin: "manual" | "agent";
  candidate_id?: string | null;
  candidate_revision?: number | null;
  manually_adjusted?: boolean | null;
};
export type Project = {
  youtube_analysis_error?: string | null;
  review_candidates?: NumberedCandidate[];
  candidate_reviews?: Record<string, CandidateReview>;
  analysis_generation?: number;
  editor_generation?: number;
  id: string;
  title: string;
  ready: boolean;
  duration?: number;
  width?: number;
  height?: number;
  thumbnails: { file: string; time: number }[];
  draft?: Draft;
};
export type Job = {
  quota_change?: QuotaChange;
  edit_draft?: Draft;
  source_job_id?: string | null;
  progress_reset?: boolean;
  candidates?: CandidateSegment[];
  model?: string;
  id: string;
  project_id: string;
  kind: "prepare" | "export" | "analyze";
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  draft: Draft | null;
  result?: AnalysisResult;
  created?: number;
  started_at?: number;
  finished_at?: number;
  heartbeat_at?: number;
  last_activity_at?: number;
  phase?: string;
  current_round?: number;
  rounds?: number;
  frames?: number;
  review_stage?: string;
  sample_every?: number;
  pending_packets?: number;
  resumable?: boolean;
  coverage?: Coverage[];
  evidence?: { time: number; event: string }[];
  sample_start?: number;
  sample_end?: number;
  activity?: { time: number; message: string }[];
};
export type Coverage = { start: number; end: number; every: number };
export type AnalysisResult = {
  candidates?: CandidateSegment[];
  can_continue?: boolean;
  review_complete?: boolean;
  completion_reason?: "pending_review" | "evidence_exhausted" | "review_complete";
  coverage?: Coverage[];
  checks?: Record<string, boolean>;
  project_id?: string;
  status: "candidate" | "not_found" | "uncertain";
  start: number | null;
  victory: number | null;
  postroll: number;
  boss: string;
  summary: string;
  warnings: string[];
  evidence: { time: number; event: string }[];
  model: string;
  frames: number;
  rounds: number;
};
export type State = { projects: Project[]; jobs: Job[] };

export type TokenUsage = {
  input_tokens: number; output_tokens: number; total_tokens: number;
  cached_input_tokens: number; reasoning_output_tokens: number; records: number;
};
export type QuotaChange = {
  status: "pending" | "estimated" | "unavailable" | "account_changed";
  windows: { bucket_id: string; bucket_name: string; window_minutes: number | null;
    status: "estimated" | "reset" | "unavailable"; percentage_points: number | null }[];
};
export type UsageSummary = {
  total: TokenUsage; project: TokenUsage | null;
  latest_analysis: { id: string; status: string; tokens: TokenUsage; quota_change: QuotaChange | null } | null;
};
export type RateLimits = {
  available: boolean; fetched_at: number; plan: string | null; detail: string;
  buckets: { id: string; name: string; windows: {
    id: string; used_percent: number; window_minutes: number | null; resets_at: number | null;
  }[] }[];
};

export function finishedClips(projectId: string, jobs: Job[]) {
  return jobs.filter(job => job.project_id === projectId && job.kind === "export" && job.status === "succeeded" && job.draft)
    .sort((a, b) => (a.created ?? 0) - (b.created ?? 0) || a.id.localeCompare(b.id));
}

export function sameClipRange(a: Pick<Draft, "start" | "victory" | "postroll">, b: Pick<Draft, "start" | "victory" | "postroll">) {
  return (["start", "victory", "postroll"] as const).every(key => Math.abs(a[key] - b[key]) < .001);
}

export function candidateExports(projectId: string, candidate: NumberedCandidate, jobs: Job[]) {
  const ids = new Set([candidate.id, ...(candidate.aliases ?? [])]);
  return finishedClips(projectId, jobs).filter(job => {
    const draft = job.draft!;
    if (draft.candidate_id) return ids.has(draft.candidate_id);
    // Older exports have no candidate identity. Match exact boundaries, never overlap.
    return [candidate, candidate.ai_range].some(range => range?.victory != null && sameClipRange(draft, {
      start: range.start, victory: range.victory, postroll: range.postroll ?? 8,
    }));
  });
}

export function editableClipDraft(job: Job): Draft {
  return job.edit_draft ?? { ...job.draft!, revision: 0, reviewed: false };
}
export type CandidateReview = "pending" | "keep" | "reject";
export type CandidateEdit = { start: number; victory: number; postroll: number; revision: number; updated_at: number };
export type CandidateSegment = {
  aliases?: string[];
  manual_edit?: CandidateEdit;
  ai_range?: { start: number; end: number; victory: number | null; postroll?: number | null };
  id: string; start: number; end: number; victory: number | null;
  verification?: "unverified" | "blocked" | "verified";
  postroll?: number;
  kind: "possible_win" | "fight" | "death_retry" | "unknown";
  confidence: "low" | "medium" | "high";
  boss: string; summary: string; warnings: string[];
  evidence: { time: number; event: string }[];
};
export type NumberedCandidate = CandidateSegment & { number: number; review: CandidateReview };

export function reviewCandidates(project: Project, jobs: Job[]): NumberedCandidate[] {
  if (project.review_candidates) return project.review_candidates;
  const found = new Map<string, CandidateSegment>();
  for (const job of [...jobs].reverse()) {
    if (job.project_id !== project.id || job.kind !== "analyze") continue;
    const r = job.result;
    if (r?.project_id && r.project_id !== project.id) continue;
    let segments = job.candidates ?? r?.candidates ?? [];
    if (!segments.length && r && r.start !== null && r.victory !== null) {
      segments = [{ id: `${job.id}:legacy`, start: r.start, end: Math.min(project.duration!, r.victory + r.postroll),
        victory: r.victory, postroll: r.postroll, kind: "possible_win", confidence: "low", boss: r.boss, summary: r.summary,
        warnings: r.warnings, evidence: r.evidence }];
    }
    for (const segment of segments) {
      if ([segment.start, segment.end].every(Number.isFinite) && segment.start >= 0 && segment.start < segment.end && segment.end <= project.duration!) {
        // Older servers have no host-verified projection. Keep their annotations
        // provisional and retain a matching result's rejection warnings.
        const matches = segment.victory !== null && segment.start === r?.start && segment.victory === r?.victory;
        found.set(segment.id, { ...segment, verification: matches && r.status !== "candidate" ? "blocked" : "unverified",
          postroll: matches ? r.postroll : segment.postroll,
          warnings: [...new Set([...segment.warnings, ...(matches ? r.warnings : [])])] });
      }
    }
  }
  return [...found.values()].map((segment, i) => ({ ...segment, number: i + 1, review: project.candidate_reviews?.[segment.id] ?? "pending" }));
}
export type Source = { path: string; name: string; size: number };
export type VideoStorage = {
  bytes: number; files: number; incomplete: boolean; updated_at: number;
  categories: Record<"sources" | "exports" | "previews", { bytes: number; files: number }>;
};

export function apiError(path: string, status: number, detail?: unknown): string {
  if (status === 404 && path.startsWith("/codex")) {
    return "目前連接的後端沒有這個 AI 功能。請重新啟動 BossCut 後端，再重新整理頁面；若仍出現此訊息，請確認前端連到正確的後端位址。";
  }
  return typeof detail === "string" ? detail : "服務回應異常，請檢查後端連線與輸入內容。";
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(apiError(path, response.status, data?.detail), response.status,
      typeof data?.code === "string" ? data.code : undefined);
  if (data === null) throw new Error("服務未傳回有效資料，請檢查後端連線。");
  return data;
}

export function time(seconds: number, precise = false) {
  const safe = Math.max(0, seconds);
  const hours = Math.floor(safe / 3600)
    .toString()
    .padStart(2, "0");
  const minutes = Math.floor((safe % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const sec = Math.floor(safe % 60)
    .toString()
    .padStart(2, "0");
  return `${hours}:${minutes}:${sec}${
    precise
      ? "." +
        Math.floor((safe % 1) * 1000)
          .toString()
          .padStart(3, "0")
      : ""
  }`;
}

export function media(project: Project, file: string) {
  return `/api/projects/${project.id}/media/${file}`;
}

export const active = (job: Job) => ["queued", "running"].includes(job.status);
export const currentAnalysis = (job: Job) => job.kind === "analyze" && !job.progress_reset;

// Older jobs retain the original diagnostic in storage; show an actionable summary.
export function analysisError(error: string): string {
  return /ffmpeg[\s\S]*timed out after/i.test(error)
    ? "擷取抽樣畫面逾時，尚未進入該輪 AI 判讀。抽樣方式已更新，可在電腦空閒時重試或縮小搜尋範圍。"
    : error;
}
