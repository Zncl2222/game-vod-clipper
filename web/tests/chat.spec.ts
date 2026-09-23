import { expect, test, type Page } from "@playwright/test";

async function chooseModel(page: Page, name: string) {
  await page.getByRole("combobox", { name: "選擇 AI 模型" }).click();
  await page.getByRole("option", { name, exact: true }).click();
}

async function chooseEffort(page: Page, name: string) {
  await page.getByRole("combobox", { name: "Reasoning effort" }).click();
  await page.getByRole("option", { name, exact: true }).click();
}

const project = { id: "demo", title: "示範專案（僅測試資料）", ready: true, duration: 180, thumbnails: [],
  draft: { start: 10, victory: 100, postroll: 5, reviewed: true, revision: 0, origin: "manual" } };
async function setup(page: Page, projects: unknown[] = [], options: { chat?: boolean; settings?: boolean } = {}) {
  // Fulfilled SSE fixtures close immediately; ignore that artificial disconnect.
  await page.addInitScript(() => {
    window.addEventListener("error", event => {
      if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
    }, true);
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
  if (projects.length) await page.getByRole("button", { name: "看全片", exact: true }).click();
  if (options.chat === false) await page.getByLabel("關閉 AI 對話").click();
  else if (!await page.getByLabel("輸入訊息").isVisible()) await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  if (projects.length && options.settings === true) await page.getByRole("button", { name: "專案工具", exact: true }).click();
  if (options.chat !== false) await expect(page.getByLabel("選擇 AI 模型")).toHaveText("Model A");
}

test("sidebars resize independently, preserve editor state, and remember bounded widths", async ({ page }) => {
  await setup(page, [project]);
  const left = page.getByRole("separator", { name: "調整素材庫寬度" });
  const right = page.getByRole("separator", { name: "調整 AI 側欄寬度" });
  const video = page.locator(".video-wrap video");
  await video.evaluate((node: HTMLVideoElement) => { node.dataset.instance = "original"; node.currentTime = 42; });
  await page.getByLabel("開始時間").fill("25");
  for (const [handle, delta, width] of [[left, 80, 304], [right, -80, 440]] as const) {
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, 350);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + delta, 350, { steps: 8 });
    await page.mouse.up();
    await expect(handle).toHaveAttribute("aria-valuenow", String(width));
  }
  expect((await page.locator(".sidebar").boundingBox())!.width).toBe(304);
  expect((await page.locator(".chat-panel").boundingBox())!.width).toBe(440);
  await expect(page.getByLabel("開始時間")).toHaveValue("25");
  await expect(video).toHaveAttribute("data-instance", "original");
  expect(await video.evaluate((node: HTMLVideoElement) => node.currentTime)).toBe(42);
  await page.reload();
  await expect(left).toHaveAttribute("aria-valuenow", "304");
  await expect(right).toHaveAttribute("aria-valuenow", "440");
  await left.focus();
  await page.keyboard.press("End");
  await expect(left).toHaveAttribute("aria-valuenow", "340");
  await right.focus();
  await page.keyboard.press("End");
  await expect(right).toHaveAttribute("aria-valuenow", "560");
  expect((await page.locator(".main-shell").boundingBox())!.width).toBeGreaterThanOrEqual(540);
  await page.keyboard.press("ArrowRight");
  await expect(right).toHaveAttribute("aria-valuenow", "550");
  await left.dblclick();
  await right.dblclick();
  await expect(left).toHaveAttribute("aria-valuenow", "224");
  await expect(right).toHaveAttribute("aria-valuenow", "360");
  await page.setViewportSize({ width: 320, height: 720 });
  await expect(left).toHaveCount(0);
  await expect(right).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("project menus rename the intended project, preserve drafts, and expose source details", async ({ page }) => {
  const second = { ...project, id: "second", title: "第二支影片", width: 1920, height: 1080 };
  const projects = [{ ...project }, second];
  await setup(page, projects);
  const writes: unknown[] = [];
  await page.route("**/api/projects/*", route => {
    const current = projects.find(item => route.request().url().endsWith(item.id))!;
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON(); writes.push(body); current.title = body.title;
    }
    return route.fulfill({ json: { ...current, source: "/recordings/boss-fight.mp4" } });
  });
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async (text: string) => { document.body.dataset.copied = text; },
    } });
  });
  await page.getByLabel("開始時間").fill("25");
  await page.getByRole("button", { name: "第二支影片 的專案選單", exact: true }).click();
  await expect(page.getByRole("menu")).toBeVisible();
  await expect(page.locator(".project-card[aria-current=page]")).toHaveAttribute("title", project.title);
  await page.screenshot({ path: "../runs/project-menu-desktop.png", fullPage: true });
  await page.getByRole("menuitem", { name: "重新命名…" }).click();
  const dialog = page.getByRole("dialog", { name: "重新命名專案" });
  await expect(dialog.getByLabel("專案名稱")).toBeFocused();
  await dialog.getByLabel("專案名稱").fill("  女武神成功挑戰  ");
  await dialog.getByRole("button", { name: "儲存名稱" }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([{ title: "女武神成功挑戰" }]);
  await expect(page.locator(".project-card").nth(1)).toHaveAttribute("title", "女武神成功挑戰");
  await expect(page.getByLabel("開始時間")).toHaveValue("25");
  await page.locator(".project-card").nth(1).click({ button: "right" });
  await page.getByRole("menuitem", { name: "專案資訊…" }).click();
  const info = page.getByRole("dialog", { name: "專案資訊" });
  await expect(info).toContainText("1920 × 1080");
  await expect(info).toContainText("/recordings/boss-fight.mp4");
  await info.getByRole("button", { name: "複製來源位置" }).click();
  await expect(info.getByRole("button", { name: "已複製", exact: true })).toBeVisible();
  expect(await page.locator("body").getAttribute("data-copied")).toBe("/recordings/boss-fight.mp4");
  await page.keyboard.press("Escape");
  await expect(info).toHaveCount(0);
  await page.locator(".project-card").first().focus();
  await page.keyboard.press("F2");
  await dialog.getByLabel("專案名稱").fill("目前影片新名稱");
  await dialog.getByRole("button", { name: "儲存名稱" }).click();
  await expect(page.locator(".project-card[aria-current=page]")).toHaveAttribute("title", "目前影片新名稱");
  await expect(page.getByLabel("開始時間")).toHaveValue("25");
  await page.reload();
  await expect(page.locator(".project-card").first()).toHaveAttribute("title", "目前影片新名稱");
  await expect(page.locator(".project-card").nth(1)).toHaveAttribute("title", "女武神成功挑戰");
});

