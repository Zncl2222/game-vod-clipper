import { useEffect, useRef } from "react";
import { ArrowDownToLine, ArrowUpRight, Check, FolderOpen, Keyboard, Scissors, ShieldCheck, Sparkles, X } from "lucide-react";

const steps = [
  { title: "匯入素材", detail: "選擇本機錄影或 YouTube 影片，準備好預覽就能開始。", icon: FolderOpen },
  { title: "找到並核對", detail: "讓 AI 尋找成功挑戰，或手動調整起點、勝利與收尾。", icon: Scissors },
  { title: "留下完整勝利", detail: "調整好片段後直接匯出 MP4，完成後會標記已匯出。", icon: ArrowDownToLine },
];

export function WorkflowSteps({ ready, exported }: { ready: boolean; exported: boolean }) {
  const current = !ready ? 0 : !exported ? 1 : 2;
  return <ol className="workflow-steps" aria-label="剪輯流程">
    {["匯入素材", "核對片段", "匯出成品"].map((label, index) => <li key={label}
      className={index < current || (index === 2 && exported) ? "complete" : ""}
      aria-current={index === current ? "step" : undefined}>
      <span aria-hidden="true">{index < current || (index === 2 && exported) ? <Check aria-hidden="true" size={12} /> : index + 1}</span>{label}
    </li>)}
  </ol>;
}

export function WelcomeScreen({ onImport, onGuide }: { onImport: () => void; onGuide: () => void }) {
  return <section className="welcome-screen" aria-labelledby="welcome-title">
    <div className="welcome-hero">
      <span className="studio-kicker"><span className="tiny-dot" /> YOUR NEXT GREAT CUT</span>
      <h2 id="welcome-title">漫長的實況，<br />值得重播的<span>一戰。</span></h2>
      <p>從第一個交鋒，到最後一刻勝利。<br />找到成功的那一次，剪出完整的高光時刻。</p>
      <div className="welcome-actions">
        <button className="primary" onClick={onImport}><FolderOpen aria-hidden="true" size={18} />建立第一個剪輯</button>
        <button className="text-button" onClick={onGuide}>看看怎麼用 <ArrowUpRight size={15} aria-hidden="true" /></button>
      </div>
      <div className="welcome-privacy"><ShieldCheck aria-hidden="true" size={16} />原片留在本機，預覽與匯出於此裝置處理。</div>
    </div>
    <div className="welcome-visual" aria-hidden="true">
      <div className="visual-topline"><span>BOSSCUT / EDIT STUDIO</span><span className="visual-live">READY TO CUT</span></div>
      <div className="visual-frame"><div className="visual-crosshair" /><Scissors aria-hidden="true" size={44} strokeWidth={1.25} /><span>KEEP THE WIN.</span></div>
      <div className="visual-ruler"><span>00:00</span><span>01:00</span><span>02:00</span></div>
      <div className="visual-track"><div className="visual-selection"><span>成功挑戰</span><i /></div></div>
      <div className="visual-caption"><span>THE FULL FIGHT</span><span>+ 5–10s 收尾</span></div>
    </div>
    <div className="welcome-steps">{steps.map(({ title, detail, icon: Icon }, index) => <div key={title}>
      <div className="welcome-step-heading"><Icon aria-hidden="true" size={19} /><span>0{index + 1}</span></div>
      <h3>{title}</h3><p>{detail}</p>
    </div>)}</div>
  </section>;
}

export function WorkspaceGuide({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={dialog} className="guide-dialog" aria-labelledby="guide-title" onCancel={onClose}>
    <div className="guide-heading"><span className="studio-kicker">BOSSCUT FIELD GUIDE</span>
      <button className="icon-button" aria-label="關閉使用指南" onClick={onClose}><X aria-hidden="true" size={20} /></button></div>
    <h2 id="guide-title">從一支實況，到一場勝利。</h2>
    <p className="guide-intro">你的桌面剪輯工作區，照自己的步調完成。</p>
    <ol className="guide-steps">
      <li><FolderOpen aria-hidden="true" size={20} /><div><h3>01 · 帶入影片</h3><p>按「我的 YouTube」連接頻道、選取直播，勾選「匯入後自動找片段」即可接著分析。也能按「匯入影片」貼上網址或選擇 downloads/ 裡的本機錄影。</p></div></li>
      <li><Sparkles aria-hidden="true" size={20} /><div><h3>02 · 尋找成功挑戰</h3><p>按「一鍵搜尋成功挑戰」，或開啟 AI 對話指定範圍。第一次使用 AI，先到「帳號設定」連接帳號並選擇模型。也可以直接手動剪輯。</p></div></li>
      <li><Scissors aria-hidden="true" size={20} /><div><h3>03 · 逐段核對與調整</h3><p>上方「目前剪輯」的實框是匯出範圍，分別標示開始、勝利與結束；結束＝勝利時間＋收尾秒數。點選候選預覽，按「編輯區間」載入草稿，再拖曳邊界或輸入時間。保留／排除只用來整理候選，不影響匯出。點「目前剪輯」放大、點「全片」找其他位置，按「證據」查看探索進度。</p></div></li>
      <li><ArrowDownToLine aria-hidden="true" size={20} /><div><h3>04 · 匯出與上傳</h3><p>調整好區間、保留勝利後 5–10 秒，直接按「匯出 MP4」，會自動儲存草稿。匯出成功後，對應候選會標記「已匯出」。到右側「成品」選擇下載，或按「上傳 YouTube」確認標題與觀看權限後上傳；預設為私人影片。</p></div></li>
    </ol>
    <div className="guide-shortcuts"><h3><Keyboard aria-hidden="true" size={17} />桌面快捷操作</h3>
      <dl><div><dt><kbd>I</kbd></dt><dd>將播放位置設為開始</dd></div><div><dt><kbd>O</kbd></dt><dd>將播放位置設為勝利</dd></div>
        <div><dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>前後移動一個預覽格</dd></div><div><dt><kbd>Esc</kbd></dt><dd>離開劇院模式或關閉視窗</dd></div>
        <div><dt><kbd>Ctrl / ⌘</kbd> + 滾輪</dt><dd>縮放時間軸</dd></div><div><dt><kbd>F2</kbd></dt><dd>重新命名焦點所在的專案</dd></div></dl>
      <p>時間快捷鍵適用於未輸入文字時。側欄頂部按鈕可收合／展開，左右分隔線可調整寬度。影片與剪輯區之間的分隔線可上下拖曳，也可用旁邊的 ＋／− 調整高度；方向鍵微調，雙擊還原。調整的大小會記住。</p>
    </div>
    <button className="primary guide-done" onClick={onClose}>開始剪輯</button>
  </dialog>;
}
