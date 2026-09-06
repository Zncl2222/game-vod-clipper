import { expect, test, type Page } from "@playwright/test";

const project = { id: "demo", title: "示範專案（僅測試資料）", ready: true, duration: 180, thumbnails: [],
  draft: { start: 10, victory: 100, postroll: 5, reviewed: true, revision: 0, origin: "manual" } };
async function setup(page: Page, projects: unknown[] = [], options: { chat?: boolean; settings?: boolean } = {}) {
  // Fulfilled SSE fixtures close immediately; ignore that artificial disconnect.
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        window.addEventListener("fixture:state", (event) => {
          this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify((event as CustomEvent).detail) }));
        });
      }
      set onerror(_handler: ((this: EventSource, ev: Event) => unknown) | null) {}
    };
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ projects, jobs: [] })}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", email: "demo@example.test", model: "model-a", plan: "plus", detail: "已連接 ChatGPT 訂閱" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [
      { id: "model-a", name: "Model A", is_default: true }, { id: "model-b", name: "Model B" },
    ] } });
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  if (options.chat !== false) await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  if (projects.length && options.settings !== false) await page.locator(".editor-settings > summary").click();
  if (options.chat !== false) await expect(page.getByLabel("選擇 AI 模型")).toHaveValue("model-a");
}

test("right rail chats, switches model, keeps history and fits desktop", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await setup(page);
  await expect(page.getByRole("heading", { name: "AI 帳號與連線" })).not.toBeVisible();
  await page.screenshot({ path: "../runs/chat-desktop.png" });
  const bounds = await page.locator(".chat-panel").boundingBox();
  expect(bounds!.x + bounds!.width).toBe(1440);
  expect(bounds!.height).toBe(900);
  await page.route("**/api/codex/chat", async (route) => {
    const request = route.request().postDataJSON();
    expect(request.model).toBe("model-b");
    expect(request.context).toBeNull();
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: `收到：${request.message}`, model: request.model, action: null }) + "\n" });
  });
  await page.getByLabel("選擇 AI 模型").selectOption("model-b");
  await page.getByLabel("輸入訊息").fill("今天想聊遊戲。");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByRole("log")).toContainText("收到：今天想聊遊戲。");
  await page.route("**/api/codex/chat", async (route) => {
    expect(route.request().postDataJSON().history).toHaveLength(2);
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "我們正在聊遊戲。", model: "model-b", action: null }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("我們剛才聊什麼？");
  await page.getByLabel("輸入訊息").press("Enter");
  await expect(page.getByRole("log")).toContainText("我們正在聊遊戲。");
  await page.getByLabel("新對話").click();
  await expect(page.getByRole("log")).not.toContainText("今天想聊遊戲。");
  expect(errors).toEqual([]);
});