test("project deletion confirms, handles failures, and switches away without stale resurrection", async ({ page }) => {
  const second = { ...project, id: "second", title: "第二支影片" };
  await setup(page, [project, second], { settings: false });
  let deletes = 0;
  let fail = true;
  await page.route("**/api/projects/*", route => {
    expect(route.request().method()).toBe("DELETE"); deletes++;
    return route.fulfill(fail ? { status: 500, json: { detail: "測試：無法移除紀錄" } } : { json: { deleted: true } });
  });
  await page.locator(".project-card").first().click({ button: "right" });
  await page.getByRole("menuitem", { name: "刪除專案…" }).click();
  const dialog = page.getByRole("dialog", { name: "刪除專案？" });
  await expect(dialog).toContainText("原始影片與已產生的檔案會保留在磁碟上");
  await expect(dialog.getByRole("button", { name: "取消", exact: true })).toBeFocused();
  await page.screenshot({ path: "../runs/project-delete-desktop.png", fullPage: true });
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  expect(deletes).toBe(0);
  await page.locator(".project-card").first().click({ button: "right" });
  await page.getByRole("menuitem", { name: "刪除專案…" }).click();
  await dialog.getByRole("button", { name: "刪除專案", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("測試：無法移除紀錄");
  await expect(page.locator(".project-card")).toHaveCount(2);
  fail = false;
  await dialog.getByRole("button", { name: "刪除專案", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".project-card")).toHaveCount(1);
  await expect(page.locator(".project-card[aria-current=page]")).toHaveAttribute("title", second.title);
  expect(await page.evaluate(() => localStorage.getItem("bosscut:selected"))).toBe("second");
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), { projects: [project, second], jobs: [] });
  await expect(page.locator(".project-card")).toHaveCount(1);
  await page.getByRole("button", { name: "第二支影片 的專案選單", exact: true }).click();
  await page.getByRole("menuitem", { name: "刪除專案…" }).click();
  await dialog.getByRole("button", { name: "刪除專案", exact: true }).click();
  await expect(page.locator(".project-card")).toHaveCount(0);
  await expect(page.getByRole("region", { name: /值得重播的一戰/ })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("bosscut:selected"))).toBeNull();
  expect(deletes).toBe(3);
});

test("project menu and dialog fit a narrow screen", async ({ page }) => {
  await setup(page, [project], { settings: false, chat: false });
  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByRole("button", { name: `${project.title} 的專案選單`, exact: true }).click();
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  const box = (await menu.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(320);
  await page.screenshot({ path: "../runs/project-menu-mobile.png", fullPage: true });
  await page.getByRole("menuitem", { name: "重新命名…" }).click();
  const dialog = page.getByRole("dialog", { name: "重新命名專案" });
  await expect(dialog.getByLabel("專案名稱")).toBeFocused();
  expect((await dialog.boundingBox())!.width).toBeLessThanOrEqual(320);
  await page.screenshot({ path: "../runs/project-rename-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("canonical candidates replace raw legacy duplicates and long timelines remain scrollable", async ({ page }) => {
  await setup(page, [project]);
  const base = { id: "scan:c1", start: 20, end: 150, victory: null, kind: "fight", confidence: "low",
    boss: "Canonical", summary: "同一場戰鬥", warnings: [], evidence: [], review: "pending", number: 1 };
  const raw = Array.from({ length: 64 }, (_, i) => ({ ...base, id: `scan:old-${i}` }));
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [{ ...project, review_candidates: [base] }],
    jobs: [{ id: "scan", project_id: "demo", kind: "analyze", status: "succeeded", candidates: raw }],
  });
  const track = page.getByLabel("候選時間軸定位", { exact: true });
  await expect(track.locator(".candidate-marker")).toHaveCount(1);
  await expect(page.getByLabel("影片 AI 助手")).toContainText("已標註 1 個候選片段");
  const distinct = Array.from({ length: 20 }, (_, i) => ({ ...base, id: `scan:c${i + 1}`, start: 20 + i, number: i + 1 }));
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [{ ...project, review_candidates: distinct }], jobs: [],
  });
  await expect(track.locator(".candidate-marker")).toHaveCount(20);
  const dimensions = await track.evaluate(el => ({ height: el.clientHeight, scroll: el.scrollHeight }));
  expect(dimensions.scroll).toBe(dimensions.height);
  expect(dimensions.height).toBeGreaterThan(700);
  const bench = page.getByLabel("剪輯與候選檢查區", { exact: true });
  await track.locator(".candidate-marker").last().scrollIntoViewIfNeeded();
  await expect(track.locator(".candidate-marker").last()).toBeInViewport();
  expect(await bench.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  expect(await track.evaluate(el => el.scrollTop)).toBe(0);
  await page.screenshot({ path: "../runs/candidate-canonical-scroll.png", fullPage: true });
});

