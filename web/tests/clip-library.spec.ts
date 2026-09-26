import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { Draft, Job, Project } from "../src/api";
import { edgeHandle, expectEdge, setEdge } from "./timing";

const source: Project = { id: "clips-project", title: "艾爾登法環 · 成品與原片", ready: true, duration: 7200,
  width: 1920, height: 1080, thumbnails: [], draft: { start: 120, victory: 320, postroll: 8, reviewed: false, revision: 0, origin: "manual" } };
const exports: Job[] = [500, 900].map((start, i) => ({ id: `clip-${i + 1}`, project_id: source.id, kind: "export", status: "succeeded",
  progress: 100, stage: "已完成", error: null, created: i + 1, draft: { ...source.draft!, start, victory: start + 120, reviewed: true, revision: i + 3 } }));

async function workspace(page: Page) {
  const state = structuredClone({ projects: [source, { ...source, id: "another", title: "另一支原片" }], jobs: exports });
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        window.addEventListener("fixture:state", event => this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify((event as CustomEvent).detail) })));
      }
      set onerror(_handler: unknown) {}
    };
    window.addEventListener("error", event => { if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation(); }, true);
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(state)}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", detail: "已連接" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "test-model", name: "Test model", is_default: true }] } });
    if (path.endsWith("/draft") && route.request().method() === "PUT") {
      const submitted = route.request().postDataJSON() as Draft;
      const draft = { ...submitted, revision: submitted.revision + 1 };
      const job = state.jobs.find(job => path.includes(`/clips/${job.id}/`));
      if (job) job.edit_draft = draft;else state.projects[0].draft = draft;
      return route.fulfill({ json: draft });
    }
    if (path.endsWith("/exports")) return route.fulfill({ status: 202, json: { id: "new-export" } });
    if (route.request().method() === "DELETE" && path.includes("/clips/")) {
      const id = path.split("/").at(-1)!;
      state.jobs = state.jobs.filter(job => job.id !== id);
      return route.fulfill({ json: { deleted: true, id } });
    }
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await expect(page.getByText("工作區已連線")).toBeVisible();
  return state;
}

test("clicking a clip directly opens the same editor and preserves source and clip workspaces", async ({ page }) => {
  await workspace(page);
  const video = page.locator(".video-wrap video");
  await setEdge(page, "start", 125);
  // Trim handles seek to the edge they move; place the playhead afterwards.
  await video.evaluate((element: HTMLVideoElement) => { element.dataset.identity = "retained"; element.currentTime = 150; element.dispatchEvent(new Event("timeupdate")); });
  await page.getByLabel("輸入訊息").fill("保留這則尚未送出的訊息");
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 500);
  await expectEdge(page, "victory", 620);
  await expect(page.getByRole("button", { name: "回到原片", exact: true })).toBeInViewport();
  await expect(video).toHaveAttribute("data-identity", "retained");
  await expect(page.locator("video")).toHaveCount(1);
  await setEdge(page, "start", 490);
  await page.getByRole("button", { name: "編輯成品 #2", exact: true }).click();
  await expectEdge(page, "start", 900);
  await setEdge(page, "start", 890);
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 490);
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await expectEdge(page, "start", 125);
  expect(await video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBe(150);
  await setEdge(page, "start", 126);
  await page.getByRole("tab", { name: "AI 助理", exact: true }).click();
  await expect(page.getByLabel("輸入訊息")).toHaveValue("保留這則尚未送出的訊息");
  await page.reload();
  await expectEdge(page, "start", 126);
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 490);
});

test("saving and exporting clip drafts never change the original project or MP4", async ({ page }) => {
  const state = await workspace(page);
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await setEdge(page, "start", 495);
  await expect(page.getByRole("button", { name: "另存新成品", exact: true })).toBeEnabled();
  const request = page.waitForRequest(request => request.url().endsWith("/exports"));
  await page.getByRole("button", { name: "另存新成品", exact: true }).click();
  expect((await request).postDataJSON()).toEqual({ revision: 1, source_job_id: "clip-1", quality: "high" });
  expect(state.projects[0].draft).toEqual(source.draft);
  expect(state.jobs[0].draft).toEqual(exports[0].draft);
  expect(state.jobs[0].edit_draft?.start).toBe(495);
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await expectEdge(page, "start", 120);
});