test("editor commands update draft and invalidate review without media processing", async ({ page }) => {
  await setup(page, [project]);
  await page.getByRole("button", { name: "剪輯助理", exact: true }).click();
  await page.route("**/api/codex/chat", async (route) => {
    expect(route.request().postDataJSON().context.draft.postroll).toBe(5);
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "收尾改為 8 秒。", model: "model-a", project_id: "demo",
      action: { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("收尾改成8秒");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await expect(page.getByRole("log")).toContainText("已更新草稿");
  await expect(page.getByLabel("勝利後收尾")).toHaveClass(/ai-target/);
  await expect(page.getByLabel("開始時間")).not.toHaveClass(/ai-target/);
  await page.screenshot({ path: "../runs/chat-editor.png" });
});

test("late reply cannot overwrite a newer manual edit", async ({ page }) => {
  await setup(page, [project]);
  await page.getByRole("button", { name: "剪輯助理", exact: true }).click();
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/codex/chat", async (route) => {
    await wait;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "收尾改為 8 秒。", model: "model-a", project_id: "demo",
      action: { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("收尾改成8秒");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("停止回應")).toBeVisible();
  await page.getByLabel("開始時間").fill("20");
  release();
  await expect(page.getByRole("log")).toContainText("未覆蓋新的設定");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("5");
});

test("mobile opens a full-height conversation without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  // Model selector is intentionally hidden before opening the mobile drawer.
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: 'data: {"projects":[],"jobs":[]}\n\n' });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "model-a", name: "Model A", is_default: true }] } });
    return route.fulfill({ json: { available: true, auth_mode: "chatgpt", detail: "已連接" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await expect(page.getByLabel("輸入訊息")).toBeVisible();
  await page.screenshot({ path: "../runs/chat-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByLabel("關閉 AI 對話").click();
  await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
});

test("missing model route explains backend mismatch instead of Not Found", async ({ page }) => {
  await setup(page);
  await page.route("**/api/codex/models", (route) => route.fulfill({ status: 404, json: { detail: "Not Found" } }));
  await page.reload();
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("請重新啟動 BossCut 後端");
  await expect(page.getByRole("alert")).not.toContainText("Not Found");
});

test("composer grows with content up to a cap and shrinks when cleared", async ({ page }) => {
  await setup(page);
  const input = page.getByLabel("輸入訊息");
  const height = () => input.evaluate((element) => element.getBoundingClientRect().height);
  expect(await height()).toBeLessThanOrEqual(30);
  await input.fill("第一行\n第二行\n第三行");
  expect(await height()).toBeGreaterThan(50);
  await input.fill(Array(20).fill("這是一行較長的訊息內容").join("\n"));
  expect(await height()).toBeLessThanOrEqual(108);
  await expect(input).toHaveCSS("overflow-y", "auto");
  await input.fill("");
  expect(await height()).toBeLessThanOrEqual(30);
});

test("analysis events drive visible stages, sampling range and stale feedback", async ({ page }) => {
  await setup(page, [project]);
  const job = { id: "analysis-fixture", project_id: "demo", kind: "analyze", status: "running",
    phase: "extracting", stage: "第 1 輪：正在擷取抽樣畫面", current_round: 1,
    frames: 12, sample_start: 30, sample_end: 90, heartbeat_at: Date.now() / 1000 };
  const emit = (job: object) => page.evaluate((data) => {
    window.dispatchEvent(new CustomEvent("fixture:state", { detail: data }));
  }, { projects: [project], jobs: [job] });
  await emit(job);
  const card = page.getByRole("region", { name: "AI 即時工作狀態" });
  await expect(card).toContainText("正在擷取畫面");
  await expect(page.getByLabel("AI 本輪抽樣範圍")).toBeAttached();
  await expect(card.locator('[aria-current="step"]')).toHaveText("擷取");
  await emit({ ...job, phase: "analyzing", stage: "Codex 已開始本輪判讀" });
  await expect(card.locator('[aria-current="step"]')).toHaveText("判讀");
  await page.getByLabel("查看分析詳情").click();
  await expect(page.getByLabel("Codex 分析進度")).toBeVisible();
  await emit({ ...job, heartbeat_at: Date.now() / 1000 - 60 });
  await expect(card).toContainText("等待背景工作回報");
  await expect(card.locator('[aria-current="step"]')).toHaveCount(0);
  await emit({ ...job, status: "cancelled" });
  await expect(card).toContainText("分析已取消");
  await expect(page.getByLabel("AI 本輪抽樣範圍")).toHaveCount(0);
});

test("one-click search and typed search use the chat endpoint and shared result card", async ({ page }) => {
  await setup(page, [project]);
  await page.getByLabel("選擇 AI 模型").selectOption("model-b");
  const requests: { intent: string; model: string }[] = [];
  await page.route("**/api/projects/*/analyze", () => { throw new Error("Legacy search route must not be called by the UI"); });
  await page.route("**/api/codex/chat", async (route) => {
    const request = route.request().postDataJSON();
    requests.push(request);
    expect(request.model).toBe("model-b");
    expect(request.context.project_id).toBe("demo");
    if (request.intent === "search") {
      expect(request.search_start).toBe(0);
      expect(request.search_end).toBe(180);
    }
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "已建立成功挑戰搜尋任務", model: "model-b", action: null, job_id: "shared-task" }) + "\n" });
  });
  await page.locator(".assistant-shortcut").getByRole("button", { name: "一鍵搜尋成功挑戰" }).click();
  await expect(page.getByRole("log")).toContainText("已建立成功挑戰搜尋任務");
  await page.getByLabel("輸入訊息").fill("再幫我搜尋成功的挑戰");
  await page.getByLabel("送出訊息").click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests.map((request) => request.intent)).toEqual(["search", "message"]);
  await page.evaluate((project) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "shared-task", project_id: "demo", kind: "analyze", status: "succeeded", model: "model-b",
      result: { project_id: "demo", status: "candidate", start: 20, victory: 100, postroll: 8, boss: "示範候選",
        summary: "需要人工檢查的候選片段", evidence: [], warnings: ["抽樣不等於逐格驗證"], frames: 24, rounds: 1, model: "model-b" } }],
  } })), project);
  await expect(page.getByLabel("AI 搜尋任務")).toContainText("model-b");
  await page.getByRole("button", { name: /套用候選/ }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
});

