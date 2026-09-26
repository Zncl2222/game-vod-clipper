import { useId } from "react";
import "./download-quality.css";

export const qualityOptions = [
  ["best", "最高可用畫質（預設）"],
  ["2160", "最高 2160p · 4K"],
  ["1440", "最高 1440p · QHD"],
  ["1080", "最高 1080p"],
  ["720", "最高 720p"],
  ["480", "最高 480p"],
] as const;
export type DownloadQualityValue = typeof qualityOptions[number][0];
export function qualityLabel(value = "best") {
  return value === "best" ? "最高可用畫質" : qualityOptions.find(([key]) => key === value)?.[1] ?? "最高可用畫質";
}

export default function DownloadQuality({ value, onChange, disabled = false }: {
  value: DownloadQualityValue; onChange: (value: DownloadQualityValue) => void; disabled?: boolean;
}) {
  const id = useId();
  return <div className="download-quality">
    <label htmlFor={id}>保留畫質</label>
    <select id={id} value={value} disabled={disabled} aria-describedby={`${id}-help`} onChange={event => onChange(event.target.value as DownloadQualityValue)}>
      {qualityOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select>
    <p id={`${id}-help`}>預設下載最高可用畫質。指定上限時，選用不超過該解析度的最佳版本；畫質越高，需要的下載時間與空間越多。</p>
    <p>成品保留原片解析度與幀率，不受 720p 預覽影響。此設定只適用於新匯入的影片，並會記住到下次匯入。</p>
  </div>;
}
