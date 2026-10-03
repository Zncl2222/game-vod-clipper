import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

const project = { id: "yt-project", title: "艾爾登法環 · 女武神挑戰", ready: true, duration: 7200, thumbnails: [],
  draft: { start: 120, victory: 320, postroll: 8, reviewed: true, revision: 2, origin: "manual" } };
const exported = { id: "finished-clip", project_id: project.id, kind: "export", status: "succeeded", stage: "已完成", progress: 100, error: null, draft: project.draft };
const channel = { id: "my-channel", title: "阿宇的遊戲實況" };
const live = [
  { id: "abcdefghijk", title: "艾爾登法環｜終於打贏女武神！", duration: 12480, ended_at: "2026-09-19T16:00:00Z", privacy: "public", available: true, reason: "", project_id: null },
  { id: "lmnopqrstuv", title: "黑暗靈魂 3｜無名王練習", duration: 8620, ended_at: "2026-09-18T16:00:00Z", privacy: "unlisted", available: true, reason: "", project_id: "yt-project" },
  { id: "private1234", title: "私人存檔", duration: 7200, ended_at: "2026-09-17T16:00:00Z", privacy: "private", available: false, reason: "私人影片請改用本機錄影", project_id: null },
];

test.beforeAll(async () => { await mkdir("../runs/youtube-ux", { recursive: true }); });

async function setup(page: Page, connected = true, clipTitle?: string) {
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  const account = { configured: connected, connected, channel: connected ? channel : null, pending: false, reconnect_required: false, error: null,
    playlist_write_enabled: connected,
    watch: { enabled: false, auto_analyze: true, model: "vision", last_checked: null, error: null }, uploads: [] as any[], imports: [] as any[] };
  let rejectImport = false, rejectUpload = false, rejectBatch = false;
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    window.addEventListener("error", event => { if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation(); }, true);
    const Native = window.EventSource;
    window.EventSource = class extends Native { set onerror(_handler: unknown) {} };
  });
  await page.route("https://i.ytimg.com/**", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#20342c"/><circle cx="160" cy="85" r="30" fill="#4d773b"/><path d="M152 68l25 17-25 17z" fill="#c5ef83"/></svg>' }));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push({ path, body: request.postDataJSON() });
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ projects: [project], jobs: [{ ...exported, draft: { ...exported.draft, title: clipTitle } }] })}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", detail: "已連接" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "vision", name: "目前的影像模型", is_default: true, input_modalities: ["text", "image"] }] } });
    if (path === "/api/youtube") return route.fulfill({ json: account });
    if (path === "/api/youtube/config") { account.configured = true; return route.fulfill({ json: account }); }
    if (path === "/api/youtube/login/cancel") { account.pending = false; return route.fulfill({ json: account }); }
    if (path === "/api/youtube/login") { account.pending = true; return route.fulfill({ json: { url: "https://accounts.google.com/o/oauth2/v2/auth?state=test" } }); }
    if (path === "/api/youtube/disconnect") { account.connected = false; account.channel = null; return route.fulfill({ json: { ...account, message: "已中斷連接" } }); }
    if (path === "/api/youtube/broadcasts") return route.fulfill({ json: { items: live, next_page_token: "" } });
    if (path === "/api/youtube/playlists") return route.fulfill({ json: { items: [
      { id: "PLboss", title: "艾爾登法環・完整勝利", privacy: "private", count: 12 },
    ], next_page_token: "" } });
    if (path === "/api/youtube/imports") {
      if (rejectBatch) return route.fulfill({ status: 429, json: { detail: "等待匯入的影片已滿，請稍後再試。" } });
      const body = request.postDataJSON();
      let added = 0, existing = 0;
      for (const video of body.videos) {
        if (account.imports.some(item => item.video_id === video.id)) { existing++; continue; }
        account.imports.push({ id: video.id, video_id: video.id, title: video.title, channel,
          status: "queued", project_id: null, error: null, auto_analyze: body.auto_analyze, progress: 0, download_quality: body.download_quality });
        added++;
      }
      await new Promise(resolve => setTimeout(resolve, 180));
      return route.fulfill({ status: 202, json: { added, existing, items: account.imports } });
    }
    const queueAction = path.match(/^\/api\/youtube\/imports\/([^/]+)\/(cancel|retry)$/);
    if (queueAction) {
      const item = account.imports.find(item => item.id === queueAction[1]);
      item.status = queueAction[2] === "cancel" ? "cancelled" : "queued";
      item.error = null;
      return route.fulfill({ json: account });
    }
    if (path.endsWith("/import")) {
      if (rejectImport) return route.fulfill({ status: 429, json: { detail: "任務佇列已滿，請稍後再試。" } });
      await new Promise(resolve => setTimeout(resolve, 180));
      return route.fulfill({ status: 202, json: { project_id: project.id } });
    }
    if (path === "/api/youtube/watch") { Object.assign(account.watch, request.postDataJSON()); return route.fulfill({ json: account.watch }); }
    if (path === "/api/youtube/uploads/finished-clip") {
      if (rejectUpload) return route.fulfill({ status: 503, json: { detail: "網路暫時中斷，請再試一次。" } });
      const upload = { ...request.postDataJSON(), channel, id: "upload-1", export_id: exported.id, project_id: project.id,
        playlist_title: "艾爾登法環・完整勝利", playlist_status: request.postDataJSON().playlist_id ? "pending" : null,
        status: "uploading", progress: 35, error: null, video_id: null, created: 1 };
      account.uploads = [upload];
      await new Promise(resolve => setTimeout(resolve, 180));
      return route.fulfill({ status: 202, json: upload });
    }
    if (path.endsWith("/playlist/retry")) {
      account.uploads[0].playlist_status = "added"; account.uploads[0].playlist_error = null;
      return route.fulfill({ json: account.uploads[0] });
    }
    if (path.endsWith("/pause")) { account.uploads[0].status = "paused"; return route.fulfill({ json: account.uploads[0] }); }
    if (path.endsWith("/resume")) { account.uploads[0].status = "succeeded"; account.uploads[0].video_id = "uploaded123"; return route.fulfill({ json: account.uploads[0] }); }
    return route.fulfill({ status: 404, json: { detail: "測試路由不存在" } });
  });
  await page.goto("/");
  await expect(page.getByText("工作區已連線")).toBeVisible();
  return { account, writes, errors, failImport: (value: boolean) => { rejectImport = value; },
    failUpload: (value: boolean) => { rejectUpload = value; }, failBatch: (value: boolean) => { rejectBatch = value; } };
}