test("reasoning effort follows model capabilities and reaches chat and search", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/models", route => route.fulfill({ json: { models: [
    { id: "model-a", name: "Model A", is_default: true, effort: "low", supported_efforts: ["low", "high"] },
    { id: "model-b", name: "Model B", effort: "medium", supported_efforts: ["medium"] },
  ] } }));
  await page.reload();
  const effort = page.getByLabel("Reasoning effort");
  await chooseEffort(page, "high");
  const sent: Record<string, unknown>[] = [];
  await page.route("**/api/codex/chat", route => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "收到", action: null }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("分析一下");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByRole("log")).toContainText("收到");
  expect(sent[0].effort).toBe("high");
  await page.locator(".chat-panel").getByRole("button", { name: "一鍵搜尋成功挑戰", exact: true }).click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[1].effort).toBe("high");
  await chooseModel(page, "Model B");
  await expect(effort).toHaveText("default");
  await effort.click();
  await expect(page.getByRole("option", { name: "high", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
});

test("composer model menu supports keyboard selection and restores focus", async ({ page }) => {
  await setup(page);
  const model = page.getByRole("combobox", { name: "選擇 AI 模型" });
  await model.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("listbox")).toBeVisible();
  await expect(page.getByRole("option", { name: "Model A", exact: true })).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByRole("option", { name: "Model B", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(model).toHaveText("Model B");
  await expect(model).toBeFocused();
  await model.click();
  await page.keyboard.press("Home");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(model).toHaveText("Model B");
  await expect(model).toBeFocused();
  await model.click();
  const heading = (await page.getByRole("heading", { name: "想聊些什麼？" }).boundingBox())!;
  // The modal select consumes this click to dismiss rather than activate the page.
  await page.mouse.click(heading.x + 10, heading.y + 10);
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.reload();
  await expect(model).toHaveText("Model B");
});

test("composer picker menus show model details and fit narrow screens", async ({ page }) => {
  await setup(page);
  await page.route("**/api/codex/models", route => route.fulfill({ json: { models: [
    { id: "model-a", name: "GPT-5.6 Luna", description: "日常對話、快速提問與剪輯協作", is_default: true,
      effort: "medium", supported_efforts: ["low", "medium", "high", "xhigh"] },
    { id: "model-b", name: "GPT-6 Astra", description: "複雜問題、多步驟分析與深入討論",
      effort: "high", supported_efforts: ["low", "medium", "high", "xhigh"] },
    { id: "model-c", name: "GPT-5.6 Terra", description: "分析、推理與日常協作",
      effort: "medium", supported_efforts: ["low", "medium", "high"] },
  ] } }));
  await page.reload();
  const model = page.getByRole("combobox", { name: "選擇 AI 模型" });
  await expect(model).toHaveText("GPT-5.6 Luna");
  await model.click();
  await expect(page.getByRole("listbox")).toContainText("日常對話、快速提問與剪輯協作");
  await page.screenshot({ path: "../runs/model-picker-desktop.png", animations: "disabled", clip: { x: 1010, y: 360, width: 430, height: 540 } });
  await page.keyboard.press("Escape");
  await page.getByRole("combobox", { name: "Reasoning effort" }).click();
  await expect(page.getByRole("option", { name: "default", exact: true })).toContainText("medium");
  await page.screenshot({ path: "../runs/effort-picker-desktop.png", animations: "disabled", clip: { x: 1010, y: 360, width: 430, height: 540 } });
  await page.getByRole("option", { name: "high", exact: true }).click();
  await page.getByLabel("輸入訊息").focus();
  await page.screenshot({ path: "../runs/composer-settings-desktop.png", animations: "disabled", clip: { x: 1064, y: 710, width: 376, height: 190 } });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("combobox", { name: "Reasoning effort" }).click();
  await page.screenshot({ path: "../runs/effort-picker-mobile.png", animations: "disabled", fullPage: true });
  await page.keyboard.press("Escape");
  // Long names and many options must remain usable at small widths/heights.
  await page.route("**/api/codex/models", route => route.fulfill({ json: { models: Array.from({ length: 18 }, (_, i) => ({
    id: `model-${i}`, name: `Very long model name for a small screen — ${i}`, is_default: i === 0,
  })) } }));
  await page.setViewportSize({ width: 320, height: 640 });
  await page.reload();
  // The explicitly opened panel remains open across reloads, including a smaller window.
  await expect(model).toBeVisible();
  await model.click();
  await expect(page.getByRole("option", { name: "Very long model name for a small screen — 0", exact: true })).toBeFocused();
  const menu = page.getByRole("listbox");
  await expect(menu).toBeInViewport();
  const box = (await menu.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(320);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(640);
  await page.keyboard.press("End");
  await expect(page.getByRole("option", { name: "Very long model name for a small screen — 17", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(model).toContainText("17");
  await expect(page.getByLabel("Reasoning effort")).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("draft edges drag across the full source and zoom stays fixed during dragging", async ({ page }) => {
  await setup(page, [project]);
  const track = page.locator(".clip-range-track");
  const end = page.getByRole("slider", { name: "勝利位置邊界" });
  await end.scrollIntoViewIfNeeded();
  const bounds = (await track.boundingBox())!;
  const handle = (await end.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 150 / 180, handle.y + handle.height / 2, { steps: 8 });
  await page.mouse.up();
  expect(Number(await end.getAttribute("aria-valuenow"))).toBeCloseTo(150, 0);
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("5");
  await page.getByRole("button", { name: "放大片段", exact: true }).click();
  const ruler = page.locator(".clip-trimmer .source-time-ruler");
  const before = await ruler.textContent();
  const start = page.getByRole("slider", { name: "片段開始邊界" });
  const point = (await start.boundingBox())!;
  await page.mouse.move(point.x + point.width / 2, point.y + point.height / 2);
  await page.mouse.down();
  await page.mouse.move(point.x + point.width / 2 + 35, point.y + point.height / 2, { steps: 8 });
  await page.mouse.up();
  expect(await ruler.textContent()).toBe(before);
  expect(Number(await start.getAttribute("aria-valuenow"))).toBeGreaterThan(10);
});

test("live exploration and finished clips share source timestamps", async ({ page }) => {
  await setup(page, [project], { settings: false });
  const jobs = [
    { id: "scan", project_id: "demo", kind: "analyze", status: "running", phase: "analyzing", sample_start: 120, sample_end: 150,
      candidates: [{ id: "scan:encounter", start: 20, end: 100, victory: null, kind: "fight", confidence: "low",
        boss: "對照候選", summary: "正在核對", warnings: [], evidence: [] }],
      evidence: [{ time: 130, event: "疑似勝利文字" }], coverage: [{ start: 0, end: 90, every: 5 }] },
    { id: "clip-a", project_id: "demo", kind: "export", status: "succeeded", draft: { ...project.draft, origin: "agent" } },
    { id: "clip-b", project_id: "demo", kind: "export", status: "succeeded", draft: { ...project.draft, start: 120, victory: 160, postroll: 8 } },
  ];
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), { projects: [project], jobs });
  await page.getByRole("button", { name: "證據", exact: true }).click();
  const timeline = page.getByLabel("AI 探索與證據", { exact: true });
  await expect(timeline.getByRole("status")).toContainText("00:02:00–00:02:30");
  await expect(timeline.getByRole("button", { name: "查看證據 00:02:10 疑似勝利文字" })).toBeVisible();
  await page.getByRole("tab", { name: "成品 2" }).click();
  const finished = page.getByRole("region", { name: "成品片段", exact: true });
  await expect(finished.getByLabel("成品片段清單").getByRole("button", { name: /^編輯成品 #/ })).toHaveCount(2);
  const sourceTrack = (await page.locator(".clip-range-track").boundingBox())!;
  for (const selector of [".candidate-overview", ".ai-overview-track"]) {
    const track = (await page.locator(selector).first().boundingBox())!;
    expect(track.x).toBeCloseTo(sourceTrack.x, 0);
    expect(track.width).toBeCloseTo(sourceTrack.width, 0);
  }
  await finished.getByRole("button", { name: "編輯成品 #2", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("120");
  await finished.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue(String(project.draft.start));
  await expect(page.locator(".video-wrap video")).toHaveAttribute("src", "/api/projects/demo/media/preview.mp4");
  await page.screenshot({ path: "../runs/ai-workspace-timeline.png", fullPage: true });
});

test("chat export validates timing and saves the draft without requiring a checkbox", async ({ page }) => {
  await setup(page, [project]);
  let exports = 0;
  await page.route("**/api/projects/demo/draft", route => route.fulfill({ json: { ...route.request().postDataJSON(), revision: 1 } }));
  await page.route("**/api/projects/demo/exports", route => {
    expect(route.request().postDataJSON().revision).toBe(1);
    exports++;
    return route.fulfill({ json: { id: "exported" } });
  });
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({
    type: "reply", reply: "提交剪輯", project_id: "demo", action: { kind: "export", start: null, victory: null, postroll: null, seconds: null },
  }) + "\n" }));
  await page.getByLabel("開始時間").fill("179");
  await page.getByLabel("輸入訊息").fill("匯出片段");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByRole("log")).toContainText("請先修正剪輯時間範圍");
  expect(exports).toBe(0);
  await page.getByLabel("開始時間").fill("10");
  await page.getByLabel("輸入訊息").fill("匯出片段");
  await page.getByLabel("送出訊息").click();
  await expect.poll(() => exports).toBe(1);
});

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
  await chooseModel(page, "Model B");
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

test("one assistant continues ordinary chat and applies requested tools after selecting a video", async ({ page }) => {
  await setup(page);
  const input = page.getByLabel("輸入訊息");
  const log = page.getByRole("log");
  await expect(page.getByRole("tab", { name: /一般聊天|剪輯助理/ })).toHaveCount(0);
  const requests: unknown[] = [];
  await page.route("**/api/codex/chat", route => {
    const body = route.request().postDataJSON(); requests.push(body);
    const edit = body.message === "收尾改成8秒";
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply",
      reply: "收到：" + body.message, project_id: body.context?.project_id,
      action: edit ? { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } : null }) + "\n" });
  });
  await input.fill("今天想聊遊戲"); await input.press("Enter");
  await expect(log).toContainText("收到：今天想聊遊戲");
  expect(requests[0]).toMatchObject({ context: null, history: [] });
  await page.evaluate(project => window.dispatchEvent(new CustomEvent("fixture:state", {
    detail: { projects: [project], jobs: [] },
  })), project);
  await expect(page.locator(".chat-context")).toContainText(project.title);
  await expect(page.getByRole("tab", { name: /一般聊天|剪輯助理/ })).toHaveCount(0);
  await input.fill("幫我想一個直播標題"); await input.press("Enter");
  await expect(log).toContainText("收到：幫我想一個直播標題");
  expect(requests[1]).toMatchObject({ context: { project_id: "demo" }, history: [
    { role: "user", content: "今天想聊遊戲" }, { role: "assistant", content: "收到：今天想聊遊戲" },
  ] });
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("5");
  await input.fill("收尾改成8秒"); await input.press("Enter");
  await expect(log).toContainText("已更新草稿");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  expect(requests[2]).toMatchObject({ history: [
    { role: "user", content: "今天想聊遊戲" }, { role: "assistant", content: "收到：今天想聊遊戲" },
    { role: "user", content: "幫我想一個直播標題" }, { role: "assistant", content: "收到：幫我想一個直播標題" },
  ] });
  await input.fill("接著還想問的問題");
  await page.reload();
  await expect(input).toHaveValue("接著還想問的問題");
  await expect(log).toContainText("已更新草稿");
  await page.getByLabel("新對話").click();
  await expect(input).toHaveValue("");
  await expect(log).not.toContainText("今天想聊遊戲");
});

test("an incomplete draft still allows ordinary chat, search and a requested timing repair", async ({ page }) => {
  await setup(page, [project]);
  await page.getByLabel("開始時間").fill("120");
  const requests: unknown[] = [];
  await page.route("**/api/codex/chat", route => {
    const body = route.request().postDataJSON(); requests.push(body);
    expect(body.context).toMatchObject({ project_id: "demo", draft: null });
    const repair = body.message === "設定開始10秒、勝利100秒、收尾8秒";
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply",
      reply: body.intent === "search" ? "搜尋已建立" : "收到：" + body.message, project_id: "demo",
      action: repair ? { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } : null }) + "\n" });
  });
  const input = page.getByLabel("輸入訊息");
  await input.fill("幫我想直播標題"); await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("收到：幫我想直播標題");
  await expect(page.getByLabel("開始時間")).toHaveValue("120");
  await input.fill("搜尋後再送出的提問");
  await page.locator(".chat-panel").getByRole("button", { name: "一鍵搜尋成功挑戰", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("搜尋已建立");
  await expect(input).toHaveValue("搜尋後再送出的提問");
  expect(requests[1]).toMatchObject({ intent: "search", search_start: 0, search_end: 180 });
  await input.fill("設定開始10秒、勝利100秒、收尾8秒"); await input.press("Enter");
  await expect(page.getByLabel("開始時間")).toHaveValue("10");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  await expect(page.getByRole("log")).toContainText("已更新草稿");
});

test("browsing clips preserves a pending assistant reply and unsent text without stealing focus", async ({ page }) => {
  await setup(page, [project]);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/codex/chat", async route => {
    await gate;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "收尾調整為8秒", project_id: "demo",
      action: { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } }) + "\n" });
  });
  const input = page.getByLabel("輸入訊息");
  await input.fill("收尾改成8秒"); await input.press("Enter");
  await expect(page.getByLabel("停止回應")).toBeVisible();
  await input.fill("下一個問題");
  const clips = page.getByRole("tab", { name: "成品 0" });
  await clips.click(); release();
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  await expect(clips).toBeFocused();
  await expect(input).not.toBeVisible();
  await page.getByRole("tab", { name: "AI 助理", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("收尾調整為8秒");
  await expect(page.getByRole("log")).toContainText("已更新草稿");
  await expect(input).toHaveValue("下一個問題");
});

