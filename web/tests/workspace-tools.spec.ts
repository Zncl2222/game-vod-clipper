import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { NumberedCandidate, Project, State, VideoStorage } from "../src/api";

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
  const controls = { failStorage: false, malformedStorage: false, failSave: false, gate: null as Promise<void> | null, saves: 0, exports: 0, tags: 0 };
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
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify(state)}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", detail: "已連接" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "test-model", name: "Test model", is_default: true }] } });
    if (path === "/api/storage") return controls.failStorage ? route.fulfill({ status: 503 })
      : route.fulfill({ json: controls.malformedStorage ? { available: true } : storage });
    if (path.endsWith("/candidate-review")) { controls.tags++; return route.fulfill({ json: {} }); }
    if (path.endsWith("/draft") && route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      project.draft = { ...body, revision: body.revision + 1 };
      return route.fulfill({ json: project.draft });
    }
    if (path.endsWith("/exports")) {
      controls.exports++;
      const job = { id: `export-${controls.exports}`, project_id: project.id, kind: "export" as const, status: "queued", stage: "等待匯出", progress: 0,
        error: null, draft: structuredClone(project.draft!), created: controls.exports };
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

test("export needs no keep tag or checkbox and only successful exports leave a persistent mark", async ({ page }) => {
  const { controls, state, publish } = await workspace(page);
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await page.getByRole("button", { name: "編輯片段 #1 區間" }).click();
  await page.getByLabel("開始時間").fill("22");
  await page.getByLabel("勝利時間").fill("65");
  await expect(page.locator(".compact-export input[type=checkbox]")).toHaveCount(0);
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
  await expect(page.getByLabel("開始時間")).toHaveValue("10");
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
