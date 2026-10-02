import * as Select from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp, Cpu, SlidersHorizontal } from "lucide-react";

export type Model = {
  id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  input_modalities?: string[];
  effort?: string;
  supported_efforts?: string[];
};

const efforts: Record<string, { description: string; level: number }> = {
  none: { description: "直接產生回應", level: 0 },
  minimal: { description: "只做必要的思考", level: 1 },
  low: { description: "較少思考，適合簡單問題", level: 1 },
  medium: { description: "兼顧回應速度與思考深度", level: 2 },
  high: { description: "投入更多思考，處理複雜問題", level: 3 },
  xhigh: { description: "進一步推敲，需要較長時間", level: 4 },
  max: { description: "使用模型最高的思考強度", level: 4 },
  ultra: { description: "投入更充分的思考時間", level: 4 },
};

function EffortBars({ value }: { value?: string }) {
  const level = value ? efforts[value]?.level : undefined;
  if (level === undefined) return <SlidersHorizontal size={14} aria-hidden="true" />;
  return <span className="effort-bars" aria-hidden="true">
    {[1, 2, 3, 4].map(bar => <i key={bar} data-active={bar <= level} />)}
  </span>;
}

function MenuScroll({ direction }: { direction: "up" | "down" }) {
  const Button = direction === "up" ? Select.ScrollUpButton : Select.ScrollDownButton;
  return <Button className="model-menu-scroll">
    {direction === "up" ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
  </Button>;
}

export default function ModelSettings({ models, model, effort, disabled, connected, onModelChange, onEffortChange }: {
  models: Model[];
  model: string;
  effort: string;
  disabled: boolean;
  connected: boolean;
  onModelChange: (value: string) => void;
  onEffortChange: (value: string) => void;
}) {
  const selected = models.find(item => item.id === model);
  const supported = selected?.supported_efforts ?? [];
  const defaultEffort = selected?.effort;
  const effectiveEffort = effort || defaultEffort;

  return <div className="chat-model-settings" role="group" aria-label="AI 回應設定">
    <Select.Root value={model} onValueChange={value => {
      if (models.some(item => item.id === value)) onModelChange(value);
    }} disabled={disabled || !models.length}>
      <Select.Trigger className="model-trigger" aria-label="選擇 AI 模型" title={selected?.name ?? "選擇 AI 模型"}>
        <Cpu className="model-trigger-icon" size={14} aria-hidden="true" />
        <Select.Value placeholder={connected ? "載入模型…" : "連接帳號"}>
          <span className="model-trigger-name">{selected?.name ?? (connected ? "載入模型…" : "連接帳號")}</span>
        </Select.Value>
        <Select.Icon className="model-trigger-chevron"><ChevronDown size={12} /></Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="model-menu" position="popper" side="top" align="start" sideOffset={12} collisionPadding={12}>
          <div className="model-menu-heading"><span className="model-menu-symbol"><Cpu size={16} /></span>
            <div><strong>選擇模型</strong><p>用於聊天與影片搜尋</p></div>
            <span className="model-menu-count">{models.length} 個可用</span>
          </div>
          <MenuScroll direction="up" />
          <Select.Viewport className="model-menu-options">
            {models.map(item => <Select.Item key={item.id} value={item.id} textValue={item.name}
              aria-label={item.name} className="model-menu-option">
              <div className="model-option-copy">
                <div className="model-option-title"><Select.ItemText>{item.name}</Select.ItemText>
                  {item.is_default && <span className="model-default-badge">預設</span>}
                </div>
                {item.description && <span className="model-option-description">{item.description}</span>}
              </div>
              <span className="model-option-check"><Select.ItemIndicator><Check size={15} strokeWidth={2.4} /></Select.ItemIndicator></span>
            </Select.Item>)}
          </Select.Viewport>
          <MenuScroll direction="down" />
          <div className="model-menu-footer">選擇會套用到下一則訊息或搜尋</div>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
    <span className="model-settings-divider" aria-hidden="true" />
    <Select.Root value={effort || "default"} onValueChange={value => {
      if (value === "default") onEffortChange("");
      else if (supported.includes(value)) onEffortChange(value);
    }}
      disabled={disabled || !supported.length}>
      <Select.Trigger className="effort-trigger" aria-label="Reasoning effort"
        title={supported.length ? `Reasoning effort · ${effort || `default${defaultEffort ? ` (${defaultEffort})` : ""}`}` : "此模型使用預設 Reasoning effort"}>
        <EffortBars value={effectiveEffort} />
        <Select.Value><span>{effort || "default"}</span></Select.Value>
        <Select.Icon className="model-trigger-chevron"><ChevronDown size={12} /></Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="model-menu effort-menu" position="popper" side="top" align="start" sideOffset={12} collisionPadding={12}>
          <div className="model-menu-heading"><span className="model-menu-symbol"><SlidersHorizontal size={16} /></span>
            <div><strong>Reasoning effort</strong><p>為回應留多少思考空間</p></div>
          </div>
          <MenuScroll direction="up" />
          <Select.Viewport className="model-menu-options">
            <Select.Item value="default" textValue="default" aria-label="default" className="model-menu-option effort-option">
              <span className="effort-option-icon"><SlidersHorizontal size={15} /></span>
              <div className="model-option-copy"><Select.ItemText>default</Select.ItemText>
                <span className="model-option-description">{defaultEffort ? `跟隨模型設定 · ${defaultEffort}` : "使用模型的預設設定"}</span>
              </div>
              <span className="model-option-check"><Select.ItemIndicator><Check size={15} strokeWidth={2.4} /></Select.ItemIndicator></span>
            </Select.Item>
            <Select.Separator className="model-menu-separator" />
            {supported.map(value => <Select.Item key={value} value={value} textValue={value}
              aria-label={value} className="model-menu-option effort-option">
              <span className="effort-option-icon"><EffortBars value={value} /></span>
              <div className="model-option-copy"><Select.ItemText>{value}</Select.ItemText>
                {efforts[value] && <span className="model-option-description">{efforts[value].description}</span>}
              </div>
              <span className="model-option-check"><Select.ItemIndicator><Check size={15} strokeWidth={2.4} /></Select.ItemIndicator></span>
            </Select.Item>)}
          </Select.Viewport>
          <MenuScroll direction="down" />
          <div className="model-menu-footer">思考越深入，通常需要越多時間</div>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  </div>;
}