test("failed assistant replies retain unsent text and can be retried", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson",
    body: JSON.stringify({ type: "error", detail: "測試連線失敗" }) + "\n" }));
  const input = page.getByLabel("輸入訊息");
  await input.fill("幫我想一個標題"); await input.press("Enter");
  await expect(page.getByRole("alert")).toContainText("測試連線失敗");
  await expect(input).toHaveValue("幫我想一個標題");
  await page.route("**/api/codex/chat", route => {
    expect(route.request().postDataJSON().history).toEqual([]);
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "重試成功", action: null }) + "\n" });
  });
  await input.press("Enter");
  await expect(page.getByRole("log")).toContainText("重試成功");
  await expect(input).toHaveValue("");
});

for (const version of ["v1", "v2"]) {
  test("unified assistant migrates " + version + " history and excludes other projects from model context", async ({ page }) => {
    await page.addInitScript(version => {
      if (sessionStorage.getItem("bosscut:chat:v3")) return;
      const general = [
        { id: "general-user", role: "user", content: "舊的聊天訊息" },
        { id: "general-ai", role: "assistant", content: "舊的聊天回覆" },
      ];
      const editing = [
        { id: "edit-user", role: "user", content: "舊的剪輯請求", project_id: "demo", analysis_generation: 0 },
        { id: "edit-ai", role: "assistant", content: "舊的剪輯回覆", project_id: "demo", analysis_generation: 0 },
      ];
      sessionStorage.setItem("bosscut:chat:" + version, JSON.stringify(version === "v1" ? [...general, ...editing] : {
        chat: { messages: general, input: "未送出的聊天" }, edit: { messages: editing, input: "未送出的剪輯要求" },
      }));
    }, version);
    await setup(page, [project, { ...project, id: "another", title: "另一支影片" }]);
    const log = page.getByRole("log");
    await expect(log).toContainText("舊的聊天回覆");
    await expect(log).toContainText("舊的剪輯回覆");
    await expect(page.getByLabel("輸入訊息")).toHaveValue(version === "v2" ? "未送出的聊天\n\n未送出的剪輯要求" : "");
    await page.reload();
    await expect(log).toContainText("舊的聊天回覆");
    await expect(log).toContainText("舊的剪輯回覆");
    await page.getByRole("button", { name: /另一支影片/ }).first().click();
    await page.route("**/api/codex/chat", route => {
      const body = route.request().postDataJSON();
      expect(body.context.project_id).toBe("another");
      expect(body.history).toEqual([
        { role: "user", content: "舊的聊天訊息" }, { role: "assistant", content: "舊的聊天回覆" },
      ]);
      return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "另一支影片的回覆", action: null }) + "\n" });
    });
    await page.getByLabel("輸入訊息").fill("查看這支影片"); await page.getByLabel("輸入訊息").press("Enter");
    await expect(log).toContainText("另一支影片的回覆");
    expect(await page.evaluate(() => sessionStorage.getItem("bosscut:chat:v2"))).toBeNull();
    expect(await page.evaluate(() => sessionStorage.getItem("bosscut:chat:v1"))).toBeNull();
  });
}

test("merging long unsent drafts preserves all text and enforces the message limit", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("bosscut:chat:v3")) return;
    sessionStorage.setItem("bosscut:chat:v2", JSON.stringify({
      chat: { messages: [], input: " ".repeat(3999) + "聊" }, edit: { messages: [], input: "剪" + " ".repeat(3999) },
    }));
  });
  await setup(page);
  const input = page.getByLabel("輸入訊息");
  const merged = " ".repeat(3999) + "聊\n\n剪" + " ".repeat(3999);
  await expect(input).toHaveValue(merged);
  await expect(page.getByLabel("送出訊息")).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText("每則訊息最多 4,000 字");
  await page.reload();
  await expect(input).toHaveValue(merged);
  let requests = 0;
  await page.route("**/api/codex/chat", route => {
    requests++;
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "不應送出", action: null }) + "\n" });
  });
  await input.press("Enter");
  await expect(input).toHaveValue(merged);
  expect(requests).toBe(0);
  await input.fill("分次送出");
  await expect(page.getByLabel("送出訊息")).toBeEnabled();
  await expect(input).not.toHaveAttribute("aria-invalid", "true");
});

test("switching accounts clears the unified transcript and saved input", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "舊帳號的回覆", action: null }) + "\n" }));
  await page.getByLabel("輸入訊息").fill("聊天訊息"); await page.getByLabel("輸入訊息").press("Enter");
  await expect(page.getByRole("log")).toContainText("舊帳號的回覆");
  await page.getByLabel("輸入訊息").fill("未送出的問題");
  await page.route("**/api/codex", route => route.fulfill({ json: { available: true, auth_mode: "chatgpt", email: "another@example.test", detail: "已切換帳號" } }));
  await page.getByLabel("帳號設定", { exact: true }).click();
  await page.getByRole("button", { name: "重新整理狀態", exact: true }).click();
  await expect(page.getByText("another@example.test", { exact: false })).toBeVisible();
  await expect(page.getByRole("log")).not.toContainText("舊帳號的回覆");
  await expect(page.getByLabel("輸入訊息")).toHaveValue("");
  const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("bosscut:chat:v3")!));
  expect(saved).toEqual({ messages: [], input: "" });
});