test("selecting a candidate from a finished clip edits the source and preserves the clip draft", async ({ page }) => {
  const state = await workspace(page);
  state.projects[0].review_candidates = [{ id: "scan:one", number: 1, start: 30, end: 70, victory: 62, postroll: 8,
    kind: "possible_win", confidence: "medium", boss: "第一場", summary: "候選", evidence: [], warnings: [], review: "pending" }];
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state);
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await setEdge(page, "start", 495);
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expectEdge(page, "start", 30);
  await expect(page.getByRole("button", { name: "原片編輯台", exact: true })).toHaveAttribute("aria-pressed", "true");
  await setEdge(page, "start", 31);
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 495);
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await expectEdge(page, "start", 31);
  expect(state.jobs[0].draft).toEqual(exports[0].draft);
});

test("a save response updates its own draft even after switching away and back", async ({ page }) => {
  await workspace(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => release = resolve);
  await page.route("**/clips/clip-1/draft", async route => {
    const body = route.request().postDataJSON();await gate;
    await route.fulfill({ json: { ...body, revision: body.revision + 1 } });
  });
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await setEdge(page, "start", 495);
  await page.getByRole("button", { name: "專案工具", exact: true }).click();
  const requested = page.waitForRequest(request => request.url().includes("/clips/clip-1/draft"));
  await page.getByRole("button", { name: "儲存草稿", exact: true }).click();await requested;
  await page.getByRole("button", { name: "關閉專案工具", exact: true }).click();
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await setEdge(page, "start", 125);
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await setEdge(page, "start", 494);
  release();
  await expect(page.getByRole("button", { name: "儲存草稿", exact: true, includeHidden: true })).toBeEnabled();
  await expectEdge(page, "start", 494);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("bosscut:clip-draft:clips-project:clip-1")!).revision)).toBe(1);
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await expectEdge(page, "start", 125);
});

test("late AI actions cannot modify another editor target, including a round trip", async ({ page }) => {
  await workspace(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => release = resolve);
  await page.route("**/api/codex/chat", async route => {
    await gate;await route.fulfill({ contentType: "application/x-ndjson", body: JSON.stringify({ type: "reply", project_id: source.id, reply: "調整開始", action: { kind: "set_draft", start: 100, victory: 320, postroll: 8, seconds: null } }) + "\n" });
  });
  await page.getByLabel("輸入訊息").fill("開始提前 20 秒");
  const request = page.waitForRequest(request => request.url().endsWith("/codex/chat"));
  await page.getByRole("button", { name: "送出訊息" }).click();await request;
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  release();
  await page.getByRole("tab", { name: "AI 助理", exact: true }).click();
  await expect(page.locator(".chat-operation")).toContainText("編輯對象已切換");
  await expectEdge(page, "start", 120);
});

test("SSE preceding a save response does not discard more recent clip edits", async ({ page }) => {
  const state = await workspace(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => release = resolve);
  await page.route("**/clips/clip-1/draft", async route => {
    const submitted = route.request().postDataJSON();
    state.jobs[0].edit_draft = { ...submitted, revision: submitted.revision + 1 };
    await gate;await route.fulfill({ json: state.jobs[0].edit_draft });
  });
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await setEdge(page, "start", 495);
  await page.getByRole("button", { name: "專案工具", exact: true }).click();
  const request = page.waitForRequest(request => request.url().includes("/clips/clip-1/draft"));
  await page.getByRole("button", { name: "儲存草稿", exact: true }).click();await request;
  await page.getByRole("button", { name: "關閉專案工具", exact: true }).click();
  await setEdge(page, "start", 494);
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state);
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 494);
  release();
  await expect(page.getByRole("button", { name: "儲存草稿", exact: true, includeHidden: true })).toBeEnabled();
  await expectEdge(page, "start", 494);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("bosscut:clip-draft:clips-project:clip-1")!).revision)).toBe(1);
  await page.reload();
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 494);
});

