import { useEffect, useId, useRef, useState } from "react";
import { ImagePlus, LoaderCircle, Plus, Star, Trash2, X } from "lucide-react";
import { api, ApiError, type GameProfile, type ProfileKind, type ProfileListing, type Project } from "./api";
import "./game-profiles.css";

const kindHelp: Record<ProfileKind, string> = {
  victory: "擊敗 Boss 後這款遊戲會出現的畫面，例如勝利字樣、獎勵或過場。",
  failure: "角色死亡或挑戰失敗時的畫面，例如死亡字樣、讀取畫面。",
  boss: "你想剪的 Boss 戰長什麼樣子。可以先用紅框圈出重點，例如 Boss 血條或名稱。",
};
const captionHint: Record<ProfileKind, string> = {
  victory: "例如：擊敗 Boss 後畫面中央會出現金色「討伐完成」字樣，約停留 3 秒，接著跳出獲得道具的清單；紅框是那行字的位置。",
  failure: "例如：角色倒下後畫面變紅、出現「死亡」字樣，接著是黑底讀取畫面和提示文字，之後回到篝火重生；這種都算失敗。",
  boss: "例如：紅框是畫面下方的 Boss 名稱和大血條，只有 Boss 戰才會出現；一般小怪只有頭上的小血條，不用剪。",
};
const PER_KIND = 3;
const CAPTION_LIMIT = 1000;

function CaptionEditor({ profileId, image, kind, disabled, onChanged }: {
  profileId: string; image: GameProfile["images"][number]; kind: ProfileKind; disabled: boolean;
  onChanged: (profile: GameProfile) => void;
}) {
  const [value, setValue] = useState(image.caption);
  const [state, setState] = useState<"" | "saving" | "saved" | "error">("");
  const dirty = value.trim() !== image.caption;
  async function save() {
    if (!dirty) return;
    setState("saving");
    try {
      onChanged(await api<GameProfile>(`/profiles/${profileId}/images/${image.id}`, "PATCH", { caption: value.trim() }));
      setState("saved");
    } catch { setState("error"); }
  }
  return <label className="profile-caption">
    <span className="sr-only">這張範例的文字說明</span>
    <textarea value={value} maxLength={CAPTION_LIMIT} rows={4} disabled={disabled} placeholder={captionHint[kind]}
      onChange={event => { setValue(event.target.value); setState(""); }} onBlur={() => void save()} />
    <span className="profile-caption-meta" aria-live="polite">
      <span className={state === "error" ? "is-error" : undefined}>
        {state === "saving" ? "儲存中…" : state === "error" ? "儲存失敗，離開欄位時會再試一次" : dirty ? "離開欄位後自動儲存" : state === "saved" ? "已儲存" : "寫得越具體，AI 越容易辨認"}
      </span>
      <span>{value.length}/{CAPTION_LIMIT}</span>
    </span>
  </label>;
}

/** The profile a project analyses with, for labels outside this dialog. */
export function effectiveProfile(project: Project | undefined, listing: ProfileListing | null) {
  if (!project || !listing) return null;
  const id = project.profile_id === undefined || project.profile_id === "default" ? listing.default_id : project.profile_id;
  return listing.profiles.find(profile => profile.id === id) ?? null;
}