test("editor commands update draft and invalidate review without media processing", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/chat", async (route) => {
    expect(route.request().postDataJSON().context.draft.postroll).toBe(5);
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "收尾改為 8 秒。", model: "model-a", project_id: "demo",
      action: { kind: "set_draft", start: 10, victory: 100, postroll: 8, seconds: null } }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("收尾改成8秒");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  await expect(page.getByRole("log")).toContainText("已更新草稿");
  await expect(page.getByLabel("勝利後收尾")).toHaveClass(/ai-target/);
  await expect(page.getByLabel("開始時間")).not.toHaveClass(/ai-target/);
  await page.screenshot({ path: "../runs/chat-editor.png" });
});

test("late reply cannot overwrite a newer manual edit", async ({ page }) => {
  await setup(page, [project]);
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
  // A mismatched backend response in the new metadata panel must not unmount
  // the conversation or the editor (this fixture returns account data for it).
  await page.locator(".usage-panel > summary").click();
  await expect(page.locator(".usage-panel")).toContainText("Token 紀錄格式異常");
  await expect(page.getByLabel("輸入訊息")).toBeVisible();
  await page.locator(".usage-panel > summary").click();
  await page.screenshot({ path: "../runs/chat-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByLabel("關閉 AI 對話").click();
  await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
});

test("missing model route explains backend mismatch instead of Not Found", async ({ page }) => {
  await setup(page);
  await page.route("**/api/codex/models", (route) => route.fulfill({ status: 404, json: { detail: "Not Found" } }));
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("請重新啟動 BossCut 後端");
  await expect(page.getByRole("alert")).not.toContainText("Not Found");
});

test("composer grows with content up to a cap and shrinks when cleared", async ({ page }) => {
  await setup(page);
  const input = page.getByLabel("輸入訊息");
  const height = () => input.evaluate((element) => element.getBoundingClientRect().height);
  const collapsedHeight = await height();
  expect(collapsedHeight).toBeLessThanOrEqual(48);
  await input.fill("第一行\n第二行\n第三行");
  expect(await height()).toBeGreaterThan(50);
  await input.fill(Array(20).fill("這是一行較長的訊息內容").join("\n"));
  expect(await height()).toBeLessThanOrEqual(108);
  await expect(input).toHaveCSS("overflow-y", "auto");
  await input.fill("");
  expect(await height()).toBeCloseTo(collapsedHeight, 0);
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
  await expect(page.getByRole("button", { name: "AI 正在查看 00:00:30 至 00:01:30", includeHidden: true })).toBeAttached();
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
  await expect(page.getByRole("button", { name: "AI 正在查看 00:00:30 至 00:01:30", includeHidden: true })).toHaveCount(0);
});

test("one-click search and typed search use the chat endpoint and shared result card", async ({ page }) => {
  await setup(page, [project]);
  await chooseModel(page, "Model B");
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
  await page.locator(".workbench-review-tools > summary").click();
  await expect(workspace.getByRole("button", { name: "選取片段 測試 Boss" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await workspace.screenshot({ path: "../runs/clip-workspace.png" });
  const handle = workspace.getByRole("slider", { name: "片段開始邊界" });
  await handle.scrollIntoViewIfNeeded();
  const bounds = (await handle.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 25, bounds.y + bounds.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(Number(await page.getByLabel("開始時間").inputValue())).toBeGreaterThan(20);
  await workspace.getByRole("slider", { name: "勝利位置邊界" }).focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect(workspace.getByRole("slider", { name: "勝利位置邊界" })).toHaveAttribute("aria-valuenow", "101");
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
  await page.locator(".workbench-review-tools > summary").click();
  await page.getByRole("button", { name: "選取片段 新候選" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
});

test("completed exports directly enter the original editor without starting new jobs", async ({ page }) => {
  await setup(page, [project]);
  await page.evaluate(project => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "finished-export", project_id: "demo", kind: "export", status: "succeeded", draft: project.draft }],
  } })), project);
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  const player = page.locator(".video-wrap video");
  await expect(player).toHaveAttribute("src", "/api/projects/demo/media/preview.mp4");
  await expect(player).toHaveAttribute("preload", "metadata");
  await expect(player).not.toHaveAttribute("controls");
  await expect(page.getByRole("button", { name: "回到原片", exact: true })).toBeVisible();
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
  await page.getByRole("button", { name: "證據", exact: true }).click();
  await workspace.getByRole("button", { name: /查看證據.*Boss 血條變化/ }).click();
  expect(await player.evaluate((el: HTMLVideoElement) => el.currentTime)).toBe(60);
  await page.locator(".workbench-review-tools > summary").click();
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

test("candidate bars load their range once and scrub without changing its boundaries", async ({ page }) => {
  await setup(page, [project], { chat: false });
  const segment = { id: "scrub:one", start: 20, end: 100, victory: null, kind: "fight", confidence: "low",
    boss: "可拖曳候選", summary: "測試定位", warnings: [], evidence: [] };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [{ id: "scrub", project_id: "demo", kind: "analyze", status: "succeeded", candidates: [segment] }],
  });
  const timeline = page.getByLabel("候選時間軸定位", { exact: true });
  // Coordinate-based mouse input must clear the sticky header as well as the viewport edge.
  await timeline.evaluate(el => el.scrollIntoView({ block: "center" }));
  const bounds = (await timeline.boundingBox())!;
  const marker = (await timeline.locator(".candidate-marker").boundingBox())!;
  const x = (seconds: number) => bounds.x + bounds.width * seconds / 180;
  const y = marker.y + marker.height / 2;
  const video = page.locator(".video-wrap video");
  const current = () => video.evaluate((v: HTMLVideoElement) => v.currentTime);
  await page.mouse.click(x(60), y);
  await expect(page.getByLabel("片段 #1 詳情")).toBeVisible();
  await expect.poll(current).toBeCloseTo(60, 0);
  await page.mouse.move(x(65), y);
  await page.mouse.down();
  await page.mouse.move(x(90), y, { steps: 6 });
  await expect.poll(current).toBeCloseTo(90, 0);
  await page.mouse.move(bounds.x + bounds.width + 30, y, { steps: 4 });
  await page.mouse.up();
  await expect.poll(current).toBe(180);
  await page.mouse.click(x(120), bounds.y + bounds.height - 3);
  await expect.poll(current).toBeCloseTo(120, 0);
  await timeline.focus();
  await page.keyboard.press("Home");
  await expect.poll(current).toBe(0);
  await timeline.locator(".candidate-marker").focus();
  await page.keyboard.press("Enter");
  await expect.poll(current).toBe(20);
  await page.keyboard.press("ArrowRight");
  await expect.poll(current).toBe(21);
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
});

test("candidate selection and scrubbing use the same source range as the draft", async ({ page }) => {
  await setup(page, [project], { chat: false });
  const segment = { id: "source:one", start: 20, end: 100, victory: null, kind: "fight", confidence: "low",
    boss: "原片候選", summary: "測試原片定位", warnings: [], evidence: [] };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [{ id: "source", project_id: "demo", kind: "analyze", status: "succeeded", candidates: [segment] }],
  });
  const row = page.getByRole("group", { name: "候選時間軸定位", exact: true });
  await row.evaluate(el => el.scrollIntoView({ block: "center" }));
  const bounds = (await row.boundingBox())!;
  const x = (seconds: number) => bounds.x + bounds.width * seconds / 180;
  const y = bounds.y + bounds.height / 2;
  const current = () => page.locator(".video-wrap video").evaluate((video: HTMLVideoElement) => video.currentTime);
  await page.mouse.click(x(60), y);
  await expect.poll(current).toBeCloseTo(60, 0);
  await page.mouse.move(x(65), y);
  await page.mouse.down();
  await page.mouse.move(x(90), y, { steps: 6 });
  await expect.poll(current).toBeCloseTo(90, 0);
  await page.mouse.move(bounds.x + bounds.width + 15, y, { steps: 5 });
  await page.mouse.up();
  await expect.poll(current).toBe(180);
  // Empty parts of this row use the same source-time mapping as the color bar.
  await page.mouse.click(x(120), y);
  await expect.poll(current).toBeCloseTo(120, 0);
  await row.focus();
  await page.keyboard.press("Home");
  await expect.poll(current).toBe(0);
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(current).toBe(10);
  await row.getByRole("button").press("Enter");
  await expect.poll(current).toBe(20);
  await row.getByRole("button").press("ArrowRight");
  await expect.poll(current).toBe(21);
  // The draft is overlaid on each AI row, not a separate source track.
  await expect(page.getByRole("group", { name: "草稿原片對照", exact: true })).toHaveCount(0);
  await expect(row.locator(".source-selection-fill")).toBeVisible();
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await row.scrollIntoViewIfNeeded();
  const updated = (await row.boundingBox())!;
  await page.mouse.click(updated.x + updated.width * 75 / 180, updated.y + updated.height / 2);
  await expect.poll(current).toBeCloseTo(75, 0);
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
  await expect(page.getByLabel("勝利時間")).toHaveValue("92");
});