test("failed extraction shows a readable error and older searches stay collapsed", async ({ page }) => {
  await setup(page, [project]);
  const latest = { id: "latest", project_id: "demo", kind: "analyze", status: "failed", model: "model-b",
    error: "Command '['/usr/bin/ffmpeg', '-ss', '0.0']' timed out after 120 seconds", frames: 0, rounds: 0 };
  await page.evaluate((jobs) => window.dispatchEvent(new CustomEvent("fixture:state", {
    detail: { projects: [{ id: "demo", title: "Demo", ready: true, duration: 180, thumbnails: [],
      draft: { start: 10, victory: 100, postroll: 5, reviewed: true, revision: 0, origin: "manual" } }], jobs },
  })), [latest, { ...latest, id: "older", status: "cancelled", model: "model-a", error: undefined }]);
  await expect(page.getByLabel("AI 搜尋任務")).toHaveCount(1);
  await expect(page.getByLabel("Codex 分析進度")).toContainText("擷取抽樣畫面逾時");
  await expect(page.getByLabel("Codex 分析進度")).not.toContainText("/usr/bin/ffmpeg");
  await expect(page.getByRole("button", { name: "重試分析" })).toBeVisible();
  await page.getByRole("button", { name: "查看較早的搜尋紀錄" }).click();
  await expect(page.getByLabel("AI 搜尋任務")).toHaveCount(2);
});

test("AI candidate appears selected in workspace and range handles edit the draft", async ({ page }) => {
  const editable = { ...project, draft: { ...project.draft, reviewed: false } };
  await setup(page, [editable]);
  const result = { project_id: "demo", status: "candidate", start: 20, victory: 100, postroll: 8, boss: "測試 Boss",
    summary: "待確認的成功挑戰", evidence: [], warnings: ["請檢查前後段"], frames: 24, rounds: 1, model: "model-a" };
  await page.evaluate(({ project, result }) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "visual-candidate", project_id: "demo", kind: "analyze", status: "succeeded", result }],
  } })), { project: editable, result });
  const workspace = page.getByRole("region", { name: "片段工作區" });
  await expect(workspace.getByRole("button", { name: "選取片段 測試 Boss" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await workspace.screenshot({ path: "../runs/clip-workspace.png" });
  const handle = workspace.getByRole("slider", { name: "片段開始邊界" });
  await handle.scrollIntoViewIfNeeded();
  const bounds = (await handle.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 25, bounds.y + bounds.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(Number(await page.getByLabel("開始時間").inputValue())).toBeGreaterThan(20);
  await workspace.getByRole("slider", { name: "片段結束邊界" }).focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect(workspace.getByRole("slider", { name: "片段結束邊界" })).toHaveAttribute("aria-valuenow", "109");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => workspace.evaluate(el => el.getBoundingClientRect().width)).toBeLessThanOrEqual(390);
});

test("new visual candidates preserve manual edits until a card is selected", async ({ page }) => {
  const editable = { ...project, draft: { ...project.draft, reviewed: false } };
  await setup(page, [editable]);
  await page.getByLabel("開始時間").fill("35");
  const job = { id: "late-candidate", project_id: "demo", kind: "analyze", status: "succeeded",
    result: { project_id: "demo", status: "candidate", start: 20, victory: 100, postroll: 8, boss: "新候選",
      summary: "稍後完成", evidence: [], warnings: [], frames: 24, rounds: 1, model: "model-a" } };
  await page.evaluate(({ project, job }) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: { projects: [project], jobs: [job] } })), { project: editable, job });
  await expect(page.getByLabel("開始時間")).toHaveValue("35");
  await page.getByRole("button", { name: "選取片段 新候選" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
});

