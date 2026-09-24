import { expect, test } from "@playwright/test";
import path from "node:path";
import { execFileSync } from "node:child_process";

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
  await expect(page.getByRole("region", { name: "剪輯設定", exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("button", { name: "匯出 MP4" })).toBeEnabled();
  await expect(page.locator(".clip-inspector input[type=checkbox]")).toHaveCount(0);
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.readyState),
    )
    .toBeGreaterThanOrEqual(1);
  await page.getByLabel("開始時間").fill("1.25");
  await page.getByLabel("片段名稱").fill("測試 Boss・完整勝利");
  await page.getByLabel("勝利時間").fill("8");
  await page.getByLabel("勝利後收尾").fill("5");
  await page.getByRole("button", { name: /預覽這段/ }).click();
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.currentTime),
    )
    .toBeGreaterThan(1.25);
  const player = page.locator(".preview-panel .video-wrap video");
  await expect(player).not.toHaveAttribute("controls");
  await page.getByRole("button", { name: "暫停原片", exact: true }).click();
  expect(await player.evaluate((v: HTMLVideoElement) => v.paused)).toBe(true);
  await page.getByRole("button", { name: "將原片靜音", exact: true }).click();
  expect(await player.evaluate((v: HTMLVideoElement) => v.muted)).toBe(true);
  await page.getByRole("button", { name: "開啟原片聲音", exact: true }).click();
  expect(await player.evaluate((v: HTMLVideoElement) => v.muted)).toBe(false);
  await page.getByRole("button", { name: "播放原片", exact: true }).click();
  const playingAt = await player.evaluate((v: HTMLVideoElement) => {
    v.dataset.instance = "original-playing-video";
    return v.currentTime;
  });
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  await expect(player).toHaveAttribute("data-instance", "original-playing-video");
  expect(await player.evaluate((v: HTMLVideoElement) => v.paused)).toBe(false);
  expect(await player.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThanOrEqual(playingAt);
  await page.screenshot({ path: "../runs/large-preview-real-theater.png" });
  await page.getByRole("button", { name: "返回工作區", exact: true }).click();
  await expect(player).toHaveAttribute("data-instance", "original-playing-video");
  expect(await player.evaluate((v: HTMLVideoElement) => v.paused)).toBe(false);
  await page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.pause());
  // Timing edits can be exported directly without an extra confirmation step.
  await page.getByLabel("開始時間").fill("1.5");
  await page.getByRole("button", { name: "匯出 MP4" }).click();
  await expect(page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true })).toBeAttached({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "專案工具", exact: true }).click();
  await page.locator(".jobs-details > summary").click();
  await expect(page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.locator(".jobs-panel").getByRole("link", { name: "下載 MP4", includeHidden: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("測試 Boss・完整勝利.mp4");
  await download.saveAs(path.resolve("../runs/web-poc-browser-export.mp4"));
  expect(await download.failure()).toBeNull();
  const metadata = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_format", "-of", "json", path.resolve("../runs/web-poc-browser-export.mp4")], { encoding: "utf8" }));
  expect(Number(metadata.format.duration)).toBeCloseTo(11.5, 0);
  await page.getByRole("button", { name: "關閉專案工具", exact: true }).click();
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("1.5");
  await expect(player).toHaveAttribute("data-instance", "original-playing-video");
  await expect(page.getByLabel("片段名稱")).toHaveValue("測試 Boss・完整勝利");
  await page.getByLabel("開始時間").fill("1.75");
  await page.getByRole("button", { name: "回到原片", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("1.5");
  await page.reload();
  await expect(page.getByLabel("開始時間")).toHaveValue("1.5");
  await page.getByRole("button", { name: "專案工具", exact: true }).click();
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
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "儲存草稿" }).click();
  await expect(
    page.getByRole("dialog", { name: "專案工具", exact: true }).getByText("草稿已儲存", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "關閉專案工具", exact: true }).click();
  await page.getByRole("button", { name: "跳到開始", exact: true }).click();
  await expect
    .poll(() =>
      page.locator(".preview-panel .video-wrap video").evaluate((v: HTMLVideoElement) => v.readyState),
    )
    .toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: "../runs/web-poc-editor.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  // Sidebar visibility persists from desktop; close the mobile drawer to edit.
  await page.getByLabel("關閉 AI 對話").click();
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
  await expect(page.getByLabel("開始時間")).toHaveValue("2");
  await page.getByRole("button", { name: "AI 對話", exact: true }).click();
  await page.getByRole("button", { name: /套用候選/ }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("3");
  await page.getByRole("tab", { name: "成品 1" }).click();
  const exportedJob = analysisState.jobs.find((job: { kind: string }) => job.kind === "export");
  await page.getByRole("button", { name: "刪除成品 #1", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "刪除成品？" })).toContainText("測試 Boss・完整勝利");
  await page.getByRole("button", { name: "刪除成品", exact: true }).click();
  await expect(page.getByText("這個專案還沒有成品")).toBeVisible();
  expect((await page.request.get(`/api/jobs/${exportedJob.id}/download`)).status()).toBe(404);
  const remaining = await (await page.request.get("/api/state")).json();
  expect(remaining.jobs.some((job: { id: string }) => job.id === exportedJob.id)).toBe(false);
  expect(remaining.projects[0].id).toBe(projectId);
  expect(consoleErrors).toEqual([]);
});