test("zoomed source comparison maps positions to the visible source window", async ({ page }) => {
  await setup(page, [project], { chat: false });
  const segment = { id: "zoom:one", start: 0, end: 170, victory: null, kind: "fight", confidence: "low",
    boss: "跨出可視範圍的候選", summary: "測試縮放定位", warnings: [], evidence: [] };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [{ id: "zoom", project_id: "demo", kind: "analyze", status: "succeeded", candidates: [segment] }],
  });
  await page.getByRole("button", { name: "放大片段", exact: true }).click();
  const source = page.getByRole("slider", { name: "播放位置", exact: true });
  const from = Number(await source.getAttribute("min"));
  const to = Number(await source.getAttribute("max"));
  expect(from).toBeGreaterThan(0);
  expect(to).toBeLessThan(170);
  const row = page.getByRole("group", { name: "候選時間軸定位", exact: true });
  await row.evaluate(el => el.scrollIntoView({ block: "center" }));
  const bounds = (await row.boundingBox())!;
  const y = bounds.y + bounds.height / 2;
  const current = () => page.locator(".video-wrap video").evaluate((video: HTMLVideoElement) => video.currentTime);
  await page.mouse.click(bounds.x + bounds.width * .5, y);
  await expect.poll(current).toBeCloseTo(from + (to - from) * .5, 0);
  await page.mouse.move(bounds.x + bounds.width * .6, y);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * .8, y, { steps: 5 });
  await expect.poll(current).toBeCloseTo(from + (to - from) * .8, 0);
  await page.mouse.move(bounds.x - 15, y, { steps: 5 });
  await page.mouse.up();
  await expect.poll(current).toBe(from);
  await expect(source).toHaveAttribute("min", String(from));
  await expect(source).toHaveAttribute("max", String(to));
  await expect(page.getByLabel("開始時間")).toHaveValue("0");
});

test("uncertain candidates keep stable numbers and become editable as soon as selected", async ({ page }) => {
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
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await expect(timeline.locator(".candidate-marker")).toHaveCount(3);
  await timeline.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.getByLabel("片段 #1 詳情")).toContainText("戰鬥尚未確認結果");
  await expect(page.getByRole("button", { name: "編輯片段 #1 區間" })).toBeVisible();
  await expect(page.getByLabel("開始時間")).toHaveValue("20");
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
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await expect(timeline.locator(".candidate-marker")).toHaveCount(3);
  await expect(page.getByLabel("片段 #2 詳情")).toContainText("00:01:02.000");
  await expect(page.getByLabel("片段 #2 詳情")).toContainText("尚未驗證");
  await page.getByRole("button", { name: "編輯片段 #2 區間" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("60");
  await expect(page.getByLabel("勝利時間")).toHaveValue("107");
  await page.screenshot({ path: "../runs/candidate-review-desktop.png", fullPage: true });
  await page.route("**/api/events", route => route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(nextState)}\n\n` }));
  await page.reload();
  await timeline.getByRole("button", { name: /時間軸片段 #2 / }).click();
  await expect(page.getByLabel("片段 #2 核對標籤")).toHaveValue("keep");
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({
    type: "reply", project_id: "demo", reply: "查看 #3", action: { kind: "select_candidate", candidate_id: third.id,
      start: null, victory: null, postroll: null, seconds: null },
  }) + "\n" }));
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await page.getByLabel("輸入訊息").fill("查看 #3");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("片段 #3 詳情")).toContainText("死亡／重試");
  await expect(page.getByRole("log")).toContainText("已選取 #3");
  await page.getByLabel("關閉 AI 對話").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../runs/candidate-review-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("desktop keeps editing visible and mobile uses one unclipped workspace", async ({ page }) => {
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
    const selection = await core.getByRole("slider", { name: "勝利位置邊界" }).boundingBox();
    const footer = await core.getByRole("button", { name: "匯出 MP4" }).boundingBox();
    await page.screenshot({ path: `../runs/simple-editor-${viewport.width}.png` });
    expect(video!.y).toBeGreaterThanOrEqual(0);
    expect(selection!.y).toBeGreaterThan(video!.y + video!.height);
    if (viewport.width > 640) expect(footer!.y + footer!.height).toBeLessThan(viewport.height);
    else {
      await core.getByRole("button", { name: "匯出 MP4" }).scrollIntoViewIfNeeded();
      await expect(core.getByRole("button", { name: "匯出 MP4" })).toBeInViewport();
    }
    expect(await page.locator(".main-shell").evaluate(el => el.scrollTop)).toBe(0);
    await expect(page.getByRole("dialog", { name: "專案工具", exact: true })).not.toBeVisible();
    await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
    await page.screenshot({ path: `../runs/simple-editor-${viewport.width}.png` });
  }
});

test("reset viewing progress keeps candidates, unsaved edits and exports while starting a fresh search", async ({ page }) => {
  await setup(page, [project]);
  await page.getByRole("button", { name: "證據", exact: true }).click();
  await page.route("**/api/codex/chat", route => route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "OLD_VIEWING_CONTEXT", action: null }) + "\n" }));
  await page.getByLabel("輸入訊息").fill("分析進度如何？");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByRole("log")).toContainText("OLD_VIEWING_CONTEXT");
  const job = { id: "old-result", kind: "analyze", project_id: "demo", status: "succeeded", resumable: true, result: {
    project_id: "demo", status: "candidate", can_continue: true, start: 20, victory: 100, postroll: 8,
    boss: "保留候選", summary: "待人工確認", evidence: [{ time: 100, event: "勝利文字" }], warnings: [],
    coverage: [{ start: 0, end: 120, every: 5 }], frames: 100, rounds: 8, model: "model-a" } };
  const exported = { id: "export", kind: "export", project_id: "demo", status: "succeeded", draft: project.draft };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [job, exported],
  });
  await page.getByLabel("開始時間").fill("37");
  await expect(page.getByLabel("AI 全片抽樣進度").locator(".ai-coverage")).toHaveCount(1);
  await expect(page.getByLabel("影片 AI 助手").getByRole("button", { name: "接續細查" })).toBeVisible();
  const retainedProject = { ...project, analysis_generation: 1, editor_generation: 0 };
  const retainedJob = { ...job, progress_reset: true, resumable: false, coverage: [], result: { ...job.result, can_continue: false, coverage: [] } };
  const nextState = { projects: [retainedProject], jobs: [retainedJob, exported] };
  let resets = 0;
  await page.route("**/api/projects/demo/reset-analysis-progress", route => {
    resets++;
    return route.fulfill({ json: { project: retainedProject, jobs: nextState.jobs } });
  });
  await page.getByRole("button", { name: "重置 AI 查看進度" }).click();
  await expect(page.getByLabel("AI 全片抽樣進度").locator(".ai-coverage")).toHaveCount(0);
  await expect(page.locator(".review-coverage, .ai-signal, .review-evidence-pin")).toHaveCount(0);
  await expect(page.getByLabel("AI 即時工作狀態")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "接續細查", exact: true })).toHaveCount(0);
  await page.locator(".workbench-review-tools > summary").click();
  await expect(page.getByRole("button", { name: "選取片段 保留候選" })).toBeVisible();
  await expect(page.getByLabel("開始時間")).toHaveValue("37");
  await expect(page.locator(".finished-clip-open")).toHaveCount(1);
  await expect(page.getByRole("log")).not.toContainText("OLD_VIEWING_CONTEXT");
  await expect(page.getByRole("button", { name: "重置 AI 查看進度" })).toBeDisabled();
  expect(resets).toBe(1);
  // Persistence must preserve the local edit as well as clear the old task UI.
  await page.route("**/api/events", route => route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(nextState)}\n\n` }));
  await page.reload();
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("37");
  await expect(page.getByRole("button", { name: "接續細查", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("AI 全片抽樣進度").locator(".ai-coverage")).toHaveCount(0);
  await page.locator(".chat-search-options > summary").click();
  await page.getByLabel("搜尋起點（秒）").fill("30");
  await page.getByLabel("搜尋終點（秒）").fill("150");
  let fresh = false;
  await page.route("**/api/codex/chat", route => {
    const data = route.request().postDataJSON();
    expect(data.intent).toBe("search");
    expect(data.context.analysis_generation).toBe(1);
    expect(data.context.draft.start).toBe(37);
    expect(data.history).toEqual([]);
    expect([data.search_start, data.search_end]).toEqual([30, 150]);
    fresh = true;
    return route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "全新搜尋已建立", action: null }) + "\n" });
  });
  await page.getByLabel("影片 AI 助手").getByRole("button", { name: "一鍵搜尋成功挑戰" }).click();
  await expect.poll(() => fresh).toBe(true);
});