test("completed exports have inline players in the workspace without starting new jobs", async ({ page }) => {
  await setup(page, [project]);
  await page.evaluate(project => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "finished-export", project_id: "demo", kind: "export", status: "succeeded", draft: project.draft }],
  } })), project);
  const player = page.getByRole("region", { name: "片段工作區" }).locator("video");
  await expect(player).toHaveAttribute("src", "/api/jobs/finished-export/download");
  await expect(player).toHaveAttribute("preload", "none");
  await expect(player).toHaveAttribute("controls", "");
});

test("video dock searches the full VOD without opening the mobile drawer", async ({ page }) => {
  await setup(page, [{ ...project, duration: 7200 }], { chat: false, settings: false });
  await page.setViewportSize({ width: 390, height: 844 });
  let requested = false;
  await page.route("**/api/codex/chat", async route => {
    expect(route.request().postDataJSON().search_end).toBe(7200);
    requested = true;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "搜尋全片", action: null }) + "\n" });
  });
  await page.getByLabel("影片 AI 助手").getByRole("button", { name: "一鍵搜尋成功挑戰" }).click();
  await expect.poll(() => requested).toBe(true);
  await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("candidate arrival preserves playback, evidence seeks, and preview stops at the chosen boundary", async ({ page }) => {
  const editable = { ...project, draft: { ...project.draft, reviewed: false } };
  await setup(page, [editable]);
  await page.evaluate(() => {
    HTMLMediaElement.prototype.play = async function () { this.dataset.plays = String(Number(this.dataset.plays ?? 0) + 1); };
    HTMLMediaElement.prototype.pause = function () { this.dataset.pauses = String(Number(this.dataset.pauses ?? 0) + 1); };
    document.querySelector("video")!.currentTime = 45;
  });
  const result = { project_id: "demo", status: "candidate", start: 20, victory: 100, postroll: 8, boss: "精細候選",
    summary: "已完成密集抽樣，等待預覽確認", evidence: [{ time: 60, event: "Boss 血條變化" }], warnings: [], frames: 860, rounds: 23, model: "model-a",
    coverage: [{ start: 0, end: 179, every: 10 }, { start: 20, end: 108, every: .5 }] };
  await page.evaluate(({ project, result }) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "precise", project_id: "demo", kind: "analyze", status: "succeeded", result }],
  } })), { project: editable, result });
  const player = page.locator(".preview-panel .video-wrap video");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  expect(await player.evaluate((el: HTMLVideoElement) => el.currentTime)).toBe(45);
  await expect(player).not.toHaveAttribute("data-pauses");
  const workspace = page.getByLabel("片段工作區");
  await workspace.getByRole("button", { name: /查看證據.*Boss 血條變化/ }).click();
  expect(await player.evaluate((el: HTMLVideoElement) => el.currentTime)).toBe(60);
  await workspace.getByRole("button", { name: /看勝利瞬間/ }).click();
  expect(await player.evaluate((el: HTMLVideoElement) => el.currentTime)).toBe(96);
  await expect(player).toHaveAttribute("data-plays", "1");
  await player.evaluate((el: HTMLVideoElement) => { el.currentTime = 103.1; el.dispatchEvent(new Event("timeupdate")); });
  await expect(player).toHaveAttribute("data-pauses", "1");
  await workspace.getByRole("slider", { name: "勝利位置邊界" }).press("Shift+ArrowRight");
  await expect(page.getByLabel("勝利時間")).toHaveValue("101");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  await workspace.screenshot({ path: "../runs/deep-review-timeline.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await workspace.screenshot({ path: "../runs/deep-review-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("unfinished inspection stays previewable and continues the saved task", async ({ page }) => {
  await setup(page, [project]);
  const job = { id: "budget-stop", project_id: "demo", kind: "analyze", status: "succeeded", resumable: true,
    result: { status: "uncertain", start: 20, victory: 100, postroll: 8, boss: "未確認",
      summary: "尚有畫面需要檢查", evidence: [], warnings: [], frames: 12000, rounds: 240, model: "model-a", can_continue: true } };
  await page.evaluate(({ project, job }) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: { projects: [project], jobs: [job] } })), { project, job });
  await expect(page.getByRole("button", { name: "選取片段 未確認" })).toHaveCount(0);
  await expect(page.getByLabel("開始時間")).toHaveValue("10");
  await expect(page.getByRole("button", { name: /時間軸片段 #1 / })).toBeVisible();
  let resumed = false;
  await page.route("**/api/jobs/budget-stop/retry", async route => { resumed = true; await route.fulfill({ json: { id: "continued" } }); });
  await page.getByLabel("影片 AI 助手").getByRole("button", { name: "接續細查" }).click();
  await expect.poll(() => resumed).toBe(true);
});

test("uncertain candidates appear live, keep stable numbers, preview, tag and explicitly become drafts", async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener("error", event => { if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation(); }, true);
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value() { this.dataset.played = String(this.currentTime); return Promise.resolve(); } });
  });
  await setup(page, [project], { chat: false });
  const first = { id: "scan:encounter-1", start: 20, end: 70, victory: null, kind: "fight", confidence: "low",
    boss: "第一場", summary: "戰鬥尚未確認結果", warnings: ["需檢查是否接到重試"], evidence: [] };
  const second = { ...first, id: "scan:encounter-2", start: 60, end: 115, victory: 107, kind: "possible_win", boss: "第二場" };
  const third = { ...first, id: "scan:encounter-3", start: 140, end: 150, kind: "death_retry", boss: "死亡片段" };
  const job = { id: "scan", project_id: "demo", kind: "analyze", status: "running", candidates: [first, second, third] };
  const state = { projects: [project], jobs: [job] };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state);
  const timeline = page.getByLabel("候選片段時間軸", { exact: true });
  await expect(timeline.locator(".candidate-marker")).toHaveCount(3);
  await timeline.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.getByLabel("片段 #1 詳情")).toContainText("戰鬥尚未確認結果");
  await expect(page.getByRole("button", { name: "將 #1 放入剪輯草稿" })).toHaveCount(0);
  await expect(page.getByLabel("開始時間")).toHaveValue("10");
  await expect(page.getByRole("checkbox")).toBeChecked();
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  await page.getByRole("button", { name: "預覽 #2", exact: true }).click();
  await expect(page.locator(".video-wrap video")).toHaveAttribute("data-played", "60");
  await page.route("**/api/projects/demo/candidate-review", async route => {
    expect(route.request().postDataJSON()).toEqual({ candidate_id: second.id, review: "keep", analysis_generation: 0 });
    await route.fulfill({ json: { candidate_id: second.id, review: "keep" } });
  });
  await page.getByLabel("片段 #2 核對標籤").selectOption("keep");
  await expect(page.getByLabel("片段 #2 核對標籤")).toHaveValue("keep");
  const refined = { ...second, start: 62 };
  const nextState = { projects: [{ ...project, candidate_reviews: { [second.id]: "keep" } }], jobs: [
    { ...job, id: "resume", status: "succeeded", candidates: [refined] }, { ...job, status: "cancelled" },
  ] };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), nextState);
  await expect(timeline.locator(".candidate-marker")).toHaveCount(3);
  await expect(page.getByLabel("片段 #2 詳情")).toContainText("00:01:02.000");
  await page.getByRole("button", { name: "將 #2 放入剪輯草稿" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("62");
  await expect(page.getByLabel("勝利時間")).toHaveValue("107");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.screenshot({ path: "../runs/candidate-review-desktop.png", fullPage: true });
  await page.route("**/api/events", route => route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(nextState)}\n\n` }));
  await page.reload();
  await timeline.getByRole("button", { name: /時間軸片段 #2 / }).click();
  await expect(page.getByLabel("片段 #2 核對標籤")).toHaveValue("keep");
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({
    type: "reply", project_id: "demo", reply: "查看 #3", action: { kind: "select_candidate", candidate_id: third.id,
      start: null, victory: null, postroll: null, seconds: null },
  }) + "\n" }));
  await page.getByLabel("輸入訊息").fill("查看 #3");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("片段 #3 詳情")).toContainText("死亡／重試");
  await expect(page.getByRole("log")).toContainText("已選取 #3");
  await page.getByLabel("關閉 AI 對話").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../runs/candidate-review-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("video and selected range fit on desktop and mobile without scrolling", async ({ page }) => {
  await page.addInitScript(() => window.addEventListener("error", event => {
    if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
  }, true));
  await setup(page, [{ ...project, draft: { ...project.draft, reviewed: false } }], { chat: false, settings: false });
  await page.evaluate(project => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [{ ...project, draft: { ...project.draft, reviewed: false } }], jobs: [{ id: "fit-candidate", project_id: "demo", kind: "analyze", status: "succeeded", result: {
      status: "candidate", start: 20, victory: 100, postroll: 8, boss: "測試 Boss", summary: "範圍確認", warnings: [], evidence: [], frames: 100, rounds: 12, model: "model-a" } }],
  } })), project);
  await expect(page.getByRole("slider", { name: "片段開始邊界" })).toHaveAttribute("aria-valuenow", "20");
  const core = page.getByLabel("影片與選取範圍");
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const video = await core.locator("video").boundingBox();
    const selection = await core.getByRole("slider", { name: "片段結束邊界" }).boundingBox();
    const footer = await core.getByRole("button", { name: "匯出 MP4" }).boundingBox();
    await page.screenshot({ path: `../runs/simple-editor-${viewport.width}.png` });
    expect(video!.y).toBeGreaterThanOrEqual(0);
    expect(selection!.y).toBeGreaterThan(video!.y + video!.height);
    expect(footer!.y + footer!.height).toBeLessThan(viewport.height);
    expect(await page.locator(".main-shell").evaluate(el => el.scrollTop)).toBe(0);
    await expect(page.locator(".editor-settings")).not.toHaveAttribute("open");
    await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
    await page.screenshot({ path: `../runs/simple-editor-${viewport.width}.png` });
  }
});

test("reset removes old candidates and editing context and a new search starts fresh", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "舊判斷：只看第100秒", model: "model-a", action: null }) + "\n" }));
  await page.getByLabel("輸入訊息").fill("看看目前的候選");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByRole("log")).toContainText("舊判斷");
  const job = { id: "old-result", kind: "analyze", project_id: "demo", status: "succeeded", result: {
    project_id: "demo", status: "candidate", start: 20, victory: 100, postroll: 8, boss: "舊候選", summary: "舊結果", evidence: [], warnings: [], frames: 100, rounds: 8, model: "model-a" } };
  await page.evaluate(({ project, job }) => window.dispatchEvent(new CustomEvent("fixture:state", { detail: { projects: [project], jobs: [job] } })), { project, job });
  const resetProject = { ...project, analysis_generation: 1, draft: { start: 0, victory: 172, postroll: 8, reviewed: false, revision: 1, origin: "manual" } };
  await page.route("**/api/projects/demo/reset-analysis", route => route.fulfill({ json: { project: resetProject } }));
  await page.getByRole("button", { name: "重置分析結果" }).click();
  await expect(page.getByRole("button", { name: "選取片段 舊候選" })).toHaveCount(0);
  await expect(page.getByRole("log")).not.toContainText("舊判斷");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await expect(page.getByLabel("開始時間")).toHaveValue("0");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("bosscut:draft:demo")!).revision)).toBe(1);
  let fresh = false;
  await page.route("**/api/codex/chat", async route => {
    const data = route.request().postDataJSON();
    expect(data.context.analysis_generation).toBe(1);
    expect(data.history).toEqual([]);
    expect(data.search_start).toBe(0);
    expect(data.search_end).toBe(180);
    fresh = true;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "重新搜尋", action: null }) + "\n" });
  });
  await page.getByLabel("影片 AI 助手").getByRole("button", { name: "一鍵搜尋成功挑戰" }).click();
  await expect.poll(() => fresh).toBe(true);
});

test("reset during an AI reply cannot restore the old draft or message", async ({ page }) => {
  await setup(page, [project]);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/codex/chat", async route => {
    await gate;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "舊回覆不可套用", project_id: "demo", action: { kind: "set_draft", start: 50, victory: 100, postroll: 8, seconds: null } }) + "\n" }).catch(() => {});
  });
  await page.getByLabel("輸入訊息").fill("幫我調整開頭");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("停止回應")).toBeVisible();
  await page.route("**/api/projects/demo/reset-analysis", route => route.fulfill({ json: { project: {
    ...project, analysis_generation: 1, draft: { start: 0, victory: 172, postroll: 8, reviewed: false, revision: 1, origin: "manual" },
  } } }));
  await page.getByRole("button", { name: "重置分析結果" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("0");
  release();
  await expect(page.getByLabel("停止回應")).not.toBeVisible();
  await expect(page.getByLabel("輸入訊息")).toHaveValue("");
  await expect(page.getByRole("log")).not.toContainText("舊回覆不可套用");
  await expect(page.getByLabel("開始時間")).toHaveValue("0");
});