async function open(page: Page) {
  const mobileChat = page.locator(".chat-mobile-toggle");
  if (await mobileChat.isVisible() && await mobileChat.getAttribute("aria-expanded") === "true") await page.getByRole("button", { name: "關閉 AI 對話", exact: true }).click();
  await page.getByRole("button", { name: "我的 YouTube", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "我的 YouTube", exact: true })).toBeVisible();
}

test("first-time setup is explained, invalid JSON is recoverable, Escape restores focus", async ({ page }) => {
  const state = await setup(page, false);
  await open(page);
  await expect(page.getByRole("button", { name: "使用 Google 連接" })).toBeDisabled();
  await expect(page.getByText("首次連接 · 設定一次即可")).toBeVisible();
  await page.screenshot({ path: "../runs/youtube-ux/setup.png", fullPage: true });
  await page.getByLabel("選擇剛下載的設定檔").setInputFiles({ name: "wrong.json", mimeType: "application/json", buffer: Buffer.from("oops") });
  await expect(page.getByRole("alert")).toContainText("不是有效的 JSON");
  await page.getByLabel("選擇剛下載的設定檔").setInputFiles({ name: "client.json", mimeType: "application/json", buffer: Buffer.from('{"installed":{"client_id":"demo.apps.googleusercontent.com","client_secret":"test"}}') });
  await expect(page.getByRole("button", { name: "使用 Google 連接" })).toBeEnabled();
  expect(state.writes.map(item => item.path)).toEqual(["/api/youtube/config"]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "我的 YouTube", exact: true })).toBeFocused();
  expect(state.errors).toEqual([]);
});