async function uploadImage(profileId: string, kind: ProfileKind, file: File) {
  const response = await fetch(`/api/profiles/${profileId}/images?kind=${kind}`, { method: "POST", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream" } });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(typeof data?.detail === "string" ? data.detail : "圖片上傳失敗，請重試。", response.status);
  return data as GameProfile;
}

function ProfileEditor({ profile, kinds, isDefault, onChanged, onDefault, onDeleted }: {
  profile: GameProfile; kinds: ProfileListing["kinds"]; isDefault: boolean;
  onChanged: (profile: GameProfile) => void; onDefault: (id: string | null) => Promise<void>; onDeleted: () => Promise<void>;
}) {
  const [title, setTitle] = useState(profile.title);
  const [notes, setNotes] = useState(profile.notes);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const dirty = title.trim() !== profile.title || notes.trim() !== profile.notes;

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label); setError("");
    try { await work(); } catch (reason) { setError((reason as Error).message); } finally { setBusy(""); }
  }
  const save = () => run("save", async () => onChanged(await api<GameProfile>(`/profiles/${profile.id}`, "PATCH", { title: title.trim(), notes: notes.trim() })));

  return <div className="profile-editor">
    <div className="profile-fields">
      <label>遊戲名稱<input value={title} maxLength={80} onChange={event => setTitle(event.target.value)} /></label>
      <label>補充說明（選填）<textarea value={notes} maxLength={2000} rows={3} onChange={event => setNotes(event.target.value)}
        placeholder="例如：Boss 戰畫面下方會有大血條與名稱；勝利後會出現「任務完成」。" /></label>
      <div className="profile-field-actions">
        <button type="button" className="primary" disabled={!dirty || !title.trim() || !!busy} onClick={() => void save()}>
          {busy === "save" && <LoaderCircle size={14} className="spin" aria-hidden="true" />}儲存名稱與說明</button>
        <button type="button" className="secondary" disabled={!!busy} aria-pressed={isDefault}
          onClick={() => void run("default", () => onDefault(isDefault ? null : profile.id))}>
          <Star size={14} aria-hidden="true" fill={isDefault ? "currentColor" : "none"} />{isDefault ? "新專案預設使用中" : "設為新專案預設"}</button>
        <button type="button" className="profile-delete" disabled={!!busy}
          onClick={() => { if (confirm(`刪除「${profile.title}」和它的所有範例圖片？`)) void run("delete", onDeleted); }}>
          <Trash2 size={14} aria-hidden="true" />刪除設定</button>
      </div>
    </div>
    {error && <p role="alert" className="project-dialog-error">{error}</p>}
    {(Object.keys(kinds) as ProfileKind[]).map(kind => {
      const images = profile.images.filter(image => image.kind === kind);
      return <section key={kind} className="profile-kind" aria-label={kinds[kind]}>
        <header><h3>{kinds[kind]}</h3><span>{images.length}/{PER_KIND}</span></header>
        <p>{kindHelp[kind]}</p>
        <div className="profile-images">
          {images.map(image => <figure key={image.id} className="profile-image">
            <img src={`/api/profiles/${profile.id}/images/${image.id}`} alt={image.caption || kinds[kind]} loading="lazy" />
            <button type="button" className="icon-button profile-image-remove" aria-label="移除這張範例" disabled={!!busy}
              onClick={() => void run("remove", async () => onChanged(await api<GameProfile>(`/profiles/${profile.id}/images/${image.id}`, "DELETE")))}>
              <Trash2 size={15} aria-hidden="true" /></button>
            <figcaption>
              <CaptionEditor profileId={profile.id} image={image} kind={kind} disabled={busy === "remove"} onChanged={onChanged} />
            </figcaption>
          </figure>)}
          {images.length < PER_KIND && <label className={`profile-add-image ${busy ? "is-disabled" : ""}`}>
            {busy === `upload-${kind}` ? <LoaderCircle size={20} className="spin" aria-hidden="true" /> : <ImagePlus size={20} aria-hidden="true" />}
            <span>加入圖片</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={!!busy} onChange={event => {
              const files = Array.from(event.target.files ?? []).slice(0, PER_KIND - images.length);
              event.target.value = "";
              if (files.length) void run(`upload-${kind}`, async () => {
                for (const file of files) onChanged(await uploadImage(profile.id, kind, file));
              });
            }} />
          </label>}
        </div>
      </section>;
    })}
  </div>;
}