test("an Agent JSON read cannot modify a workspace selected after import started", async ({ page }) => {
  await workspace(page);
  await page.evaluate(() => {
    const read = File.prototype.text;
    File.prototype.text = async function () {
      const result = await read.call(this);
      await new Promise<void>(resolve => window.addEventListener("fixture:release-file", () => resolve(), { once: true }));
      return result;
    };
  });
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByLabel("匯入 Agent JSON").setInputFiles({ name: "clip-result.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ project_id: source.id, start: 490, victory: 620, postroll: 8 })) });
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await page.evaluate(() => window.dispatchEvent(new Event("fixture:release-file")));
  await expect(page.getByRole("alert")).toContainText("編輯對象或草稿已變更");
  await expectEdge(page, "start", 120);
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expectEdge(page, "start", 500);
});

test("drawer keyboard navigation, accessibility, counts and narrow editing", async ({ page }) => {
  await workspace(page);
  const ai = page.getByRole("tab", { name: "AI 助理", exact: true });
  await ai.focus();await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "成品 2" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "成品 2" })).toHaveAttribute("aria-selected", "true");
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
    await expect(page.getByRole("button", { name: "回到原片", exact: true })).toBeInViewport();
    expect(await page.getByRole("button", { name: "回到原片", exact: true }).evaluate(button => {
      const rect = button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    })).toBe(true);
    await expect(page.getByRole("button", { name: "另存新成品", exact: true })).toBeInViewport();
    await expect(page.getByLabel("片段名稱")).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.screenshot({ path: "../runs/clip-library-desktop.png" });
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "編輯成品 #2", exact: true }).click();
  await expectEdge(page, "start", 900);
  await expect(page.getByRole("button", { name: "回到原片", exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await setEdge(page, "start", 130);
  await expectEdge(page, "start", 130);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/clip-library-mobile.png" });
});

test("source return remains clickable when the editor header wraps on small phones", async ({ page }) => {
  await workspace(page);
  await page.getByRole("tab", { name: "成品 2" }).click();
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 844 });
    if (!await page.getByRole("button", { name: "編輯成品 #1", exact: true }).isVisible())
      await page.getByRole("button", { name: "AI 對話", exact: true }).click();
    await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
    const back = page.getByRole("button", { name: "回到原片", exact: true });
    expect(await back.evaluate(button => {
      const rect = button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    })).toBe(true);
    await back.click();
    await expectEdge(page, "start", 120);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});

test("the pencil button edits and refocuses the selected clip", async ({ page }) => {
  await workspace(page);
  await page.getByRole("tab", { name: "成品 2" }).click();
  const edit = page.getByRole("button", { name: "編輯成品 #1", exact: true });
  await edit.locator("svg").click();
  await expect(edgeHandle(page, "start")).toBeFocused();
  await expectEdge(page, "start", 500);
  await setEdge(page, "start", 495);
  await edit.focus();
  await page.keyboard.press("Enter");
  await expect(edgeHandle(page, "start")).toBeFocused();
  await expectEdge(page, "start", 495);
});

test("delete confirms, restores the source draft and ignores stale events", async ({ page }) => {
  const state = await workspace(page), stale = structuredClone(state);
  await page.getByLabel("片段名稱").fill("原片草稿名稱");
  await setEdge(page, "start", 125);
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByLabel("片段名稱").fill("選錯的成品");
  const remove = page.getByRole("button", { name: "刪除成品 #1", exact: true });
  await remove.click();
  const dialog = page.getByRole("dialog", { name: "刪除成品？" });
  await expect(dialog.getByRole("button", { name: "取消" })).toBeFocused();
  await expect(dialog).toContainText("本機 MP4");
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(remove).toBeFocused();
  expect(state.jobs).toHaveLength(2);
  await remove.click();
  await dialog.getByRole("button", { name: "刪除成品", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("tab", { name: "成品 1" })).toBeVisible();
  await expect(page.getByLabel("片段名稱")).toHaveValue("原片草稿名稱");
  await expectEdge(page, "start", 125);
  await expect(page.getByRole("button", { name: "原片編輯台", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => localStorage.getItem("bosscut:clip-draft:clips-project:clip-1"))).toBeNull();
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), stale);
  await expect(page.getByRole("tab", { name: "成品 1" })).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "成品 1" }).click();
  await expect(page.locator(".finished-clip-card")).toHaveCount(1);
  await page.getByRole("button", { name: "刪除成品 #1", exact: true }).click();
  await page.getByRole("button", { name: "刪除成品", exact: true }).click();
  await expect(page.getByText("這個專案還沒有成品")).toBeVisible();
  await expect(page.getByRole("tab", { name: "成品 0" })).toBeFocused();
});

