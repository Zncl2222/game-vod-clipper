import type { Draft } from "./api";

export function draftStorageKey(projectId: string, clipId: string | null) {
  return clipId ? `bosscut:clip-draft:${projectId}:${clipId}` : `bosscut:draft:${projectId}`;
}

export function readWorkingDraft(projectId: string, clipId: string | null, baseline: Draft): Draft {
  try {
    const saved = JSON.parse(localStorage.getItem(draftStorageKey(projectId, clipId)) ?? "null");
    if (saved && saved.revision === baseline.revision &&
        [saved.start, saved.victory, saved.postroll].every(value => typeof value === "number" && Number.isFinite(value)) &&
        typeof saved.reviewed === "boolean" && ["manual", "agent"].includes(saved.origin)) return saved;
  } catch { /* A corrupt or inaccessible browser cache must not prevent editing. */ }
  return baseline;
}
