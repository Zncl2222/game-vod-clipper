import type { Draft } from "./api";

export function draftStorageKey(projectId: string, clipId: string | null) {
  return clipId ? `bosscut:clip-draft:${projectId}:${clipId}` : `bosscut:draft:${projectId}`;
}

export function candidateDraftStorageKey(projectId: string, generation: number) {
  return `bosscut:candidate-drafts:${projectId}:${generation}`;
}

export function readCandidateDrafts(key: string): Map<string, Draft> {
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? "{}");
    return new Map(Object.entries(saved).filter(([id, value]) => {
      const draft = value as Draft | null;
      return draft?.candidate_id === id && [draft.start, draft.victory, draft.postroll]
        .every(value => typeof value === "number" && Number.isFinite(value))
        && ["manual", "agent"].includes(draft.origin);
    }) as [string, Draft][]);
  } catch { return new Map(); }
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
