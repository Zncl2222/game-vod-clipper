import { useEffect, useRef } from "react";
import { ArrowDownToLine, ArrowUpRight, Check, FolderOpen, Keyboard, Scissors, ShieldCheck, Sparkles, X } from "lucide-react";

const steps = [
  { title: "匯入素材", detail: "選擇本機錄影或 YouTube 影片，準備好預覽就能開始。", icon: FolderOpen },
  { title: "找到並核對", detail: "讓 AI 尋找成功挑戰，或手動調整起點、勝利與收尾。", icon: Scissors },
  { title: "留下完整勝利", detail: "看過完整片段、勾選確認，再匯出 MP4。", icon: ArrowDownToLine },
];

export function WorkflowSteps({ ready, reviewed, exported }: { ready: boolean; reviewed: boolean; exported: boolean }) {
  const current = !ready ? 0 : !reviewed ? 1 : 2;
  return <ol className="workflow-steps" aria-label="剪輯流程">
    {["匯入素材", "核對片段", "匯出成品"].map((label, index) => <li key={label}
      className={index < current || (index === 2 && exported && reviewed) ? "complete" : ""}
      aria-current={index === current ? "step" : undefined}>
      <span aria-hidden="true">{index < current || (index === 2 && exported && reviewed) ? <Check aria-hidden="true" size={12} /> : index + 1}</span>{label}
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
      <li><FolderOpen aria-hidden="true" size={20} /><div><h3>01 · 帶入影片</h3><p>按「匯入影片」選擇來源。本機錄影請先放進 downloads/ 資料夾，或貼上 YouTube 網址。背景準備完成後就能預覽。</p></div></li>
      <li><Sparkles aria-hidden="true" size={20} /><div><h3>02 · 尋找成功挑戰</h3><p>按「一鍵搜尋成功挑戰」，或開啟 AI 對話指定範圍。第一次使用 AI，先到「帳號設定」連接帳號並選擇模型。也可以直接手動剪輯。</p></div></li>
      <li><Scissors aria-hidden="true" size={20} /><div><h3>03 · 逐段核對與調整</h3><p>上方「目前剪輯」的實框是匯出範圍，分別標示開始、勝利與結束；結束＝勝利時間＋收尾秒數，斜線區也會保留。下方 AI 編號卡是參考片段，淡虛線僅供對照。點選候選預覽，使用保留／排除整理結果，再將成功候選放入草稿。拖曳開始與勝利位置，或直接輸入時間；點「目前剪輯」放大、點「全片」找其他位置，按「證據」查看探索進度。最後看完完整片段並核對收尾。</p></div></li>
      <li><ArrowDownToLine aria-hidden="true" size={20} /><div><h3>04 · 確認後匯出</h3><p>確認沒有失敗、死亡或跑圖片段，並包含勝利後 5–10 秒。勾選完整看過後按「匯出 MP4」，完成的影片會出現在下方成品區，可播放或下載。</p></div></li>
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
