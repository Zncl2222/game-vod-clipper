import { useSyncExternalStore } from "react";
import type { DownloadQualityValue } from "../components/media/DownloadQuality";

export type ExportQuality = "max" | "high" | "balanced" | "fast";
export type Preferences = {
  exportQuality: ExportQuality;
  downloadQuality: DownloadQualityValue;
  notifyOnExport: boolean;
  // Last choices in the YouTube import dialog, kept until the user changes them.
  importAutoAnalyze: boolean;
  importModel: string;
};

// Numbers measured on a YouTube AV1 1080p60 source; time is relative to the fast preset.
export const exportQualityOptions: { value: ExportQuality; label: string; summary: string; detail: string }[] = [
  { value: "max", label: "最高畫質", summary: "H.264 CRF 12 · medium", detail: "與原片幾乎無差異（約 52 dB）· 檔案最大 · 匯出約 2.5 倍時間" },
  { value: "high", label: "高畫質（建議）", summary: "H.264 CRF 14 · medium", detail: "肉眼看不出差異（約 51 dB）· 檔案約 2 倍 · 匯出約 2.4 倍時間" },
  { value: "balanced", label: "平衡", summary: "H.264 CRF 14 · veryfast", detail: "非常接近原片（約 49 dB）· 檔案約 1.7 倍 · 匯出速度與「快速」相同" },
  { value: "fast", label: "快速", summary: "H.264 CRF 18 · veryfast", detail: "細節略有損失（約 47 dB）· 檔案最小 · 匯出最快" },
];
export const exportQualityLabel = (value?: string | null) =>
  exportQualityOptions.find(option => option.value === value)?.label.replace("（建議）", "") ?? "快速";

const KEY = "bosscut:preferences";
const DEFAULTS: Preferences = { exportQuality: "high", downloadQuality: "best", notifyOnExport: true, importAutoAnalyze: true, importModel: "" };
const listeners = new Set<() => void>();
let cached: Preferences | null = null;

function read(): Preferences {
  if (cached) return cached;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    cached = {
      exportQuality: exportQualityOptions.some(option => option.value === saved.exportQuality) ? saved.exportQuality : DEFAULTS.exportQuality,
      downloadQuality: ["best", "2160", "1440", "1080", "720", "480"].includes(saved.downloadQuality) ? saved.downloadQuality : DEFAULTS.downloadQuality,
      notifyOnExport: typeof saved.notifyOnExport === "boolean" ? saved.notifyOnExport : DEFAULTS.notifyOnExport,
      importAutoAnalyze: typeof saved.importAutoAnalyze === "boolean" ? saved.importAutoAnalyze : DEFAULTS.importAutoAnalyze,
      importModel: typeof saved.importModel === "string" ? saved.importModel : DEFAULTS.importModel,
    };
  } catch { cached = DEFAULTS; }
  return cached;
}

export function getPreferences() { return read(); }

export function setPreferences(changes: Partial<Preferences>) {
  cached = { ...read(), ...changes };
  try { localStorage.setItem(KEY, JSON.stringify(cached)); } catch { /* Preferences still apply for this session. */ }
  listeners.forEach(listener => { listener(); });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Keep other open tabs in sync.
  const storage = (event: StorageEvent) => { if (event.key === KEY) { cached = null; listener(); } };
  window.addEventListener("storage", storage);
  return () => { listeners.delete(listener); window.removeEventListener("storage", storage); };
}

export function usePreferences() {
  return useSyncExternalStore(subscribe, read, () => DEFAULTS);
}
