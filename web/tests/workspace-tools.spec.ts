import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { NumberedCandidate, Project, State, StorageLocations, VideoStorage } from "../src/api";

async function workspace(page: Page) {
  const segments: NumberedCandidate[] = [
    { id: "scan:one", number: 1, start: 20, end: 70, victory: null, kind: "possible_win", confidence: "medium", boss: "疑似勝利", summary: "勝利位置待確認", warnings: [], evidence: [], review: "pending", verification: "unverified" },
    { id: "scan:two", number: 2, start: 80, end: 140, victory: 130, kind: "possible_win", confidence: "medium", boss: "第二場", summary: "另一個候選", warnings: [], evidence: [], review: "pending", verification: "unverified" },
  ];
  const project: Project = { id: "manual-project", title: "艾爾登法環 · 人工核對", ready: true, duration: 180, thumbnails: [],
    draft: { start: 10, victory: 120, postroll: 8, reviewed: true, revision: 0, origin: "manual" }, review_candidates: segments };
  const storage: VideoStorage = { bytes: 12_500_000_000, files: 8, incomplete: false, updated_at: 1,
    categories: { sources: { bytes: 10_000_000_000, files: 2 }, exports: { bytes: 500_000_000, files: 4 }, previews: { bytes: 2_000_000_000, files: 2 } } };
  const state: State = { projects: [project], jobs: [] };
  const controls = { failStorage: false, malformedStorage: false, failSave: false, gate: null as Promise<void> | null,
    saves: 0, exports: 0, exportQualities: [] as string[], tags: 0, rechecks: [] as { start: number; end: number; candidate_id: string; model: string; analysis_generation: number }[] };
  await page.addInitScript(() => {
    const Native = window.EventSource;
    window.EventSource = class extends Native {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        window.addEventListener("fixture:state", event => this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify((event as CustomEvent).detail) })));
      }
      set onerror(_handler: unknown) {}
    };
    window.addEventListener("error", event => { if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation(); }, true);
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value() { this.dataset.played = String(this.currentTime); return Promise.resolve(); } });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value() { this.dataset.pausedAt = String(this.currentTime); } });
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(state)}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", detail: "已連接" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "test-model", name: "Test model", is_default: true }] } });
    if (path === "/api/storage") return controls.failStorage ? route.fulfill({ status: 503 })
      : route.fulfill({ json: controls.malformedStorage ? { available: true } : storage });
    if (path.endsWith("/candidate-review")) { controls.tags++; return route.fulfill({ json: {} }); }
    if (path.endsWith("/analyze") && route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      controls.rechecks.push(body);
      const job: State["jobs"][number] = { id: `recheck-${controls.rechecks.length}`, project_id: project.id, kind: "analyze",
        status: "queued", stage: "等待判讀", progress: 0, error: null, draft: null, analysis: body };
      state.jobs.unshift(job);
      return route.fulfill({ status: 202, json: job });
    }
    if (path.endsWith("/draft") && route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      project.draft = { ...body, revision: body.revision + 1 };
      return route.fulfill({ json: project.draft });
    }
    if (path.endsWith("/exports")) {
      controls.exports++;
      const quality = route.request().postDataJSON().quality;
      controls.exportQualities.push(quality);
      const job = { id: `export-${controls.exports}`, project_id: project.id, kind: "export" as const, status: "queued", stage: "等待匯出", progress: 0,
        error: null, draft: structuredClone(project.draft!), created: controls.exports, export_quality: quality };
      state.jobs.push(job);
      return route.fulfill({ status: 202, json: job });
    }
    if (path.endsWith("/candidate-edit")) {
      controls.saves++;
      const body = route.request().postDataJSON();
      if (controls.gate) await controls.gate;
      if (controls.failSave) return route.fulfill({ status: 409, json: { detail: "此片段已在其他視窗調整，請重新載入後再編輯。" } });
      const index = project.review_candidates!.findIndex(segment => segment.id === body.candidate_id);
      const candidate = project.review_candidates![index];
      if (body.revision !== (candidate.manual_edit?.revision ?? 0)) return route.fulfill({ status: 409, json: { detail: "片段版本已更新" } });
      const saved: NumberedCandidate = { ...candidate, start: body.start, victory: body.victory, end: body.victory + body.postroll, postroll: body.postroll,
        ai_range: candidate.ai_range ?? { start: candidate.start, end: candidate.end, victory: candidate.victory },
        manual_edit: { start: body.start, victory: body.victory, postroll: body.postroll, revision: body.revision + 1, updated_at: 1 } };
      project.review_candidates![index] = saved;
      return route.fulfill({ json: saved });
    }
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await expect(page.getByText("工作區已連線")).toBeVisible();
  return { controls, project, storage, state,
    publish: () => page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state) };
}

