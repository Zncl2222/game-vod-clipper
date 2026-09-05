export type Draft = {
  start: number;
  victory: number;
  postroll: number;
  reviewed: boolean;
  revision: number;
  origin: "manual" | "agent";
};
export type Project = {
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
  id: string;
  project_id: string;
  kind: "prepare" | "export" | "analyze";
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  draft: Draft | null;
  result?: AnalysisResult;
};
export type AnalysisResult = {
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
export type Source = { path: string; name: string; size: number };

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
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "輸入格式不正確，請檢查欄位。",
    );
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
