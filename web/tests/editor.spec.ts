import { expect, test } from "@playwright/test";
import path from "node:path";

test("import, preview, trim, review, export, restore and mobile layout", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("工作區已連線")).toBeVisible();
  await page.screenshot({ path: "../runs/web-poc-empty.png", fullPage: true });
  await page.getByRole("button", { name: "建立第一個剪輯" }).click();
  await page.getByLabel("選擇影片").selectOption("downloads/synthetic.mp4");
  await page.getByRole("button", { name: "建立剪輯專案" }).click();
  await page.locator(".editor-settings > summary").click();
  await expect(page.getByRole("heading", { name: "剪輯設定" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("button", { name: "匯出 MP4" })).toBeDisabled();
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.readyState),
    )
    .toBeGreaterThanOrEqual(1);
  await page.getByLabel("開始時間").fill("1.25");
  await page.getByLabel("勝利時間").fill("8");
  await page.getByLabel("勝利後收尾").fill("5");
  await page.getByRole("button", { name: "播放開頭" }).click();
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.currentTime),
    )
    .toBeGreaterThan(1.25);
  await page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.pause());
  await page.getByRole("checkbox").check();
  // Any edit must invalidate the prior review.
  await page.getByLabel("開始時間").fill("1.5");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "匯出 MP4" }).click();
  await expect(page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true })).toBeAttached({
    timeout: 30_000,
  });
  await page.locator(".jobs-details > summary").click();
  await expect(page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true }).click();
  const download = await downloadPromise;
  await download.saveAs(path.resolve("../runs/web-poc-browser-export.mp4"));
  expect(await download.failure()).toBeNull();
  await page.reload();
  await page.locator(".editor-settings > summary").click();
  await expect(page.getByLabel("開始時間")).toHaveValue("1.5");
  await page.locator(".jobs-details > summary").click();
  await expect(page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true })).toBeVisible();
  const projectId = await page.evaluate(async () => {
    const state = await (await fetch("/api/state")).json();
    return state.projects[0].id as string;
  });
  await page.getByLabel("匯入 Agent JSON").setInputFiles({
    name: "wrong-source.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        project_id: "another-source",
        start: 2,
        victory: 8,
        postroll: 5,
      }),
    ),
  });
  await expect(page.getByRole("alert")).toContainText("project_id");
  await page.getByRole("button", { name: "關閉錯誤" }).click();
  await page.getByLabel("匯入 Agent JSON").setInputFiles({
    name: "agent-result.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        project_id: projectId,
        start: 2,
        victory: 8,
        postroll: 5,
      }),
    ),
  });
  await expect(page.getByLabel("開始時間")).toHaveValue("2");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("button", { name: "儲存草稿" }).click();
  await expect(
    page.getByText("草稿已儲存", { exact: false }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "跳到開始", exact: true }).click();
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.readyState),
    )
    .toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: "../runs/web-poc-editor.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../runs/web-poc-mobile.png", fullPage: true });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  // Deterministic UI coverage: applying a model result is explicit and clears review.
  // This mocks only the displayed observation; real-model tests are separately opt-in.
  const analysisState = await (await page.request.get("/api/state")).json();
  analysisState.jobs.unshift({
    id: "codex-ui-fixture",
    project_id: projectId,
    kind: "analyze",
    status: "succeeded",
    stage: "完成",
    progress: 100,
    error: null,
    draft: null,
    result: {
      status: "candidate",
      start: 3,
      victory: 8,
      postroll: 5,
      boss: "UI test only",
      summary: "介面測試用候選，非真實模型分析。",
      warnings: ["需要人工檢查。"],
      evidence: [{ time: 8, event: "介面測試標記" }],
      model: "gpt-5.6-luna",
      frames: 16,
      rounds: 1,
    },
  });
  await page.route("**/api/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `data: ${JSON.stringify(analysisState)}\n\n`,
    }),
  );
  await page.reload();
  await page.locator(".editor-settings > summary").click();
  await expect(page.getByLabel("開始時間")).toHaveValue("2");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await page.getByRole("button", { name: /套用候選/ }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("3");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  expect(consoleErrors).toEqual([]);
});