test("live permission errors keep login, explain the fix, and retry the failed list", async ({ page }) => {
  const state = await setup(page);
  let blocked = true, listRequests = 0;
  await page.route("**/api/youtube/broadcasts", async route => {
    listRequests++;
    return blocked ? route.fulfill({ status: 403, json: { code: "liveStreamingNotEnabled",
      detail: "目前連接的 YouTube 頻道尚未啟用直播，Google 無法提供直播存檔清單。請確認選到平常直播的頻道，或到 YouTube 完成直播啟用；首次啟用最多可能需要 24 小時。" } })
      : route.fulfill({ json: { items: live, next_page_token: "" } });
  });
  await open(page);
  await expect(page.getByRole("alert")).toContainText("尚未啟用直播");
  await expect(page.getByText(channel.title, { exact: true })).toBeVisible();
  const help = page.getByRole("link", { name: "檢查 YouTube 直播功能" });
  await expect(help).toHaveAttribute("href", "https://www.youtube.com/features");
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(help).toBeVisible();
  expect((await new AxeBuilder({ page }).include(".yt-dialog").analyze()).violations).toEqual([]);
  await page.screenshot({ path: "../runs/youtube-ux/live-permission-error.png", fullPage: true });
  blocked = false;
  await page.getByRole("button", { name: "重新整理連線", exact: true }).click();
  await expect(page.getByRole("button", { name: "匯入直播：艾爾登法環｜終於打贏女武神！" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(listRequests).toBe(2);
  expect(state.account.connected).toBe(true);
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("selecting a stream queues one import with explicit AI choice; failures retain the list", async ({ page }) => {
  const state = await setup(page);
  await open(page);
  await expect(page.getByLabel("直播分析模型")).toHaveValue("vision");
  await expect(page.getByLabel("保留畫質")).toHaveValue("best");
  await page.getByLabel("保留畫質").selectOption("1440");
  await expect(page.getByRole("button", { name: "匯入直播：私人存檔" })).toBeDisabled();
  await page.getByLabel("搜尋直播存檔").fill("沒有這個遊戲");
  await expect(page.getByText("沒有符合的直播")).toBeVisible();
  await page.getByRole("button", { name: "清除搜尋", exact: true }).click();
  state.failImport(true);
  await page.getByRole("button", { name: "匯入直播：艾爾登法環｜終於打贏女武神！" }).click();
  await expect(page.getByRole("alert")).toContainText("佇列已滿");
  await expect(page.getByLabel("保留畫質")).toHaveValue("1440");
  await expect(page.getByText("黑暗靈魂 3｜無名王練習", { exact: true })).toBeVisible();
  state.failImport(false);
  await page.getByRole("button", { name: "匯入直播：艾爾登法環｜終於打贏女武神！" }).evaluate((button: HTMLButtonElement) => { button.click(); button.click(); button.click(); });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const imports = state.writes.filter(item => item.path.endsWith("/import"));
  expect(imports).toHaveLength(2); // one rejected attempt, then one accepted despite rapid clicks
  expect(imports[1].body).toEqual({ channel_id: channel.id, auto_analyze: true, model: "vision", download_quality: "1440" });
  expect(state.errors).toEqual([]);
});

test("batch selection survives search, pagination and rejection; rapid submit queues once and choices persist on reopening", async ({ page }) => {
  const state = await setup(page);
  const second = { ...live[0], id: "newlive1234", title: "隻狼｜劍聖一心" };
  const third = { ...live[0], id: "newlive5678", title: "法環｜拉塔恩" };
  await page.route("**/api/youtube/broadcasts*", route => route.fulfill({ json: new URL(route.request().url()).searchParams.has("page_token")
    ? { items: [third], next_page_token: "" } : { items: [...live, second], next_page_token: "next" } }));
  await open(page);
  await page.getByLabel("保留畫質").selectOption("720");
  await page.getByLabel("全選目前清單", { exact: true }).check();
  await expect(page.getByRole("button", { name: "匯入所選（2）", exact: true })).toBeEnabled();
  await expect(page.getByRole("checkbox", { name: `選取直播：${live[1].title}`, exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: "選取直播：私人存檔", exact: true })).toBeDisabled();
  await page.getByLabel("搜尋直播存檔").fill("隻狼");
  await expect(page.getByRole("button", { name: "匯入所選（2）", exact: true })).toBeEnabled();
  await page.getByLabel("搜尋直播存檔").fill("");
  await page.getByRole("button", { name: "載入更多直播", exact: true }).click();
  await page.getByRole("checkbox", { name: `選取直播：${third.title}`, exact: true }).check();
  await page.getByRole("button", { name: "清除選取", exact: true }).click();
  await expect(page.getByRole("button", { name: "匯入所選（0）", exact: true })).toBeDisabled();
  await page.getByLabel("全選目前清單", { exact: true }).check();
  await page.getByLabel("匯入後自動找片段").uncheck();
  state.failBatch(true);
  await page.getByRole("button", { name: "匯入所選（3）", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("等待匯入的影片已滿");
  await expect(page.getByRole("button", { name: "匯入所選（3）", exact: true })).toBeEnabled();
  state.failBatch(false);
  await page.getByRole("button", { name: "匯入所選（3）", exact: true }).evaluate((button: HTMLButtonElement) => { button.click(); button.click(); button.click(); });
  await expect(page.getByText(/已加入 3 部，會依序匯入/)).toBeVisible();
  await expect(page.getByRole("dialog", { name: "我的 YouTube", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "匯入所選（0）", exact: true })).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: `選取直播：${live[0].title}`, exact: true })).toBeDisabled();
  const batches = state.writes.filter(item => item.path === "/api/youtube/imports");
  expect(batches).toHaveLength(2);
  expect(batches[1].body).toEqual({ channel_id: channel.id, auto_analyze: false, model: "vision", download_quality: "720",
    videos: [live[0], second, third].map(({ id, title }) => ({ id, title })) });
  await page.keyboard.press("Escape");
  await open(page);
  await expect(page.getByRole("article", { name: `匯入進度：${third.title}`, exact: true })).toContainText("等待匯入");
  await expect(page.getByRole("article", { name: `匯入進度：${third.title}`, exact: true })).toContainText("最高 720p");
  // Choices stay put across reopening until the user changes them.
  await expect(page.getByLabel("保留畫質")).toHaveValue("720");
  await expect(page.getByLabel("匯入後自動找片段")).not.toBeChecked();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("bosscut:preferences")!)))
    .toMatchObject({ downloadQuality: "720", importAutoAnalyze: false });
  expect(state.writes).toHaveLength(2);
  expect(state.errors).toEqual([]);
});

test("batch queue exposes progress, cancel and individual retry with accessible mobile controls", async ({ page }) => {
  const state = await setup(page);
  state.account.imports = Array.from({ length: 7 }, (_, index) => ({ id: `task-${index}`, video_id: `video${index.toString().padStart(6, "0")}`,
    title: `直播 ${index + 1}｜${"艾爾登法環與夥伴一起挑戰高難度頭目".repeat(index === 0 ? 3 : 1)}`, channel,
    status: index === 0 ? "preparing" : index === 1 ? "failed" : "queued", project_id: index === 0 ? project.id : null,
    error: index === 1 ? "這部直播存檔尚未處理完成，請稍後重試。" : null, auto_analyze: true, progress: index === 0 ? 35 : 0,
    queue_position: index > 1 ? index - 1 : undefined, waiting_reason: "前一部影片仍在下載或製作預覽，完成後會自動接續。",
    stage: "下載 YouTube 影像", job_status: "running", media_progress: index === 0 ? {
      phase: "download", percent: 35, downloaded_bytes: 700_000_000, total_bytes: 2_000_000_000,
      speed_bps: 10_000_000, eta_seconds: 130, updated_at: Date.now() / 1000,
    } : null }));
  await open(page);
  const queue = page.locator(".yt-import-queue");
  await expect(queue.getByRole("article")).toHaveCount(5);
  await expect(queue.getByRole("progressbar")).toHaveAttribute("value", "35");
  await expect(queue).toContainText("35.0%");
  await expect(queue).toContainText("700.0 MB / 2.0 GB");
  await expect(queue).toContainText("10.0 MB/s");
  await expect(queue).toContainText("本階段約剩 3 分鐘");
  await expect(queue).toContainText("排隊第 1 部");
  await expect(queue).toContainText("1 部需處理");
  await page.getByRole("button", { name: "顯示全部 7 部", exact: true }).click();
  await expect(queue.getByRole("article")).toHaveCount(7);
  await page.getByRole("button", { name: `取消等待：${state.account.imports[2].title}`, exact: true }).click();
  await expect(queue.getByRole("article", { name: `匯入進度：${state.account.imports[2].title}`, exact: true })).toContainText("已取消");
  await page.getByRole("button", { name: `重新排隊：${state.account.imports[1].title}`, exact: true }).click();
  await expect(queue.getByRole("article", { name: `匯入進度：${state.account.imports[1].title}`, exact: true })).toContainText("等待匯入");
  await page.getByRole("button", { name: "收起清單", exact: true }).click();
  await page.locator(".yt-content").evaluate(element => { element.scrollTop = 0; });
  await page.screenshot({ path: "../runs/youtube-ux/batch-import-desktop.png", fullPage: true });
  expect((await new AxeBuilder({ page }).include(".yt-dialog").analyze()).violations).toEqual([]);
  for (const viewport of [{ width: 375, height: 812 }, { width: 812, height: 375 }]) {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await page.locator(".yt-dialog").evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
    await expect(page.getByRole("button", { name: "匯入所選（0）", exact: true })).toBeInViewport();
    await expect(page.getByRole("button", { name: "關閉 YouTube 視窗", exact: true })).toBeInViewport();
    expect((await new AxeBuilder({ page }).include(".yt-dialog").analyze()).violations).toEqual([]);
    if (viewport.width === 375) await page.screenshot({ path: "../runs/youtube-ux/batch-import-mobile.png", fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  // Polling updates actual transfer data and later stages without reopening the dialog.
  state.account.imports[0].media_progress.percent = null;
  state.account.imports[0].media_progress.total_bytes = null;
  state.account.imports[0].media_progress.updated_at = Date.now() / 1000 - 90;
  await expect(queue.getByRole("progressbar")).not.toHaveAttribute("value");
  await expect(queue).toContainText("正在等待回應");
  await expect(queue).not.toContainText("10.0 MB/s");
  state.account.imports[0].stage = "製作 720p 預覽影片";
  state.account.imports[0].media_progress = { phase: "preview", percent: 58.5, updated_at: Date.now() / 1000 };
  await expect(queue.getByRole("progressbar")).toHaveAttribute("value", "58.5");
  await expect(queue).toContainText("原片已就緒");
  await expect(queue).not.toContainText("正在等待回應");
  state.account.imports[0].status = "ready";
  state.account.imports[0].progress = 100;
  await expect(queue.getByRole("article", { name: `匯入進度：${state.account.imports[0].title}`, exact: true })).toContainText("已匯入");
  await page.getByRole("button", { name: `開啟工作區：${state.account.imports[0].title}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.writes.map(item => item.path)).toEqual(["/api/youtube/imports/task-2/cancel", "/api/youtube/imports/task-1/retry"]);
  expect(state.errors).toEqual([]);
});

test("select-all caps each request at 100 and clearing remains available", async ({ page }) => {
  const state = await setup(page);
  await page.route("**/api/youtube/broadcasts", route => route.fulfill({ json: { items: Array.from({ length: 102 }, (_, index) => ({ ...live[0],
    id: `video${index.toString().padStart(6, "0")}`, title: `直播 ${index}` })), next_page_token: "" } }));
  await open(page);
  await page.getByLabel("全選目前清單", { exact: true }).click();
  await expect(page.getByRole("button", { name: "匯入所選（100）", exact: true })).toBeEnabled();
  await expect(page.getByRole("checkbox", { name: "選取直播：直播 101", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "清除選取", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "選取直播：直播 101", exact: true })).toBeEnabled();
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("upload defaults private, requires audience, preserves failed form and supports pause/resume", async ({ page }) => {
  const state = await setup(page);
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  await expect(page.getByLabel("誰可以觀看？")).toHaveValue("private");
  await expect(page.getByRole("button", { name: "確認並上傳", exact: true })).toBeInViewport();
  await page.screenshot({ path: "../runs/youtube-ux/upload.png", fullPage: true });
  const accessibility = await new AxeBuilder({ page }).include(".yt-dialog").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByRole("button", { name: "確認並上傳" }).click();
  await expect(page.getByRole("alert")).toContainText("是否為兒童打造");
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("影片標題", { exact: true }).fill("女武神 · 完整勝利");
  await page.getByLabel("這部影片是否為兒童打造？").selectOption("no");
  state.failUpload(true);
  await page.getByRole("button", { name: "確認並上傳" }).click();
  await expect(page.getByRole("alert")).toContainText("網路暫時中斷");
  await expect(page.getByLabel("影片標題", { exact: true })).toHaveValue("女武神 · 完整勝利");
  state.failUpload(false);
  await page.getByRole("button", { name: "確認並上傳" }).evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await expect(page.getByRole("progressbar", { name: "YouTube 上傳進度" })).toBeVisible();
  const uploads = state.writes.filter(item => item.path.endsWith("/finished-clip"));
  expect(uploads).toHaveLength(2);
  expect(uploads[1].body.privacy).toBe("private");
  expect(uploads[1].body.channel_id).toBe(channel.id);
  await page.getByRole("button", { name: "暫停上傳" }).click();
  await page.getByRole("button", { name: "繼續上傳" }).click();
  await expect(page.getByText("上傳完成", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "在 YouTube 查看" })).toHaveAttribute("href", "https://www.youtube.com/watch?v=uploaded123");
  expect(state.errors).toEqual([]);
});

test("a named clip supplies the upload title without starting an upload", async ({ page }) => {
  const state = await setup(page, true, "瑪蓮妮亞・無傷通關");
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  await expect(page.getByLabel("影片標題", { exact: true })).toHaveValue("瑪蓮妮亞・無傷通關");
  expect(state.writes).toEqual([]);
});

test("playlist choice survives failed submission and joining can retry without uploading again", async ({ page }) => {
  const state = await setup(page);
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  const picker = page.getByLabel("加入播放清單", { exact: false });
  await expect(picker).toHaveValue("");
  await picker.selectOption("PLboss");
  await page.getByLabel("這部影片是否為兒童打造？").selectOption("no");
  state.failUpload(true);
  await page.getByRole("button", { name: "確認並上傳", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("網路暫時中斷");
  await expect(picker).toHaveValue("PLboss");
  await page.getByRole("tab", { name: "上傳紀錄", exact: true }).click();
  await page.getByRole("tab", { name: "上傳這段成品", exact: true }).click();
  await expect(picker).toHaveValue("PLboss");
  await picker.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/youtube-ux/playlist-selection.png" });
  expect((await new AxeBuilder({ page }).include(".yt-dialog").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  state.failUpload(false);
  await page.getByRole("button", { name: "確認並上傳", exact: true }).click();
  await expect(page.getByRole("progressbar", { name: "YouTube 上傳進度" })).toBeVisible();
  expect(state.writes.filter(item => item.path.endsWith("/finished-clip")).at(-1)!.body).toMatchObject({ playlist_id: "PLboss", privacy: "private" });
  Object.assign(state.account.uploads[0], { status: "succeeded", video_id: "uploaded123", playlist_status: "failed", playlist_error: "網路暫時中斷" });
  await expect(page.getByText("影片已上傳，尚未加入播放清單", { exact: false })).toBeVisible();
  const uploadsBefore = state.writes.filter(item => item.path.endsWith("/finished-clip")).length;
  await page.getByRole("button", { name: "重試加入播放清單", exact: true }).click();
  await expect(page.getByText("已加入播放清單：艾爾登法環・完整勝利", { exact: true })).toBeVisible();
  expect(state.writes.filter(item => item.path.endsWith("/finished-clip"))).toHaveLength(uploadsBefore);
  expect(state.writes.filter(item => item.path.endsWith("/playlist/retry"))).toHaveLength(1);
  expect(state.errors).toEqual([]);
});

test("legacy connections can authorize playlists without losing upload fields", async ({ page }) => {
  const state = await setup(page);
  state.account.playlist_write_enabled = false;
  await page.context().route("https://accounts.google.com/**", route => route.fulfill({ contentType: "text/html", body: "Test authorization" }));
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  const picker = page.getByLabel("加入播放清單", { exact: false });
  await expect(picker).toBeDisabled();
  await page.getByLabel("影片標題", { exact: true }).fill("保留我的標題");
  await page.getByLabel("這部影片是否為兒童打造？").selectOption("no");
  await expect(page.getByRole("button", { name: "確認並上傳", exact: true })).toBeEnabled();
  const request = page.waitForRequest(request => request.url().includes("/youtube/login?playlists=true"));
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "授權播放清單", exact: true }).click();
  await request;
  const authorization = await popup;
  // Wait for the mocked OAuth document before closing the initially blank popup.
  await expect(authorization).toHaveURL("https://accounts.google.com/o/oauth2/v2/auth?state=test");
  await expect(authorization.getByText("Test authorization", { exact: true })).toBeVisible();
  await authorization.close();
  await expect(page.getByRole("button", { name: "取消授權", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "確認並上傳", exact: true })).toBeDisabled();
  state.account.pending = false;
  state.account.playlist_write_enabled = true;
  await expect(picker).toBeEnabled();
  await expect(page.getByLabel("影片標題", { exact: true })).toHaveValue("保留我的標題");
  await expect(page.getByLabel("這部影片是否為兒童打造？")).toHaveValue("no");
  await picker.selectOption("PLboss");
  expect(state.writes.filter(item => item.path.includes("/uploads/"))).toHaveLength(0);
});

test("playlist loading failures and empty lists still allow uploading without a playlist", async ({ page }) => {
  const state = await setup(page);
  let fail = true;
  await page.route("**/api/youtube/playlists?*", route => fail ? route.fulfill({ status: 503, json: { detail: "清單暫時無法使用" } })
    : route.fulfill({ json: { items: [], next_page_token: "" } }));
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  await expect(page.getByRole("alert")).toContainText("播放清單讀取失敗");
  await expect(page.getByRole("button", { name: "確認並上傳", exact: true })).toBeEnabled();
  fail = false;
  await page.getByRole("button", { name: "重試讀取播放清單", exact: true }).click();
  await expect(page.getByText("這個頻道還沒有播放清單。", { exact: false })).toBeVisible();
  await page.getByLabel("這部影片是否為兒童打造？").selectOption("no");
  await page.getByRole("button", { name: "確認並上傳", exact: true }).click();
  await expect(page.getByRole("progressbar", { name: "YouTube 上傳進度" })).toBeVisible();
  expect(state.writes.find(item => item.path.endsWith("/finished-clip"))!.body.playlist_id).toBeNull();
});

test("playlist pagination preserves selection across tabs and fits a small screen", async ({ page }) => {
  await setup(page);
  await page.route("**/api/youtube/playlists?*", route => {
    const next = new URL(route.request().url()).searchParams.get("page_token") === "second";
    return route.fulfill({ json: { items: [{ id: next ? "PLsecond" : "PLfirst", title: next ? "Dark Souls・Boss 戰與完整勝利合集" : "Elden Ring",
      privacy: next ? "public" : "private", count: next ? 40 : 2 }], next_page_token: next ? "" : "second" } });
  });
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "上傳成品 #1 到 YouTube" }).click();
  await page.getByRole("button", { name: "載入更多播放清單", exact: true }).click();
  const picker = page.getByLabel("加入播放清單", { exact: false });
  await picker.selectOption("PLsecond");
  await page.getByRole("tab", { name: "上傳紀錄", exact: true }).click();
  await page.getByRole("tab", { name: "上傳這段成品", exact: true }).click();
  await expect(picker).toHaveValue("PLsecond");
  await expect(picker.locator('option:checked')).toContainText("Dark Souls");
  await page.setViewportSize({ width: 320, height: 844 });
  await picker.scrollIntoViewIfNeeded();
  const box = (await picker.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(320);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/youtube-ux/playlist-mobile.png" });
});

test("watcher is opt-in and clearly explains future streams and human review", async ({ page }) => {
  const state = await setup(page);
  await open(page);
  expect(state.writes).toHaveLength(0);
  await page.getByLabel("保留畫質").selectOption("1440");
  await page.getByText("自動匯入新直播", { exact: false }).click();
  await expect(page.getByText(/每 10 分鐘檢查一次/)).toBeVisible();
  await page.getByRole("button", { name: "使用上方設定開啟" }).click();
  await expect(page.getByRole("button", { name: "關閉自動匯入" })).toBeVisible();
  await expect(page.getByText(/目前設定：最高 1440p/)).toBeVisible();
  await page.getByRole("button", { name: "關閉自動匯入" }).click();
  expect(state.writes.map(item => item.body.enabled)).toEqual([true, false]);
  expect(state.writes[0].body.download_quality).toBe("1440");
});

test("new imports default to the highest quality and choosing a cap does not start work", async ({ page }) => {
  const state = await setup(page);
  await open(page);
  const quality = page.getByLabel("保留畫質");
  await expect(quality).toHaveValue("best");
  await expect(quality.locator("option")).toHaveCount(6);
  for (const value of ["2160", "1440", "1080", "720", "480", "best"]) await quality.selectOption(value);
  expect(state.writes).toEqual([]);
  await page.getByRole("button", { name: "匯入直播：艾爾登法環｜終於打贏女武神！" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.writes[0].body.download_quality).toBe("best");
});

test("desktop and small-screen views have readable contrast and no clipped controls", async ({ page }) => {
  const state = await setup(page);
  await open(page);
  await expect(page.getByRole("button", { name: "匯入直播：艾爾登法環｜終於打贏女武神！" })).toBeEnabled();
  await page.screenshot({ path: "../runs/youtube-ux/desktop.png", fullPage: true });
  let results = await new AxeBuilder({ page }).include(".yt-dialog").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByLabel("保留畫質").scrollIntoViewIfNeeded();
  await expect(page.getByLabel("保留畫質")).toBeInViewport();
  await page.screenshot({ path: "../runs/youtube-ux/mobile.png", fullPage: true });
  expect(await page.locator(".yt-dialog").evaluate(element => element.scrollWidth <= element.clientWidth)).toBeTruthy();
  await expect(page.locator(".yt-dialog").getByRole("button", { name: "回到工作區", exact: true })).toBeInViewport();
  results = await new AxeBuilder({ page }).include(".yt-dialog").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
  await page.setViewportSize({ width: 812, height: 375 });
  await expect(page.locator(".yt-dialog").getByRole("button", { name: "回到工作區", exact: true })).toBeInViewport();
  expect(state.errors).toEqual([]);
});

test("seeded monkey exploration never starts media work or loses the way back", async ({ page }) => {
  const state = await setup(page);
  let seed = 20260920;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  await open(page);
  for (let step = 0; step < 120; step++) {
    const action = Math.floor(random() * 11);
    if (action === 0) { await page.keyboard.press("Escape"); await open(page); }
    if (action === 1) await page.getByRole("tab", { name: "上傳紀錄", exact: true }).click();
    if (action === 2) await page.getByRole("tab", { name: "直播存檔", exact: true }).click();
    if (action === 3 && await page.getByLabel("搜尋直播存檔").isVisible()) await page.getByLabel("搜尋直播存檔").fill(random() > .5 ? "王" : "");
    if (action === 4) { await page.setViewportSize(random() > .5 ? { width: 375, height: 812 } : { width: 1440, height: 900 }); }
    if (action === 5) { await page.keyboard.press("Tab"); await page.keyboard.press("Shift+Tab"); }
    if (action === 6 && await page.getByLabel("匯入後自動找片段").isVisible()) await page.getByLabel("匯入後自動找片段").click();
    const refresh = page.getByRole("button", { name: "重新整理直播", exact: true });
    if (action === 7 && await refresh.isVisible() && await refresh.isEnabled()) await refresh.click();
    const selectAll = page.getByLabel("全選目前清單", { exact: true });
    if (action === 8 && await selectAll.isVisible() && await selectAll.isEnabled()) await selectAll.click();
    const clear = page.getByRole("button", { name: "清除選取", exact: true });
    if (action === 9 && await clear.isVisible()) await clear.click();
    const selectOne = page.getByRole("checkbox", { name: `選取直播：${live[0].title}`, exact: true });
    if (action === 10 && await selectOne.isVisible() && await selectOne.isEnabled()) await selectOne.click();
    await expect(page.getByRole("button", { name: "關閉 YouTube 視窗" })).toBeInViewport();
  }
  await page.locator(".yt-dialog").getByRole("button", { name: "回到工作區", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});