test("selected candidate can be rechecked with its current range and see a separate AI finding", async ({ page }) => {
  const { controls, state, publish } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await page.getByLabel("開始時間").fill("22");
  await page.getByLabel("勝利時間").fill("65");
  await page.getByRole("button", { name: "請 AI 複判片段 #1" }).click();
  await expect.poll(() => controls.rechecks.length).toBe(1);
  expect(controls.rechecks[0]).toMatchObject({ start: 22, end: 73, candidate_id: "scan:one", model: "test-model", analysis_generation: 0 });
  expect(state.jobs[0].analysis?.candidate_id).toBe("scan:one");
  await publish();
  await expect(page.getByRole("group", { name: "片段 #1 AI 複判結果" })).toContainText("等待判讀");
  await expect(page.getByRole("button", { name: "請 AI 複判片段 #1" })).toBeDisabled();
  state.jobs[0].status = "succeeded";
  state.jobs[0].result = { status: "uncertain", start: null, victory: null, postroll: 8,
    boss: "", summary: "發現疑似死亡後重新挑戰，勝利仍未確認。", warnings: ["需核對重試畫面"],
    evidence: [{ time: 44, event: "玩家倒下" }], model: "test-model", frames: 30, rounds: 2 };
  await publish();
  const result = page.getByRole("group", { name: "片段 #1 AI 複判結果" });
  await expect(result).toContainText("仍有疑點");
  await expect(result).toContainText("發現疑似死亡後重新挑戰");
  await result.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/candidate-recheck-desktop.png" });
  expect((await new AxeBuilder({ page }).include(".candidate-detail").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await result.getByRole("button", { name: /玩家倒下/ }).click();
  await expect(page.locator(".video-wrap video")).toHaveJSProperty("currentTime", 44);
  await page.getByRole("button", { name: /時間軸片段 #2 / }).click();
  await expect(page.getByRole("group", { name: "片段 #2 AI 複判結果" })).toHaveCount(0);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(result).toContainText("仍有疑點");
  state.jobs[0].result = { ...state.jobs[0].result!, status: "candidate", start: 80, victory: 130, postroll: 8 };
  await publish();
  await expect(result).toContainText("找到可能成功挑戰");
  await expect(page.getByLabel("開始時間")).toHaveValue("22");
  await expect(page.getByLabel("勝利時間")).toHaveValue("65");
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByRole("button", { name: "請 AI 複判片段 #1" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("export needs no keep tag or checkbox and only successful exports leave a persistent mark", async ({ page }) => {
  const { controls, state, publish } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await page.getByLabel("開始時間").fill("22");
  await page.getByLabel("勝利時間").fill("65");
  await expect(page.locator(".clip-inspector input[type=checkbox]")).toHaveCount(0);
  await expect(page.getByLabel("片段 #1 核對標籤")).toHaveValue("pending");
  const exportButton = page.getByRole("button", { name: "匯出 MP4", exact: true });
  await exportButton.click();
  await expect.poll(() => controls.exports).toBe(1);
  expect(controls.tags).toBe(0);
  expect(state.jobs[0].draft).toMatchObject({ candidate_id: "scan:one", start: 22, victory: 65, reviewed: false });
  for (const status of ["queued", "running", "failed"]) {
    state.jobs[0].status = status;
    await publish();
    await expect(page.locator(".candidate-export-badge")).toHaveCount(0);
    await expect(page.getByText("目前區間已匯出", { exact: true })).toHaveCount(0);
  }
  await exportButton.click();
  await expect.poll(() => controls.exports).toBe(2);
  state.jobs[1].status = "succeeded";
  state.jobs[1].progress = 100;
  await publish();
  await expect(page.getByRole("group", { name: "片段 #1 詳情", exact: true }).getByText("已匯出", { exact: true })).toBeVisible();
  await expect(page.getByText("目前區間已匯出", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "剪輯流程" }).locator('[aria-current="step"]')).toContainText("匯出成品");
  await page.getByRole("group", { name: "片段 #1 詳情", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/candidate-exported-desktop.png" });
  await page.getByLabel("開始時間").fill("23");
  await expect(page.getByText("此片段曾匯出，目前區間有修改", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("開始時間")).toHaveValue("23");
  await expect(page.getByText("此片段曾匯出，目前區間有修改", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /時間軸片段 #1 .*已匯出/ }).click();
  await expect(page.getByRole("group", { name: "片段 #1 詳情", exact: true }).getByText("已匯出", { exact: true })).toBeVisible();
});

test("export shows live encoding progress, flags a stalled encoder and offers the finished MP4", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("bosscut:export-speed", JSON.stringify({ "unknown:high": 2 }));
    const sent: { title: string; body?: string }[] = [];
    (window as unknown as { sentNotifications: typeof sent }).sentNotifications = sent;
    class FakeNotification {
      static permission = "default";
      static requestPermission() { FakeNotification.permission = "granted"; return Promise.resolve("granted"); }
      onclick: (() => void) | null = null;
      constructor(title: string, options?: NotificationOptions) { sent.push({ title, body: options?.body }); }
      close() {}
    }
    Object.defineProperty(window, "Notification", { configurable: true, value: FakeNotification });
  });
  const { controls, state, publish } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #2 / }).click();
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exports).toBe(1);
  const panel = page.getByRole("region", { name: "匯出狀態" });
  await expect(panel).toContainText("匯出排隊中");
  await expect(panel).toContainText("開始後預估約需 29 秒");
  await expect(page.getByRole("button", { name: "排隊中…" })).toHaveClass(/is-waiting/);
  const now = await page.evaluate(() => Date.now() / 1000);
  Object.assign(state.jobs[0], { status: "running", stage: "重新編碼剪輯", progress: 42, started_at: now - 12,
    media_progress: { phase: "export", percent: 42, updated_at: now, processed_seconds: 29, total_seconds: 68, speed_ratio: 2.4, eta_seconds: 16 } });
  await publish();
  await expect(panel.getByRole("progressbar", { name: "匯出進度" })).toHaveAttribute("value", "42");
  await expect(panel).toContainText("已處理 0:29 / 1:08");
  await expect(panel).toContainText("約剩 16 秒");
  const button = page.getByRole("button", { name: "匯出中 42%" });
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute("style", /--export-progress: 42%/);
  await expect(page.locator("#export-help")).toHaveText("約剩 16 秒 · 可繼續編輯");
  await panel.scrollIntoViewIfNeeded();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.screenshot({ path: "../runs/export-progress-running.png" });
  state.jobs[0].media_progress!.updated_at = now - 60;
  await publish();
  await expect(panel).toContainText("處理可能卡住");
  await page.evaluate(() => { document.hasFocus = () => false; });
  Object.assign(state.jobs[0], { status: "succeeded", progress: 100, finished_at: now + 1, media_progress: null });
  await publish();
  await expect.poll(() => page.evaluate(() => (window as unknown as { sentNotifications: { title: string }[] }).sentNotifications))
    .toEqual([{ title: "匯出完成", body: "艾爾登法環 · 人工核對 已可下載。" }]);
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).not.toHaveClass(/is-exporting/);
  await expect(panel).toContainText("匯出完成 · 成品 #1");
  await expect(panel.getByRole("link", { name: "下載 MP4" })).toHaveAttribute("href", "/api/jobs/export-1/download");
  await page.screenshot({ path: "../runs/export-progress-done.png" });
  await panel.getByRole("button", { name: "關閉匯出狀態" }).click();
  await expect(panel).toHaveCount(0);
  expect(await new AxeBuilder({ page }).include(".clip-inspector").analyze().then(r => r.violations)).toEqual([]);
});

test("a newly submitted export replaces the previous completion before the event stream updates", async ({ page }) => {
  const { controls, state, publish } = await workspace(page);
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exports).toBe(1);
  state.jobs[0].status = "succeeded";
  state.jobs[0].finished_at = Date.now() / 1000;
  await publish();
  await expect(page.getByRole("region", { name: "匯出狀態" })).toContainText("匯出完成");

  await page.getByLabel("開始時間").fill("12");
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exports).toBe(2);
  const panel = page.getByRole("region", { name: "匯出狀態" });
  await expect(panel).toContainText("匯出排隊中");
  await expect(page.getByRole("button", { name: "排隊中…" })).toBeDisabled();
  await publish();
  await expect(panel).toContainText("匯出排隊中");
});

test("preferences choose the export and download quality and can silence notifications", async ({ page }) => {
  const { controls, state, publish } = await workspace(page);
  await expect(page.locator("#export-help")).toContainText("MP4 · 高畫質");
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exportQualities).toEqual(["high"]);
  state.jobs[0].status = "succeeded";
  await publish();

  await page.locator("#export-help").getByRole("button", { name: "變更" }).click();
  const dialog = page.getByRole("dialog", { name: "偏好設定" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("radio", { name: /高畫質（建議）/ })).toBeChecked();
  await dialog.getByRole("radio", { name: /平衡/ }).check();
  await dialog.getByLabel("預設保留畫質").selectOption("1080");
  await dialog.getByRole("checkbox", { name: /匯出完成或失敗時通知我/ }).uncheck();
  expect(await new AxeBuilder({ page }).include("#preferences").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze().then(r => r.violations)).toEqual([]);
  await page.screenshot({ path: "../runs/preferences-dialog.png" });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.locator("#export-help")).toContainText("MP4 · 平衡");

  await page.reload();
  await expect(page.locator("#export-help")).toContainText("MP4 · 平衡");
  await page.getByLabel("開始時間").fill("12");
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exportQualities).toEqual(["high", "balanced"]);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("bosscut:preferences")!)))
    .toEqual({ exportQuality: "balanced", downloadQuality: "1080", notifyOnExport: false });
  await page.getByRole("button", { name: "偏好設定", exact: true }).click();
  await expect(dialog.getByLabel("預設保留畫質")).toHaveValue("1080");
  await expect(dialog.getByRole("checkbox", { name: /匯出完成或失敗時通知我/ })).not.toBeChecked();
});