export default function GameProfilesDialog({ project, onClose, onProjectChanged, onListing }: {
  project?: Project; onClose: () => void; onProjectChanged: (project: Project) => void; onListing: (listing: ProfileListing) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [listing, setListing] = useState<ProfileListing | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  // Uploads and default changes can overlap; always merge into the latest listing.
  const apply = (next: ProfileListing) => setListing(next);
  const replaceProfile = (profile: GameProfile) => setListing(previous => previous &&
    { ...previous, profiles: previous.profiles.map(item => item.id === profile.id ? profile : item) });
  useEffect(() => { if (listing) onListing(listing); }, [listing, onListing]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal();
    api<ProfileListing>("/profiles").then(result => {
      apply(result);
      setSelected(effectiveProfile(project, result)?.id ?? result.profiles[0]?.id ?? null);
    }).catch(reason => setError((reason as Error).message));
    return () => { element?.close(); previous?.focus({ preventScroll: true }); };
    // Load once per opening; later changes flow through apply().
  }, []);

  const current = listing?.profiles.find(profile => profile.id === selected);
  const defaultProfile = listing?.profiles.find(profile => profile.id === listing.default_id);
  const choice = project?.profile_id === undefined ? "default" : project.profile_id ?? "none";

  async function chooseForProject(value: string) {
    if (!project) return;
    setError("");
    try {
      const profileId = value === "none" ? null : value;
      onProjectChanged(await api<Project>(`/projects/${project.id}/profile`, "PUT", { profile_id: profileId }));
      // Picking a game here also becomes the default for new projects.
      if (value !== "default") setListing(previous => previous && { ...previous, default_id: profileId });
    } catch (reason) { setError((reason as Error).message); }
  }
  async function create() {
    setCreating(true); setError("");
    try {
      const profile = await api<GameProfile>("/profiles", "POST", { title: `新遊戲 ${(listing?.profiles.length ?? 0) + 1}`, notes: "" });
      setListing(previous => previous && { ...previous, profiles: [...previous.profiles, profile] });
      setSelected(profile.id);
    } catch (reason) { setError((reason as Error).message); }
    finally { setCreating(false); }
  }

  return <dialog ref={dialog} className="editor-tools-dialog game-profiles-dialog" aria-labelledby={`${id}-title`}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="editor-tools-heading">
      <div><h2 id={`${id}-title`}>遊戲判斷範例</h2>
        <p>為每款遊戲提供勝利、失敗與 Boss 戰的範例圖，AI 搜尋片段時會一起參考。沒有選用範例時，沿用原本的判斷方式。</p></div>
      <button type="button" className="icon-button" aria-label="關閉遊戲判斷範例" onClick={onClose}><X size={20} aria-hidden="true" /></button>
    </header>
    <div className="editor-tools-content game-profiles-content">
      {project && listing && <label className="preference-row profile-project-choice">
        <span>「{project.title}」搜尋時使用</span>
        <select value={choice} onChange={event => void chooseForProject(event.target.value)}>
          <option value="default">跟隨預設（{defaultProfile?.title ?? "不使用範例"}）</option>
          <option value="none">不使用範例（原本的判斷方式）</option>
          {listing.profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.title}</option>)}
        </select>
      </label>}
      <p className="preference-note">{project && "在這裡選的遊戲也會成為之後新匯入影片（包含 YouTube 自動匯入）的預設。"}變更只套用到之後開始的搜尋；進行中的搜尋會沿用開始時的範例。</p>
      {error && <p role="alert" className="project-dialog-error">{error}</p>}
      {!listing ? !error && <p role="status"><LoaderCircle size={15} className="spin" aria-hidden="true" /> 載入中…</p> : <div className="profile-layout">
        <nav className="profile-list" aria-label="遊戲範例設定">
          {listing.profiles.map(profile => <button key={profile.id} type="button" aria-current={profile.id === selected ? "true" : undefined}
            className={profile.id === selected ? "is-selected" : undefined} onClick={() => setSelected(profile.id)}>
            <strong>{profile.title}</strong>
            <small>{profile.images.length} 張範例{profile.id === listing.default_id ? " · 預設" : ""}</small>
          </button>)}
          <button type="button" className="profile-new" disabled={creating} onClick={() => void create()}>
            {creating ? <LoaderCircle size={15} className="spin" aria-hidden="true" /> : <Plus size={15} aria-hidden="true" />}新增遊戲</button>
        </nav>
        {current ? <ProfileEditor key={current.id} profile={current} kinds={listing.kinds} isDefault={current.id === listing.default_id}
          onChanged={replaceProfile}
          onDefault={async value => {
            const next = await api<ProfileListing>("/profiles/default", "PUT", { profile_id: value });
            setListing(previous => previous && { ...previous, default_id: next.default_id });
          }}
          onDeleted={async () => {
            const next = await api<ProfileListing>(`/profiles/${current.id}`, "DELETE");
            apply(next);
            setSelected(next.profiles[0]?.id ?? null);
            if (project?.profile_id === current.id) onProjectChanged({ ...project, profile_id: "default" });
          }} />
          : <div className="clip-empty"><ImagePlus size={28} aria-hidden="true" /><strong>還沒有遊戲範例</strong>
            <p>按「新增遊戲」，放入勝利、失敗與 Boss 戰的截圖，讓 AI 更懂這款遊戲。</p></div>}
      </div>}
    </div>
  </dialog>;
}
