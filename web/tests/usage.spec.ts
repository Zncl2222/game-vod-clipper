import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const project = { id: "usage-demo", title: "用量測試影片", ready: true, duration: 180, thumbnails: [],
  draft: { start: 10, victory: 100, postroll: 8, reviewed: false, revision: 0, origin: "manual" } };
const counts = { input_tokens: 274254, output_tokens: 15168, total_tokens: 289422,
  cached_input_tokens: 14592, reasoning_output_tokens: 9599, records: 11 };
const usage = { total: { ...counts, input_tokens: 300000, total_tokens: 315168 }, project: counts,
  latest_analysis: { id: "analysis", status: "succeeded", tokens: counts,
    quota_change: { status: "estimated", windows: [
      { bucket_id: "codex", bucket_name: "codex", window_minutes: 10080, status: "estimated", percentage_points: 3 },
    ] } } };
const quota = { available: true, plan: "plus", fetched_at: 1790000000, detail: "", buckets: [
  { id: "codex", name: "codex", windows: [
    { id: "primary", window_minutes: 10080, used_percent: 23, resets_at: 1790600000 },
    { id: "secondary", window_minutes: 300, used_percent: 60, resets_at: 1790010000 },
  ] },
] };

async function setup(page: Page, quotaResult: unknown = quota, usageResult: unknown = usage) {
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      set onerror(_handler: ((this: EventSource, event: Event) => unknown) | null) {}
    };
    window.addEventListener("error", event => {
      if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
    }, true);
  });
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/events") return route.fulfill({ contentType: "text/event-stream",
      body: `data: ${JSON.stringify({ projects: [project, { ...project, id: "second", title: "另一支影片" }], jobs: [] })}\n\n` });
    if (url.pathname === "/api/codex") return route.fulfill({ json: {
      available: true, auth_mode: "chatgpt", email: "fixture@example.test", plan: "plus", detail: "已連接",
    } });
    if (url.pathname === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "fixture", name: "Fixture", is_default: true }] } });
    if (url.pathname === "/api/codex/usage") return route.fulfill({ json: usageResult });
    if (url.pathname === "/api/codex/rate-limits") return route.fulfill({ json: quotaResult });
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  if (!await page.getByLabel("輸入訊息").isVisible()) await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  const summary = page.locator(".usage-panel > summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("本機累積", { exact: true })).toContainText("315,168");
  await expect(page.getByRole("button", { name: "更新用量", exact: true })).toBeEnabled();
}

test("usage shows local/project tokens, real window lengths, reset times and estimated deltas", async ({ page }) => {
  await setup(page);
  const panel = page.locator(".usage-panel");
  await expect(page.getByLabel("目前影片累積", { exact: true })).toContainText("289,422");
  await expect(panel).toContainText("含快取輸入 14,592 · 推理輸出 9,599");
  await expect(panel.getByRole("progressbar", { name: "codex 週額度已用", exact: true })).toHaveAttribute("value", "23");
  await expect(panel.getByRole("progressbar", { name: "codex 5 小時額度已用", exact: true })).toHaveAttribute("value", "60");
  await expect(panel).toContainText("剩餘 77%");
  await expect(panel).toContainText("重置");
  await expect(panel).toContainText("約 +3 個百分點");
  expect((await new AxeBuilder({ page }).include(".usage-panel").analyze()).violations).toEqual([]);
  await page.screenshot({ path: "../runs/usage-desktop.png" });
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(panel.locator(":scope > summary")).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/usage-mobile.png" });
});

test("unavailable subscription keeps token totals and never fabricates zero usage", async ({ page }) => {
  await setup(page, { available: false, fetched_at: 1790000000, plan: null, buckets: [], detail: "API Key 依 API 用量計費，沒有 ChatGPT 訂閱額度。" },
    { ...usage, latest_analysis: { ...usage.latest_analysis, quota_change: null } });
  await expect(page.getByLabel("Codex 訂閱額度", { exact: true })).toContainText("沒有 ChatGPT 訂閱額度");
  await expect(page.locator(".usage-panel").getByRole("progressbar")).toHaveCount(0);
  await expect(page.locator(".usage-panel")).toContainText("舊任務未記錄額度快照，無法回推");
  await page.route("**/api/codex/rate-limits", route => route.fulfill({ status: 503, json: { detail: "額度查詢暫時中斷" } }));
  await page.getByRole("button", { name: "更新用量", exact: true }).click();
  await expect(page.getByLabel("Codex 訂閱額度", { exact: true })).toContainText("額度查詢暫時中斷");
  await expect(page.getByLabel("本機累積", { exact: true })).toContainText("315,168");
  await page.route("**/api/codex/rate-limits", route => route.fulfill({ json: quota }));
  await page.getByRole("button", { name: "更新用量", exact: true }).click();
  await expect(page.getByRole("progressbar", { name: "codex 週額度已用", exact: true })).toBeVisible();
});

test("reset estimates and project changes never display stale attribution", async ({ page }) => {
  await setup(page, quota, { ...usage, latest_analysis: { ...usage.latest_analysis,
    quota_change: { status: "unavailable", windows: [{ ...usage.latest_analysis.quota_change.windows[0], status: "reset", percentage_points: null }] } } });
  await expect(page.getByLabel("最近一次分析用量", { exact: true })).toContainText("期間額度已重置或調整，無法估算");
  let release: () => void = () => {};
  const waiting = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/codex/usage?project_id=usage-demo", async route => {
    await waiting;
    await route.fulfill({ json: usage });
  });
  const requested = page.waitForRequest("**/api/codex/usage?project_id=usage-demo");
  await page.getByRole("button", { name: "更新用量", exact: true }).click();
  await requested;
  await page.route("**/api/codex/usage?project_id=second", route => route.fulfill({ json: {
    ...usage, project: { ...counts, input_tokens: 400, output_tokens: 100, total_tokens: 500 }, latest_analysis: null,
  } }));
  await page.locator(".project-card").nth(1).click();
  await expect(page.getByLabel("目前影片累積", { exact: true }).locator("strong")).toHaveText("500 tokens");
  release();
  await expect(page.getByLabel("目前影片累積", { exact: true }).locator("strong")).toHaveText("500 tokens");
  await expect(page.getByLabel("最近一次分析用量", { exact: true })).toHaveCount(0);
});