test("export marks respect candidate aliases and exact legacy boundaries, never mere overlap", async ({ page }) => {
  const { project, state, publish } = await workspace(page);
  project.review_candidates![0].aliases = ["scan:one", "legacy:one"];
  const base = { project_id: project.id, kind: "export" as const, status: "succeeded", progress: 100, stage: "完成", error: null };
  state.jobs = [
    { ...base, id: "overlap", draft: { ...project.draft!, start: 21, victory: 65, postroll: 8 } },
    { ...base, id: "exact", draft: { ...project.draft!, start: 80, victory: 130, postroll: 8 } },
  ];
  await publish();
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.getByRole("group", { name: "片段 #1 詳情", exact: true }).locator(".candidate-export-badge")).toHaveCount(0);
  await page.getByRole("button", { name: /時間軸片段 #2 .*已匯出/ }).click();
  await expect(page.getByRole("group", { name: "片段 #2 詳情", exact: true }).getByText("已匯出", { exact: true })).toBeVisible();
  state.jobs.push({ ...base, id: "aliased", draft: { ...project.draft!, candidate_id: "legacy:one" } });
  await publish();
  await page.getByRole("button", { name: /時間軸片段 #1 .*已匯出/ }).click();
  await expect(page.getByRole("group", { name: "片段 #1 詳情", exact: true }).getByText("已匯出", { exact: true })).toBeVisible();
});

test("single-click candidate editing preserves each range and previews exactly what will export", async ({ page }) => {
  const { controls, state } = await workspace(page);
  const target = page.getByRole("group", { name: "目前編輯與匯出區間", exact: true });
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(target).toContainText("正在編輯 #1");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await target.getByRole("button", { name: "調整時間" }).click();
  await expect(page.getByLabel("開始時間")).toBeFocused();
  await page.getByLabel("開始時間").fill("22");
  await page.getByLabel("勝利時間").fill("65");
  await expect(target).toContainText("00:00:22.000 → 00:01:13.000");
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await expect(target).toContainText("正在編輯 #2");
  await page.getByLabel("開始時間").fill("82");
  await page.getByRole("button", { name: "上一段", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("22");
  await expect(page.getByLabel("勝利時間")).toHaveValue("65");
  // Clicking the same annotation or its shortcut must not reset an edited range.
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await page.getByRole("button", { name: "編輯片段 #1 區間" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("22");
  await page.getByRole("button", { name: "預覽 #1", exact: true }).click();
  await expect(page.locator(".video-wrap video")).toHaveAttribute("data-played", "22");
  await page.locator(".video-wrap video").evaluate((video: HTMLVideoElement) => {
    video.currentTime = 73; video.dispatchEvent(new Event("timeupdate"));
  });
  await expect(page.locator(".video-wrap video")).toHaveAttribute("data-paused-at", "73");
  await page.reload();
  await expect(target).toContainText("正在編輯 #1");
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("82");
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({
    type: "reply", project_id: "manual-project", reply: "查看第一段", action: { kind: "select_candidate", candidate_id: "scan:one",
      start: null, victory: null, postroll: null, seconds: null } }) + "\n" }));
  await page.getByLabel("輸入訊息").fill("查看 #1");
  await page.getByRole("button", { name: "送出訊息" }).click();
  await expect(page.locator(".chat-operation")).toContainText("已選取 #1 · 00:00:22–00:01:13");
  await expect(target).toContainText("正在編輯 #1");
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).click();
  await expect.poll(() => controls.exports).toBe(1);
  expect(state.jobs[0].draft).toMatchObject({ candidate_id: "scan:one", start: 22, victory: 65, postroll: 8 });
  expect(controls.saves).toBe(0);
  await target.getByRole("button", { name: "調整時間" }).click();
  await page.screenshot({ path: "../runs/direct-candidate-edit-desktop.png" });
  expect((await new AxeBuilder({ page }).include(".clip-inspector").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
});

test("late AI edits are rejected after a candidate round trip", async ({ page }) => {
  await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/codex/chat", async route => {
    await gate;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", project_id: "manual-project",
      reply: "調整開始", action: { kind: "set_draft", start: 18, victory: 62, postroll: 8, seconds: null } }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("開始提前兩秒");
  const request = page.waitForRequest(request => request.url().endsWith("/codex/chat"));
  await page.getByRole("button", { name: "送出訊息" }).click();
  await request;
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await page.getByRole("button", { name: "上一段", exact: true }).click();
  release();
  await expect(page.locator(".chat-operation")).toContainText("編輯對象已切換");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
});

test("local capacity shows real totals, keeps stale values on failure and can recover", async ({ page }) => {
  const { controls, storage } = await workspace(page);
  const usage = page.getByLabel("本地影片容量", { exact: true });
  await expect(usage).toContainText("12.5 GB");
  await usage.locator("summary").click();
  await expect(usage).toContainText("500 MB");
  await expect(usage).toContainText("預覽與暫存");
  controls.failStorage = true;
  await page.getByRole("button", { name: "更新影片用量" }).click();
  await expect(usage).toContainText("更新失敗，顯示上次計算結果");
  await expect(usage).toContainText("12.5 GB");
  controls.failStorage = false;
  storage.bytes = 11_000_000_000;
  storage.categories.previews.bytes = 500_000_000;
  await page.getByRole("button", { name: "更新影片用量" }).click();
  await expect(usage).toContainText("11 GB");
  await expect(usage).not.toContainText("更新失敗");
  await expect(usage).toBeInViewport();
  await page.screenshot({ path: "../runs/local-capacity-desktop.png" });
  expect((await new AxeBuilder({ page }).include(".local-storage").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  controls.malformedStorage = true;
  await page.reload();
  await expect(usage).toContainText("暫時無法讀取");
  await expect(page.getByLabel("輸入訊息")).toBeVisible();
});

test("a candidate with no victory time can be edited, marked, saved and reopened", async ({ page }) => {
  const { project, controls } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  const edit = page.getByRole("button", { name: "編輯片段 #1 區間" });
  await edit.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/candidate-edit-button.png" });
  await edit.click();
  await expect(page.getByLabel("開始時間")).toBeFocused();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await expect(page.getByLabel("勝利時間")).toHaveValue("62");
  await expect(page.locator(".manual-adjustment-badge")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "儲存區間", exact: true })).toBeDisabled();
  await page.getByLabel("開始時間").fill("22");
  await page.getByLabel("勝利時間").fill("65");
  await expect(page.getByRole("group", { name: "正在編輯片段 #1" })).toContainText("已手動調整");
  await page.getByRole("button", { name: "儲存區間", exact: true }).click();
  await expect(page.getByRole("button", { name: "區間已儲存", exact: true })).toBeDisabled();
  expect(controls.saves).toBe(1);
  expect(project.review_candidates![0].ai_range?.start).toBe(20);
  await page.getByRole("group", { name: "正在編輯片段 #1" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/candidate-manual-edit-desktop.png" });
  expect((await new AxeBuilder({ page }).include(".clip-workspace").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.reload();
  await page.getByLabel("開始時間").fill("23");
  await page.getByRole("button", { name: "儲存區間", exact: true }).click();
  await expect(page.getByRole("button", { name: "區間已儲存", exact: true })).toBeDisabled();
  expect(controls.saves).toBe(2);
  await page.getByRole("button", { name: /時間軸片段 #1 .*已手動調整/ }).click();
  await expect(page.getByRole("group", { name: "片段 #1 詳情" })).toContainText("AI 原始區間 00:00:20.000–00:01:10.000");
  await page.getByRole("button", { name: "編輯片段 #1 區間" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("23");
  await expect(page.getByLabel("勝利時間")).toHaveValue("65");
  await page.getByRole("slider", { name: "片段開始邊界", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "儲存區間", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeEnabled();
});

test("failed range saves retain edits and a late response never changes another candidate", async ({ page }) => {
  const { controls } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await page.getByRole("button", { name: "編輯片段 #1 區間" }).click();
  await page.getByLabel("開始時間").fill("23");
  controls.failSave = true;
  await page.getByRole("button", { name: "儲存區間", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("其他視窗調整");
  await expect(page.getByLabel("開始時間")).toHaveValue("23");
  controls.failSave = false;
  let release!: () => void;
  controls.gate = new Promise<void>(resolve => { release = resolve; });
  const requested = page.waitForRequest(request => request.url().endsWith("/candidate-edit"));
  await page.getByRole("button", { name: "儲存區間", exact: true }).click();
  await requested;
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await page.getByRole("button", { name: "編輯片段 #2 區間" }).click();
  await page.getByLabel("開始時間").fill("82");
  release();
  await expect(page.getByRole("button", { name: "儲存區間", exact: true })).toBeEnabled();
  await expect(page.getByLabel("開始時間")).toHaveValue("82");
  await expect(page.getByLabel("勝利時間")).toHaveValue("130");
  expect(controls.saves).toBe(2);
});

test("candidate editing remains usable on narrow screens and invalid ranges cannot be saved", async ({ page }) => {
  await workspace(page);
  await page.getByRole("button", { name: "關閉 AI 對話", exact: true }).click();
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
    await page.getByRole("button", { name: "編輯片段 #1 區間" }).click();
    await page.getByLabel("開始時間").fill("75");
    await expect(page.getByLabel("開始時間")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("button", { name: "儲存區間", exact: true })).toBeDisabled();
    await page.getByLabel("開始時間").fill("25");
    await expect(page.getByRole("button", { name: "儲存區間", exact: true })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `../runs/candidate-manual-edit-${width}.png` });
  }
});

test("storage folders can be moved, rejected with a reason, and restored from preferences", async ({ page }) => {
  await workspace(page);
  const locations: StorageLocations = {
    sources: { path: "/work/downloads", default: "/work/downloads", custom: false },
    exports: { path: "/work/clips", default: "/work/clips", custom: false },
    cache: { path: "/work/runs", default: "/work/runs", custom: false },
  };
  const updates: Record<string, string | null>[] = [];
  await page.route("**/api/locations", route => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<keyof StorageLocations, string | null>;
      updates.push(body);
      if (body.exports === "clips") return route.fulfill({ status: 422, json: { detail: "請輸入完整的資料夾路徑，例如 D:\\Videos\\BossCut。" } });
      for (const [kind, path] of Object.entries(body) as [keyof StorageLocations, string | null][])
        locations[kind] = { ...locations[kind], path: path ?? locations[kind].default, custom: !!path };
    }
    return route.fulfill({ json: locations });
  });
  await page.getByRole("button", { name: "偏好設定", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "偏好設定" });
  const exports = dialog.getByRole("textbox", { name: "輸出成品", exact: true });
  await expect(exports).toHaveValue("/work/clips");
  const apply = dialog.locator(".storage-location").filter({ hasText: "輸出成品" }).getByRole("button", { name: "套用" });
  await expect(apply).toBeDisabled();
  await exports.fill("clips");
  await apply.click();
  await expect(dialog.getByRole("alert")).toContainText("請輸入完整的資料夾路徑");
  await expect(exports).toHaveAttribute("aria-invalid", "true");
  await exports.fill("/mnt/d/BossCut/成品");
  await apply.click();
  await expect(dialog.getByRole("status").filter({ hasText: "已更新「輸出成品」位置" })).toContainText("/mnt/d/BossCut/成品");
  await expect(exports).toHaveAttribute("aria-invalid", "false");
  expect(updates).toEqual([{ exports: "clips" }, { exports: "/mnt/d/BossCut/成品" }]);
  await dialog.getByRole("group", { name: "儲存位置" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/storage-locations.png" });
  expect((await new AxeBuilder({ page }).include("#preferences").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await dialog.getByRole("button", { name: /還原預設/ }).click();
  await expect(exports).toHaveValue("/work/clips");
  await expect(dialog.getByRole("button", { name: /還原預設/ })).toHaveCount(0);
  expect(updates.at(-1)).toEqual({ exports: null });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
});