test("viewing progress reset reports failure and prevents duplicate resets while cancelling a running search", async ({ page }) => {
  await setup(page, [project], { settings: false });
  await page.getByRole("button", { name: "證據", exact: true }).click();
  const job = { id: "running", kind: "analyze", project_id: "demo", status: "running", phase: "analyzing",
    coverage: [{ start: 0, end: 90, every: 5 }], sample_start: 90, sample_end: 150, frames: 20, rounds: 1 };
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), { projects: [project], jobs: [job] });
  await page.route("**/api/projects/demo/reset-analysis-progress", route => route.fulfill({ status: 500, json: { detail: "分析檔案清理未完成，請重試重置。" } }));
  const button = page.getByRole("button", { name: "重置 AI 查看進度" });
  await button.click();
  await expect(page.getByRole("alert")).toContainText("請重試重置");
  await expect(button).toBeEnabled();
  await expect(page.getByLabel("AI 全片抽樣進度").locator(".ai-coverage")).toHaveCount(1);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let calls = 0;
  await page.route("**/api/projects/demo/reset-analysis-progress", async route => {
    calls++;
    await gate;
    return route.fulfill({ json: { project: { ...project, analysis_generation: 1, editor_generation: 0 },
      jobs: [{ ...job, status: "cancelled", progress_reset: true, coverage: [] }] } });
  });
  await button.click();
  await expect(page.getByRole("button", { name: "重置中…" })).toBeDisabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重置分析結果" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "停止搜尋" })).toBeDisabled();
  release();
  await expect(button).toBeDisabled();
  await expect(page.getByLabel("AI 全片抽樣進度").locator(".ai-coverage")).toHaveCount(0);
  await expect(page.getByLabel("AI 搜尋任務")).toHaveCount(0);
  expect(calls).toBe(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("關閉 AI 對話").click();
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeInViewport();
});

