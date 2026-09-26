import type { Project } from "./api";

export function playbackFile(project: Project) {
  return project.playback === "source" ? "source" : "preview.mp4";
}

/** Average-frame-duration stepping, not a frame-accurate decoder (especially for VFR). */
export function previewStep(project: Project) {
  const fps = project.playback === "source" ? project.frame_rate : 30;
  return fps && Number.isFinite(fps) && fps > 0 ? 1 / fps : 1 / 30;
}

export function playbackError(project: Project, code?: number) {
  if (code === 2) return "影片讀取中斷，請確認服務與原片檔案仍可存取，再重新載入。";
  if (project.playback !== "source") return "預覽影片載入失敗，請確認服務仍在運作。";
  const format = [project.source_container, project.video_codec, project.audio_codec].filter(Boolean).join(" / ");
  return `無法直接播放此原片${format ? `（${format}）` : ""}。請確認檔案可讀取；若格式不受支援，可改用支援此格式的瀏覽器。原片已保留，仍可分析與匯出；不會自動製作整支預覽。`;
}
