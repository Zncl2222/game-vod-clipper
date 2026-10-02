import { useEffect, useRef } from "react";
import { active, type Job, type Project } from "./api";
import { getPreferences, type ExportQuality } from "./preferences";

const SPEED_KEY = "bosscut:export-speed";

export const clipLength = (job: Pick<Job, "draft">) =>
  job.draft ? Math.max(0, job.draft.victory + job.draft.postroll - job.draft.start) : 0;

// Encoding speed depends on source resolution and the x264 preset, so remember it per height and quality on this device only.
function speeds(): Record<string, number> {
  try {
    const parsed = JSON.parse(localStorage.getItem(SPEED_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch { return {}; }
}

const speedKey = (project: Project, quality: ExportQuality) => `${project.height ?? "unknown"}:${quality}`;

export function rememberExportSpeed(project: Project, quality: ExportQuality, speed: number | null | undefined) {
  if (!speed || !Number.isFinite(speed) || speed <= 0) return;
  const key = speedKey(project, quality), known = speeds();
  // Blend with the previous run so one unusually busy export does not swing the estimate.
  known[key] = known[key] ? known[key] * .5 + speed * .5 : speed;
  try { localStorage.setItem(SPEED_KEY, JSON.stringify(known)); } catch { /* Estimates are optional. */ }
}

export function estimateExportSeconds(project: Project, quality: ExportQuality, seconds: number) {
  const speed = speeds()[speedKey(project, quality)];
  return speed && seconds > 0 ? seconds / speed : null;
}

export function requestExportNotifications() {
  try {
    if (getPreferences().notifyOnExport && "Notification" in window && Notification.permission === "default")
      void Notification.requestPermission();
  } catch { /* Notifications are a convenience; the inline panel still reports the outcome. */ }
}

function notify(job: Job, project?: Project) {
  try {
    if (!getPreferences().notifyOnExport || !("Notification" in window) || Notification.permission !== "granted") return;
    if (document.visibilityState === "visible" && document.hasFocus()) return;
    const done = job.status === "succeeded";
    const name = job.draft?.title?.trim() || project?.title || "剪輯";
    const notification = new Notification(done ? "匯出完成" : "匯出未完成", {
      body: done ? `${name} 已可下載。` : `${name}：${job.error || "請回到 BossCut 查看並重試。"}`,
      tag: `bosscut-export-${job.id}`,
    });
    notification.onclick = () => { window.focus(); notification.close(); };
  } catch { /* Some browsers only allow notifications from a service worker. */ }
}

/** Notify once when an export this session watched leaves the queue while the tab is in the background. */
export function useExportNotifications(jobs: Job[], projects: Project[]) {
  const seen = useRef<Map<string, string> | null>(null);
  useEffect(() => {
    const previous = seen.current;
    seen.current = new Map(jobs.filter(job => job.kind === "export").map(job => [job.id, job.status]));
    if (!previous) return;
    for (const job of jobs) {
      const before = previous.get(job.id);
      if (job.kind !== "export" || !before || !["queued", "running"].includes(before) || active(job)) continue;
      notify(job, projects.find(project => project.id === job.project_id));
    }
  }, [jobs, projects]);
}