test("viewing progress reset rejects a late AI edit without remounting the editor", async ({ page }) => {
  await setup(page, [project]);
  await page.getByRole("button", { name: "證據", exact: true }).click();
  await page.getByLabel("開始時間").fill("37");
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [{ id: "stopped", project_id: "demo", kind: "analyze", status: "cancelled", resumable: true }],
  });
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/codex/chat", async route => {
    await gate;
    await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", reply: "LATE_OLD_EDIT", project_id: "demo",
      action: { kind: "set_draft", start: 50, victory: 100, postroll: 8, seconds: null } }) + "\n" }).catch(() => {});
  });
  await page.getByLabel("輸入訊息").fill("幫我調整開頭");
  await page.getByLabel("送出訊息").click();
  await expect(page.getByLabel("停止回應")).toBeVisible();
  await page.route("**/api/projects/demo/reset-analysis-progress", route => route.fulfill({ json: {
    project: { ...project, analysis_generation: 1, editor_generation: 0 }, jobs: [],
  } }));
  await page.getByRole("button", { name: "重置 AI 查看進度" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("37");
  release();
  await expect(page.getByLabel("停止回應")).not.toBeVisible();
  await expect(page.getByLabel("輸入訊息")).toHaveValue("");
  await expect(page.getByRole("log")).not.toContainText("LATE_OLD_EDIT");
  await expect(page.getByLabel("開始時間")).toHaveValue("37");
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

test("six-hour VOD zooms to seconds, pans across the source and keeps all tracks aligned", async ({ page }) => {
  const long = { ...project, duration: 21600, draft: { ...project.draft, start: 10800, victory: 10920, postroll: 8 } };
  await setup(page, [long]);
  const seek = page.getByRole("slider", { name: "播放位置", exact: true });
  const position = page.getByRole("slider", { name: "可視範圍位置", exact: true });
  const ruler = page.locator(".clip-trimmer .source-time-ruler");
  await page.getByRole("button", { name: "放大片段", exact: true }).click();
  await expect(seek).toHaveAttribute("min", "10795");
  await expect(seek).toHaveAttribute("max", "10933");
  await page.locator(".preview-panel .video-wrap video").evaluate((video: HTMLVideoElement) => {
    video.currentTime = 10800; video.dispatchEvent(new Event("timeupdate"));
  });
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: "放大時間軸", exact: true }).click();
  const from = Number(await seek.getAttribute("min"));
  const to = Number(await seek.getAttribute("max"));
  expect(to - from).toBeCloseTo(5);
  await expect(page.getByRole("button", { name: "放大時間軸", exact: true })).toBeDisabled();
  const before = await ruler.textContent();
  const edge = page.getByRole("slider", { name: "片段開始邊界", exact: true });
  const handle = (await edge.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 35, handle.y + handle.height / 2, { steps: 5 });
  await page.mouse.up();
  const changed = Number(await edge.getAttribute("aria-valuenow"));
  expect(changed).toBeGreaterThan(10800);
  expect(changed).toBeLessThan(10801);
  expect(await ruler.textContent()).toBe(before);
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("8");
  expect(new Set(await page.locator(".source-time-ruler").allTextContents()).size).toBe(1);
  await position.press("End");
  await expect(seek).toHaveAttribute("min", "21595");
  await expect(seek).toHaveAttribute("max", "21600");
  await expect(edge).toHaveCount(0);
  await position.press("Home");
  await expect(seek).toHaveAttribute("min", "0");
  await expect(seek).toHaveAttribute("max", "5");
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await expect(seek).toHaveAttribute("max", "21600");
  await expect(edge).toHaveAttribute("aria-valuenow", String(changed));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("timeline wheel zoom anchors the pointed time and navigator pans without editing the draft", async ({ page }) => {
  await setup(page, [{ ...project, duration: 21600 }]);
  const track = page.locator(".clip-range-track");
  const seek = page.getByRole("slider", { name: "播放位置", exact: true });
  const wheel = async (ctrlKey: boolean) => track.evaluate((el, ctrlKey) => {
    const box = el.getBoundingClientRect();
    const event = new WheelEvent("wheel", { bubbles: true, cancelable: true, ctrlKey, deltaY: -100,
      clientX: box.left + box.width * .75, clientY: box.top + 10 });
    el.dispatchEvent(event);
    return { prevented: event.defaultPrevented, fraction: (event.clientX - box.left) / box.width };
  }, ctrlKey);
  expect((await wheel(false)).prevented).toBe(false);
  await expect(seek).toHaveAttribute("min", "0");
  const pointed = await wheel(true);
  expect(pointed.prevented).toBe(true);
  const from = Number(await seek.getAttribute("min"));
  const to = Number(await seek.getAttribute("max"));
  expect(from + (to - from) * pointed.fraction).toBeCloseTo(21600 * pointed.fraction);
  const navigator = page.getByRole("slider", { name: "可視範圍位置", exact: true });
  await navigator.evaluate(el => el.scrollIntoView({ block: "center" }));
  await navigator.press("End");
  await expect(seek).toHaveAttribute("max", "21600");
  expect(Number(await seek.getAttribute("max")) - Number(await seek.getAttribute("min"))).toBeCloseTo(to - from);
  await expect(page.getByLabel("開始時間")).toHaveValue("10");
});

test("model settings stay readable on mobile and exported file location is discoverable", async ({ page }) => {
  await setup(page, [project]);
  await page.route("**/api/codex/models", route => route.fulfill({ json: { models: [
    { id: "model-a", name: "GPT-5.6 Luna", is_default: true, effort: "medium", supported_efforts: ["low", "medium", "high", "xhigh"] },
  ] } }));
  await page.reload();
  await chooseEffort(page, "high");
  const controls = page.getByRole("group", { name: "AI 回應設定" });
  await expect(controls).toContainText("GPT-5.6 Luna");
  await expect(controls).toContainText("high");
  await page.screenshot({ path: "../runs/timeline-model-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("選擇 AI 模型")).toBeInViewport();
  await expect(page.getByLabel("Reasoning effort")).toBeInViewport();
  await page.screenshot({ path: "../runs/timeline-model-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("關閉 AI 對話").click();
  await page.evaluate(project => window.dispatchEvent(new CustomEvent("fixture:state", { detail: {
    projects: [project], jobs: [{ id: "finished-export", project_id: "demo", kind: "export", status: "succeeded", draft: project.draft }],
  } })), project);
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByText("檔案儲存位置", { exact: true }).click();
  await expect(page.getByRole("region", { name: "成品片段", exact: true }).getByText("clips/web/demo/finished-export.mp4", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "下載成品 #1 MP4", exact: true })).toHaveAttribute("href", "/api/jobs/finished-export/download");
});

test("large source preview stays visible while candidate review scrolls independently", async ({ page }) => {
  await page.addInitScript(() => window.addEventListener("error", event => {
    if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
  }, true));
  await setup(page, [project], { settings: false });
  const video = page.locator(".preview-panel .video-wrap video");
  const before = (await video.boundingBox())!;
  expect(before.height).toBeGreaterThan(250);
  const track = (await page.locator(".clip-range-track").boundingBox())!;
  expect(track.y).toBeGreaterThan(before.y + before.height);
  // The viewing shortcuts and zoom/pan now occupy two distinct navigation rows.
  expect(track.y - (before.y + before.height)).toBeLessThan(200);
  const segments = Array.from({ length: 12 }, (_, i) => ({ id: `large:c${i}`, start: 10 + i, end: 100 + i,
    victory: null, kind: "fight", confidence: "low", boss: `Boss ${i}`, summary: "需要查看", warnings: [], evidence: [] }));
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), {
    projects: [project], jobs: [{ id: "large", project_id: "demo", kind: "analyze", status: "succeeded", candidates: segments }],
  });
  await page.getByLabel("剪輯與候選檢查區").evaluate(el => { el.scrollTop = el.scrollHeight; });
  expect((await video.boundingBox())!.y).toBeCloseTo(before.y);
  expect((await video.boundingBox())!.height).toBeCloseTo(before.height);
  expect(await page.getByLabel("剪輯與候選檢查區").evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await expect(video).toBeInViewport();
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
  await page.screenshot({ path: "../runs/large-preview-review.png", fullPage: true });
});

test("theater mode enlarges the same video, keeps trimming available and restores the workspace", async ({ page }) => {
  await page.addInitScript(() => window.addEventListener("error", event => {
    if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
  }, true));
  await setup(page, [project], { settings: false });
  const video = page.locator(".preview-panel .video-wrap video");
  const before = (await video.boundingBox())!;
  await video.evaluate((v: HTMLVideoElement) => {
    v.dataset.instance = "same-player"; v.currentTime = 42; v.playbackRate = 1.5; v.volume = .3;
  });
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  await expect(page.locator(".app")).toHaveClass(/preview-is-large/);
  await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
  await expect(page.locator(".sidebar")).not.toBeVisible();
  await expect(video).toHaveAttribute("data-instance", "same-player");
  expect(await video.evaluate((v: HTMLVideoElement) => [v.currentTime, v.playbackRate, v.volume])).toEqual([42, 1.5, .3]);
  const expanded = (await video.boundingBox())!;
  expect(Math.min(expanded.width, expanded.height * 16 / 9)).toBeGreaterThan(Math.min(before.width, before.height * 16 / 9) * 1.2);
  const edge = page.getByRole("slider", { name: "片段開始邊界", exact: true });
  await expect(edge).toBeInViewport();
  await edge.press("Shift+ArrowRight");
  await expect(edge).toHaveAttribute("aria-valuenow", "11");
  await expect(video).toBeInViewport();
  await page.screenshot({ path: "../runs/large-preview-theater.png", fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.locator(".app")).not.toHaveClass(/preview-is-large/);
  await expect(page.getByLabel("輸入訊息")).toBeVisible();
  await expect(page.locator(".sidebar")).toBeVisible();
  await expect(video).toHaveAttribute("data-instance", "same-player");
  await expect(edge).toHaveAttribute("aria-valuenow", "11");
  expect(await video.evaluate((v: HTMLVideoElement) => [v.currentTime, v.playbackRate, v.volume])).toEqual([11, 1.5, .3]);
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  await page.getByRole("button", { name: "返回工作區", exact: true }).click();
  await expect(page.getByLabel("輸入訊息")).toBeVisible();
  await page.getByLabel("關閉 AI 對話").click();
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = (await video.boundingBox())!;
  expect(mobile.height).toBeGreaterThan(190);
  expect(mobile.width / mobile.height).toBeCloseTo(16 / 9, 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/large-preview-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 844, height: 390 });
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  const landscape = (await video.boundingBox())!;
  expect(landscape.height).toBeGreaterThan(160);
  const editing = (await page.getByLabel("剪輯與候選檢查區").boundingBox())!;
  expect(editing.y).toBeGreaterThanOrEqual(landscape.y + landscape.height);
  await expect(page.getByLabel("剪輯與候選檢查區")).toHaveCSS("overflow-y", "visible");
  await page.getByRole("button", { name: "匯出 MP4", exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/large-preview-landscape.png", fullPage: true });
});