test("failed deletion keeps the clip and supports retry without changing another draft", async ({ page }) => {
  await workspace(page);
  let attempts = 0;
  await page.route("**/api/projects/clips-project/clips/clip-2", async route => {
    attempts++;
    return attempts === 1 ? route.fulfill({ status: 409, json: { detail: "這個成品正在上傳 YouTube，請先暫停上傳再刪除。" } })
      : route.fulfill({ json: { deleted: true, id: "clip-2" } });
  });
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByLabel("片段名稱").fill("保留這份編輯");
  await page.getByRole("button", { name: "刪除成品 #2", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "刪除成品？" });
  await dialog.getByRole("button", { name: "刪除成品", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("請先暫停上傳");
  await expect(page.locator(".finished-clip-card")).toHaveCount(2);
  await dialog.getByRole("button", { name: "刪除成品", exact: true }).click();
  await expect(page.locator(".finished-clip-card")).toHaveCount(1);
  await expect(page.getByLabel("片段名稱")).toHaveValue("保留這份編輯");
  await expectEdge(page, "start", 500);
});

test("external deletion and a late save cannot restore a deleted clip draft", async ({ page }) => {
  const state = await workspace(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => release = resolve);
  await page.route("**/clips/clip-1/draft", async route => {
    const body = route.request().postDataJSON(); await gate;
    await route.fulfill({ json: { ...body, revision: body.revision + 1 } });
  });
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByLabel("片段名稱").fill("即將刪除");
  const request = page.waitForRequest(request => request.url().endsWith("/clip-1/draft"));
  await page.getByRole("button", { name: "另存新成品", exact: true }).click();
  await request;
  state.jobs = state.jobs.filter(job => job.id !== "clip-1");
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state);
  await expectEdge(page, "start", 120);
  release();
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeEnabled();
  expect(await page.evaluate(() => localStorage.getItem("bosscut:clip-draft:clips-project:clip-1"))).toBeNull();
  await expect(page.getByLabel("片段名稱")).toHaveValue("");
});

test("clip names survive switching, saving, reload and export and can be searched", async ({ page }) => {
  const state = await workspace(page);
  const name = "瑪蓮妮亞・無傷通關";
  await page.getByLabel("片段名稱").fill("原片自己的名稱");
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await page.getByLabel("片段名稱").fill(name);
  await page.getByRole("button", { name: "編輯成品 #2", exact: true }).click();
  await expect(page.getByLabel("片段名稱")).toHaveValue("");
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expect(page.getByLabel("片段名稱")).toHaveValue(name);
  await page.getByRole("button", { name: "專案工具", exact: true }).click();
  await page.getByRole("button", { name: "儲存草稿", exact: true }).click();
  await expect.poll(() => state.jobs[0].edit_draft?.title).toBe(name);
  await page.reload();
  await expect(page.getByLabel("片段名稱")).toHaveValue("原片自己的名稱");
  await page.getByRole("tab", { name: "成品 2" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expect(page.getByLabel("片段名稱")).toHaveValue(name);
  await page.route("**/api/projects/clips-project/exports", async route => {
    const job = { ...exports[0], id: "named-export", created: 3, draft: structuredClone(state.jobs[0].edit_draft!) };
    state.jobs.push(job);
    await route.fulfill({ status: 202, json: job });
  });
  await page.getByRole("button", { name: "另存新成品", exact: true }).click();
  await expect.poll(() => state.jobs.length).toBe(3);
  await page.evaluate(state => window.dispatchEvent(new CustomEvent("fixture:state", { detail: state })), state);
  await expect(page.locator(".finished-clip-title").getByText(name, { exact: true })).toBeVisible();
  await page.getByLabel("搜尋成品片段").fill("瑪蓮");
  await expect(page.locator(".finished-clip-card")).toHaveCount(1);
  await page.screenshot({ path: "../runs/clip-library-named.png" });
});
