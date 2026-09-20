import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const project = { id: "studio-demo", title: "艾爾登法環 · 女武神挑戰", ready: true, duration: 7200, width: 1920, height: 1080, thumbnails: [],
  draft: { start: 120, victory: 320, postroll: 8, reviewed: false, revision: 0, origin: "manual" } };

async function workspace(page: Page, projects: unknown[] = [], jobs: unknown[] = []) {
  await page.addInitScript(() => {
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      set onerror(_handler: ((this: EventSource, event: Event) => unknown) | null) {}
    };
    window.addEventListener("error", event => {
      if (event.target instanceof HTMLMediaElement) event.stopImmediatePropagation();
    }, true);
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ projects, jobs })}\n\n` });
    if (path === "/api/codex") return route.fulfill({ json: { available: true, auth_mode: "chatgpt", email: "creator@example.test", detail: "已連接" } });
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "demo-model", name: "Studio model", is_default: true }] } });
    if (path === "/api/sources") return route.fulfill({ json: [] });
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await expect(page.getByText("工作區已連線")).toBeVisible();
}

test("candidate verification remains visible and rejected ranges load only for manual correction", async ({ page }) => {
  const base = { kind: "possible_win", confidence: "high", summary: "完整成功嘗試", warnings: [], evidence: [], review: "pending" };
  const candidates = [
    { ...base, id: "review:one", number: 1, start: 20, end: 60, victory: 52, boss: "粗查片段", verification: "unverified" },
    { ...base, id: "review:two", number: 2, start: 80, end: 130, victory: 122, boss: "含失敗畫面", verification: "blocked",
      warnings: ["仍與死亡／重試片段重疊"] },
    { ...base, id: "review:three", number: 3, start: 150, end: 196, victory: 190, boss: "通過檢查", verification: "verified", postroll: 6 },
  ];
  await workspace(page, [{ ...project, duration: 400, draft: { ...project.draft, reviewed: true }, review_candidates: candidates }]);
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await page.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.getByLabel("片段 #1 詳情")).toContainText("尚未驗證");
  await expect(page.getByLabel("片段 #1 詳情").getByRole("status")).toContainText("可能包含失敗／重試");
  await expect(page.getByRole("button", { name: "將 #1 放入剪輯草稿" })).toHaveCount(0);
  await page.getByRole("button", { name: "下一段", exact: true }).click();
  const blocked = page.getByLabel("片段 #2 詳情");
  await expect(blocked).toContainText("未通過驗證");
  await expect(blocked).toContainText("仍與死亡／重試片段重疊");
  await expect(blocked.getByRole("button", { name: "預覽 #2", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "將 #2 放入剪輯草稿" })).toHaveCount(0);
  await blocked.getByRole("button", { name: "載入 #2 手動修正" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("80");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeDisabled();
  await blocked.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../runs/candidate-verification-desktop.png" });
  await page.getByLabel("關閉 AI 對話").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await blocked.scrollIntoViewIfNeeded();
  await expect(blocked.getByRole("status")).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/candidate-verification-mobile.png" });
  await blocked.getByRole("button", { name: "下一段", exact: true }).click();
  await expect(page.getByLabel("片段 #3 詳情")).toContainText("已通過 AI 檢查");
  await page.getByRole("button", { name: "將 #3 放入剪輯草稿" }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("150");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("6");
  await expect(page.getByRole("checkbox")).not.toBeChecked();
});

test("desktop onboarding and guide support keyboard dismissal and restore focus", async ({ page }) => {
  await workspace(page);
  await expect(page.getByRole("list", { name: "剪輯流程" }).locator('[aria-current="step"]')).toHaveText("1匯入素材");
  await page.screenshot({ path: "../runs/studio-welcome-desktop.png", fullPage: true });
  const help = page.getByRole("button", { name: "操作指南", exact: true });
  await help.click();
  const guide = page.getByRole("dialog", { name: "從一支實況，到一場勝利。" });
  await expect(guide).toBeVisible();
  await expect(guide).toContainText("5–10 秒");
  await expect(guide).toContainText("桌面快捷操作");
  await page.screenshot({ path: "../runs/studio-guide-desktop.png" });
  await page.keyboard.press("Escape");
  await expect(guide).not.toBeVisible();
  await expect(help).toBeFocused();
});

test("import can recover an empty or failed source list without closing the dialog", async ({ page }) => {
  await workspace(page);
  await page.getByRole("button", { name: "建立第一個剪輯" }).click();
  const dialog = page.getByRole("dialog", { name: "帶入你的下一場勝利" });
  await expect(dialog.getByText("先放入一支錄影")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "建立剪輯專案" })).toBeDisabled();
  await page.route("**/api/sources", route => route.fulfill({ status: 500, json: { detail: "測試：素材讀取失敗" } }));
  await dialog.getByRole("button", { name: "重新整理素材" }).click();
  await expect(dialog.getByRole("alert")).toContainText("無法載入素材");
  await page.route("**/api/sources", route => route.fulfill({ json: [{ path: "downloads/victory.mp4", name: "victory.mp4", size: 1000000 }] }));
  await dialog.getByRole("button", { name: "重新整理素材" }).click();
  await dialog.getByLabel("選擇影片").selectOption("downloads/victory.mp4");
  await expect(dialog.getByRole("button", { name: "建立剪輯專案" })).toBeEnabled();
  await page.screenshot({ path: "../runs/studio-import-desktop.png" });
});

test("YouTube form validates inline, preserves failed input, and submits a trimmed URL", async ({ page }) => {
  await workspace(page);
  await page.getByRole("button", { name: "匯入影片", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "帶入你的下一場勝利" });
  await dialog.getByRole("button", { name: "YouTube 網址" }).click();
  const input = dialog.getByLabel("公開影片網址");
  await input.fill("https://example.com/video");
  let requests = 0;
  await page.route("**/api/projects", route => { requests++; return route.fulfill({ status: 500, json: { detail: "來源暫時無法讀取" } }); });
  await dialog.getByRole("button", { name: "建立剪輯專案" }).click();
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(input).toBeFocused();
  expect(requests).toBe(0);
  await input.fill(" https://www.youtube.com/watch?v=example ");
  await dialog.getByRole("button", { name: "建立剪輯專案" }).click();
  await expect(dialog.getByRole("alert").filter({ hasText: "來源暫時無法讀取" })).toBeFocused();
  await expect(input).toHaveValue(" https://www.youtube.com/watch?v=example ");
  await page.route("**/api/projects", route => {
    expect(route.request().postDataJSON()).toEqual({ kind: "youtube", source: "https://www.youtube.com/watch?v=example" });
    return route.fulfill({ json: { project } });
  });
  await dialog.getByRole("button", { name: "建立剪輯專案" }).click();
  await expect(dialog).not.toBeVisible();
});

test("library search preserves the working draft and workflow follows review changes", async ({ page }) => {
  await workspace(page, [project, { ...project, id: "second", title: "黑暗靈魂 · 無名王者" }]);
  const steps = page.getByRole("list", { name: "剪輯流程" });
  await expect(steps.locator('[aria-current="step"]')).toContainText("核對片段");
  await page.getByRole("checkbox").check();
  await expect(steps.locator('[aria-current="step"]')).toContainText("匯出成品");
  await page.getByLabel("搜尋素材庫").fill("無名");
  await expect(page.locator(".project-card")).toHaveCount(1);
  await expect(page.locator(".project-card")).toHaveAttribute("title", "黑暗靈魂 · 無名王者");
  await expect(page.getByRole("checkbox")).toBeChecked();
  await page.getByLabel("搜尋素材庫").fill("不存在");
  await expect(page.getByRole("status").filter({ hasText: "找不到符合的影片" })).toBeVisible();
  await page.getByRole("button", { name: "清除素材搜尋" }).click();
  await expect(page.locator(".project-card")).toHaveCount(2);
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toBeFocused();
  await page.getByLabel("開始時間").fill("125");
  await expect(steps.locator('[aria-current="step"]')).toContainText("核對片段");
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeDisabled();
  await expect(page.locator(".compact-export")).toContainText("看完片段並勾選確認即可匯出");
});

test("desktop layouts keep review and export visible and preserve the player in theater mode", async ({ page }) => {
  await workspace(page, [project]);
  for (const [width, height] of [[1280, 800], [1440, 900], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
    await expect(page.getByRole("checkbox")).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `../runs/studio-editor-${width}.png` });
  }
  const player = page.locator(".video-wrap video");
  await player.evaluate((video: HTMLVideoElement) => { video.dataset.instance = "original"; video.currentTime = 160; });
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  await expect(player).toHaveAttribute("data-instance", "original");
  await page.keyboard.press("Escape");
  await expect(player).toHaveAttribute("data-instance", "original");
  expect(await player.evaluate((video: HTMLVideoElement) => video.currentTime)).toBe(160);
});

test("guide prevents editor shortcuts from changing a draft and reduced motion is honored", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await workspace(page, [project]);
  await page.getByRole("button", { name: "操作指南", exact: true }).click();
  const guide = page.getByRole("dialog", { name: "從一支實況，到一場勝利。" });
  await guide.getByRole("heading", { name: "03 · 逐段核對與調整" }).click();
  await page.keyboard.press("i");
  await page.keyboard.press("o");
  await page.keyboard.press("Escape");
  await expect(page.getByLabel("開始時間")).toHaveValue("120");
  await expect(page.getByLabel("勝利時間")).toHaveValue("320");
  expect(await page.getByRole("button", { name: "匯出 MP4", exact: true }).evaluate(element => getComputedStyle(element).transitionDuration)).toBe("0s");
});

test("the candidate track aligns a dashed draft reference on the same zoomed time scale", async ({ page }) => {
  const candidates = [
    { id: "compare:one", start: 40, end: 200, boss: "完整涵蓋的挑戰" },
    { id: "compare:two", start: 160, end: 230, boss: "部分重疊的挑戰" },
    { id: "compare:three", start: 400, end: 440, boss: "其他挑戰" },
  ].map(segment => ({ ...segment, victory: null, kind: "fight", confidence: "low", summary: "原片對照", warnings: [], evidence: [] }));
  await workspace(page, [{ ...project, duration: 600, draft: { ...project.draft, start: 60, victory: 180, postroll: 8, reviewed: true } }],
    [{ id: "compare", project_id: project.id, kind: "analyze", status: "succeeded", candidates }]);
  const summary = page.locator("#source-selection-details");
  const comparison = page.getByRole("group", { name: "候選時間軸定位", exact: true });
  const overlays = comparison.locator(".source-selection-fill");
  const bars = comparison.locator(".candidate-duration");
  const source = page.getByRole("slider", { name: "播放位置", exact: true });
  async function expectOverlay(start: number, end: number) {
    const from = Number(await source.getAttribute("min"));
    const to = Number(await source.getAttribute("max"));
    const position = (value: number) => Math.max(0, Math.min(100, (value - from) / (to - from) * 100));
    await expect(overlays).toHaveCount(1);
    for (const overlay of await overlays.all()) {
      const values = await overlay.evaluate((el: HTMLElement) => ({ left: parseFloat(el.style.left), width: parseFloat(el.style.width), pointer: getComputedStyle(el).pointerEvents }));
      expect(values.left).toBeCloseTo(position(start), 4);
      expect(values.width).toBeCloseTo(position(end) - position(start), 4);
      expect(values.pointer).toBe("none");
    }
  }
  await expect(page.locator(".source-selection-summary, .source-selection-overview, .current-draft-range")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "草稿原片對照", exact: true })).toHaveCount(0);
  await expectOverlay(60, 188);
  await expect(overlays).toHaveClass(/source-reference-fill/);
  await expect(overlays).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(overlays).toHaveCSS("box-shadow", "none");
  await expect(comparison.locator(".source-selection-postroll")).toHaveCount(0);
  const originalBars = await bars.evaluateAll(elements => elements.map(el => el.getAttribute("style")));
  await expect(summary).toContainText("00:01:00.000 → 00:03:08.000");
  await expect(summary).toContainText("片長 00:02:08.000 · 含收尾 8 秒");
  await page.getByRole("slider", { name: "片段開始邊界", exact: true }).press("Shift+ArrowRight");
  await expect(summary).toContainText("00:01:01.000 → 00:03:08.000");
  await expectOverlay(61, 188);
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("slider", { name: "勝利位置邊界", exact: true }).press("Shift+ArrowRight");
  await expect(summary).toContainText("00:01:01.000 → 00:03:09.000");
  await expectOverlay(61, 189);
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await page.getByLabel("勝利後收尾").fill("5");
  await expect(summary).toContainText("片長 00:02:05.000 · 含收尾 5 秒");
  await expectOverlay(61, 186);
  expect(await bars.evaluateAll(elements => elements.map(el => el.getAttribute("style")))).toEqual(originalBars);
  await comparison.screenshot({ path: "../runs/source-selection-ai-overlays.png" });
  expect((await new AxeBuilder({ page }).include(".unified-workbench").analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "放大片段", exact: true }).click();
  await expect(source).toHaveAttribute("min", "56");
  await expectOverlay(61, 186);
  await page.getByRole("region", { name: "片段工作區", exact: true }).screenshot({ path: "../runs/source-selection-comparison.png" });
  // Moving the view clips the overlay, without changing actual overlap durations.
  await page.getByRole("slider", { name: "可視範圍位置", exact: true }).press("Shift+ArrowRight");
  await expectOverlay(61, 186);
  await expect(comparison.locator(".source-selection-edge")).toHaveCount(1);
  await page.getByRole("slider", { name: "可視範圍位置", exact: true }).press("Home");
  await expectOverlay(61, 186);
  await expect(comparison.locator(".source-selection-postroll")).toHaveCount(0);
  await expect(comparison.locator(".source-selection-edge")).toHaveCount(1);
  await page.getByRole("slider", { name: "可視範圍位置", exact: true }).press("End");
  await expect(page.getByText("目前剪輯區間在可視範圍外", { exact: false })).toBeVisible();
  await expect(overlays).toHaveCount(0);
  await expect(summary).toContainText("00:01:01.000 → 00:03:06.000");
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  await expectOverlay(61, 186);
  // Check updates while the trim handle is still held, not just on release.
  const handle = page.getByRole("slider", { name: "片段開始邊界", exact: true });
  await handle.scrollIntoViewIfNeeded();
  const handleBox = (await handle.boundingBox())!;
  const trackBox = (await page.locator(".clip-range-track").boundingBox())!;
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(trackBox.x + trackBox.width * 90 / 600, handleBox.y + handleBox.height / 2, { steps: 5 });
  const draggedStart = Number(await handle.getAttribute("aria-valuenow"));
  expect(draggedStart).toBeCloseTo(90, 0);
  await expectOverlay(draggedStart, 186);
  await page.mouse.up();
  await page.getByLabel("開始時間").fill("200");
  await expect(summary).toContainText("目前區間無效");
  await expect(overlays).toHaveCount(0);
});

test("source comparison handles exact candidate boundaries and a draft reaching the source end", async ({ page }) => {
  const candidates = [
    { id: "edge:one", start: 0, end: 60 },
    { id: "edge:two", start: 60, end: 100 },
  ].map(segment => ({ ...segment, boss: "邊界測試", victory: null, kind: "fight", confidence: "low", summary: "邊界對照", warnings: [], evidence: [] }));
  await workspace(page, [{ ...project, duration: 100, draft: { ...project.draft, start: 60, victory: 92, postroll: 8 } }],
    [{ id: "edge", project_id: project.id, kind: "analyze", status: "succeeded", candidates }]);
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  const comparison = page.getByRole("group", { name: "候選時間軸定位", exact: true });
  await expect(comparison.locator(".source-selection-fill")).toHaveCount(1);
  await expect(comparison.locator(".source-selection-fill").first()).toHaveCSS("pointer-events", "none");
  expect(await comparison.locator(".source-selection-edge").evaluateAll(elements => elements.map(el => (el as HTMLElement).style.left)))
    .toEqual(["60%", "100%"]);
  await comparison.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.locator(".source-candidate-overlap")).toHaveText("與目前剪輯未重疊");
  await comparison.getByRole("button", { name: /時間軸片段 #2 / }).click();
  await expect(page.locator(".source-candidate-overlap")).toHaveText("與目前剪輯重疊 00:00:40.000");
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await page.getByLabel("開始時間").fill("0");
  await expect(comparison.locator(".source-selection-fill")).toHaveCount(1);
  for (const overlay of await comparison.locator(".source-selection-fill").all()) {
    expect(await overlay.evaluate((el: HTMLElement) => [el.style.left, el.style.width])).toEqual(["0%", "100%"]);
  }
  await comparison.getByRole("button", { name: /時間軸片段 #1 / }).click();
  await expect(page.locator(".source-candidate-overlap")).toHaveText("與目前剪輯重疊 00:01:00.000");
});

test("without AI candidates the selection stays on the existing source track", async ({ page }) => {
  await workspace(page, [project]);
  await expect(page.locator(".clip-range-track .source-selection-fill")).toBeVisible();
  await expect(page.locator(".source-selection-summary, .source-selection-overview, .current-draft-range")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "草稿原片對照", exact: true })).toHaveCount(0);
});

test("start, victory and export end remain distinct on a full long VOD, and postroll moves only the end", async ({ page }) => {
  await workspace(page, [{ ...project, duration: 21600, draft: { ...project.draft, start: 21000, victory: 21001, postroll: 8 } }]);
  await page.getByRole("button", { name: "看全片", exact: true }).click();
  const track = page.locator(".clip-range-track");
  const victory = page.getByRole("slider", { name: "勝利位置邊界", exact: true });
  const end = track.locator(".clip-end-marker");
  await expect(track.locator("svg")).toHaveCount(0);
  await expect(track.locator(".clip-point-label")).toHaveText(["開始", "勝利", "結束"]);
  async function expectDistinctLabels() {
    await track.scrollIntoViewIfNeeded();
    const bounds = (await track.boundingBox())!;
    const labels = await track.locator(".clip-point-label").evaluateAll(nodes => nodes.map(node => {
      const rect = node.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    }));
    for (const label of labels) {
      expect(label.left).toBeGreaterThanOrEqual(bounds.x - 1);
      expect(label.right).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
    }
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
      expect(labels[i].bottom <= labels[j].top || labels[j].bottom <= labels[i].top).toBe(true);
    }
  }
  await expectDistinctLabels();
  const originalVictoryLine = await track.locator(".clip-victory-guide").getAttribute("style");
  await page.getByLabel("勝利後收尾").fill("10");
  await expect(victory).toHaveAttribute("aria-valuenow", "21001");
  await expect(track.locator(".clip-victory-guide")).toHaveAttribute("style", originalVictoryLine!);
  await expect(page.locator(".clip-end-time")).toHaveText("片段結束 05:50:11.000");
  // CSSOM rounds percentage values; this tolerance is still well below one pixel.
  expect(await end.evaluate((node: HTMLElement) => parseFloat(node.style.left))).toBeCloseTo(21011 / 21600 * 100, 3);
  await victory.press("Shift+ArrowRight");
  await expect(page.getByLabel("勝利後收尾")).toHaveValue("10");
  await expect(page.locator(".clip-end-time")).toHaveText("片段結束 05:50:12.000");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("關閉 AI 對話").click();
  await expectDistinctLabels();
  await track.screenshot({ path: "../runs/clear-timeline-markers-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("sidebars collapse independently, preserve editing context and restore saved widths after reload", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("bosscut:panel-widths", JSON.stringify({ library: 280, chat: 420 })));
  await workspace(page, [project]);
  const player = page.locator(".video-wrap video");
  await player.evaluate((video: HTMLVideoElement) => { video.dataset.instance = "retained"; video.currentTime = 160; });
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await page.getByLabel("開始時間").fill("125");
  await page.getByLabel("搜尋素材庫").fill("女武神");
  await page.getByLabel("輸入訊息").fill("請保留這則尚未送出的訊息");
  const initialWidth = (await page.locator(".main-shell").boundingBox())!.width;
  const initialVideoWidth = (await page.locator(".preview-stage").boundingBox())!.width;
  await page.getByRole("button", { name: "收合素材庫側欄", exact: true }).click();
  const expandLibrary = page.getByRole("button", { name: "展開素材庫側欄", exact: true });
  await expect(expandLibrary).toHaveAttribute("aria-expanded", "false");
  await expect(expandLibrary).toBeFocused();
  await expect(page.getByRole("separator", { name: "調整素材庫寬度" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "影片專案" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "匯入影片", exact: true })).toBeVisible();
  expect((await page.locator(".main-shell").boundingBox())!.width).toBe(initialWidth + 216);
  await page.getByLabel("關閉 AI 對話").click();
  const expandChat = page.getByRole("button", { name: "AI 對話", exact: true });
  await expect(expandChat).toBeFocused();
  await expect(page.getByRole("separator", { name: "調整 AI 側欄寬度" })).toHaveCount(0);
  expect((await page.locator(".main-shell").boundingBox())!.width).toBe(initialWidth + 216 + 420);
  expect((await page.locator(".preview-stage").boundingBox())!.width).toBe(initialVideoWidth + 216 + 420);
  await expect(player).toHaveAttribute("data-instance", "retained");
  expect(await player.evaluate((video: HTMLVideoElement) => video.currentTime)).toBe(160);
  await expect(page.getByLabel("開始時間")).toHaveValue("125");
  await page.locator(".main-shell").evaluate(element => { element.scrollTop = 0; });
  await page.screenshot({ path: "../runs/sidebars-collapsed-desktop.png" });
  await page.getByRole("button", { name: "劇院模式", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(expandLibrary).toBeVisible();
  await expect(expandChat).toBeVisible();
  await expandChat.click();
  await expect(page.getByLabel("輸入訊息")).toHaveValue("請保留這則尚未送出的訊息");
  await expect(page.getByLabel("輸入訊息")).toBeFocused();
  await expandLibrary.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("搜尋素材庫")).toHaveValue("女武神");
  await expect(page.getByRole("separator", { name: "調整素材庫寬度" })).toHaveAttribute("aria-valuenow", "280");
  await expect(page.getByRole("separator", { name: "調整 AI 側欄寬度" })).toHaveAttribute("aria-valuenow", "420");
  await page.getByRole("button", { name: "收合素材庫側欄", exact: true }).click();
  await page.getByLabel("關閉 AI 對話").click();
  await page.reload();
  await expect(expandLibrary).toBeVisible();
  await expect(expandChat).toBeVisible();
  await expect(page.getByRole("navigation", { name: "影片專案" })).not.toBeVisible();
  await expect(page.getByLabel("輸入訊息")).not.toBeVisible();
  await expandLibrary.click();
  await expandChat.click();
  await expect(page.getByRole("separator", { name: "調整素材庫寬度" })).toHaveAttribute("aria-valuenow", "280");
  await expect(page.getByRole("separator", { name: "調整 AI 側欄寬度" })).toHaveAttribute("aria-valuenow", "420");
  await page.getByRole("button", { name: "精確調整", exact: true }).click();
  await expect(page.getByLabel("開始時間")).toHaveValue("125");
});

test("desktop workspace, import and guide meet automated accessibility checks", async ({ page }) => {
  const candidate = { id: "win-one", number: 1, start: 120, end: 328, victory: 320, kind: "possible_win", confidence: "high", boss: "女武神", summary: "可預覽並核對完整挑戰", warnings: [], evidence: [] };
  await workspace(page, [{ ...project, review_candidates: [candidate] }], [{ id: "finished", project_id: project.id, kind: "export", status: "succeeded", draft: project.draft }]);
  const violations: unknown[] = [];
  const check = async () => {
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    violations.push(...result.violations.map(item => ({ id: item.id, nodes: item.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) })));
  };
  await check();
  await page.getByRole("button", { name: /時間軸片段 #1/ }).click();
  await check();
  await page.getByRole("tab", { name: "成品 1" }).click();
  await page.getByRole("button", { name: "編輯成品 #1", exact: true }).click();
  await check();
  await page.getByRole("button", { name: "更多工具", exact: true }).click();
  await check();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "匯入影片", exact: true }).click();
  await check();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "操作指南", exact: true }).click();
  await check();
  expect(violations).toEqual([]);
});


test("unified workbench stays beside a full-height chat with one ruler", async ({ page }) => {
  await workspace(page, [project]);
  const source = page.getByRole("slider", { name: "播放位置", exact: true });
  await expect(source).toHaveAttribute("min", "115");
  await expect(source).toHaveAttribute("max", "333");
  await expect(page.locator(".source-time-ruler")).toHaveCount(1);
  await expect(page.locator(".video-wrap video")).not.toHaveAttribute("controls");
  await expect(page.getByRole("slider", { name: "片段結束邊界" })).toHaveCount(0);
  await expect(page.locator(".aligned-source-track, .aligned-candidates, .timeline-navigator")).toHaveCount(0);
  await expect(page.locator(".candidate-track .source-selection-fill")).toHaveCount(0);
  for (const [width, height] of [[1280, 800], [1440, 900], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    const player = (await page.locator(".preview-stage").boundingBox())!;
    const bench = (await page.locator(".preview-editing").boundingBox())!;
    const chat = (await page.locator(".chat-panel").boundingBox())!;
    expect(bench.width).toBeCloseTo(player.width, 0);
    expect(bench.x + bench.width).toBeLessThan(chat.x);
    expect(chat.y).toBe(0);
    expect(chat.height).toBe(height);
    expect(bench.height).toBe(260);
    await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
    await page.screenshot({ path: `../runs/resizable-workbench-${width}.png` });
  }
  await page.locator(".main-shell").evaluate(element => { element.scrollTop = 400; });
  expect((await page.locator(".chat-panel").boundingBox())!.y).toBe(0);
  await expect(page.getByLabel("輸入訊息")).toBeInViewport();
});

test("workbench resizes without changing edits or playback, remembers height and bounds it to the window", async ({ page }) => {
  await workspace(page, [project]);
  const divider = page.getByRole("separator", { name: "調整剪輯區高度", exact: true });
  const player = page.locator(".video-wrap video");
  await player.evaluate((video: HTMLVideoElement) => { video.dataset.instance = "same-player"; video.currentTime = 160; video.playbackRate = 1.5; });
  await page.getByLabel("開始時間").fill("125");
  await page.getByLabel("輸入訊息").fill("保留尚未送出的訊息");
  const source = page.getByRole("slider", { name: "播放位置", exact: true });
  const view = [await source.getAttribute("min"), await source.getAttribute("max")];
  const videoHeight = (await player.boundingBox())!.height;
  const box = (await divider.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - 70, { steps: 6 });
  await expect(divider).toHaveAttribute("aria-valuenow", "330");
  await page.mouse.up();
  expect((await player.boundingBox())!.height).toBeCloseTo(videoHeight - 70, 0);
  await expect(player).toHaveAttribute("data-instance", "same-player");
  expect(await player.evaluate((video: HTMLVideoElement) => [video.currentTime, video.playbackRate])).toEqual([160, 1.5]);
  await expect(page.getByLabel("開始時間")).toHaveValue("125");
  await expect(page.getByLabel("輸入訊息")).toHaveValue("保留尚未送出的訊息");
  expect([await source.getAttribute("min"), await source.getAttribute("max")]).toEqual(view);
  await page.reload();
  await expect(divider).toHaveAttribute("aria-valuenow", "330");
  await divider.press("End");
  const preferred = Number(await divider.getAttribute("aria-valuenow"));
  await page.setViewportSize({ width: 1280, height: 720 });
  await expect.poll(async () => Number(await divider.getAttribute("aria-valuenow"))).toBeLessThan(preferred);
  expect((await page.locator(".preview-stage").boundingBox())!.height).toBeGreaterThanOrEqual(239);
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(divider).toHaveAttribute("aria-valuenow", String(preferred));
  await divider.press("Home");
  await expect(page.getByRole("button", { name: "縮小剪輯區", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "放大剪輯區", exact: true }).click();
  await expect(divider).toHaveAttribute("aria-valuenow", "200");
  await divider.press("Shift+ArrowUp");
  await expect(divider).toHaveAttribute("aria-valuenow", "240");
  await page.getByRole("button", { name: "還原剪輯區高度", exact: true }).click();
  await expect(divider).toHaveAttribute("aria-valuenow", "260");
  await expect(page.getByLabel("開始時間")).toHaveValue("125");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(divider).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

const crowdedProject = { ...project, review_candidates: Array.from({ length: 20 }, (_, index) => ({
  id: `overlap:${index}`, number: index + 1, start: 120 + index, end: 320, victory: null,
  kind: "fight", confidence: "low", boss: `挑戰 ${index + 1}`, summary: "等待核對", warnings: [], evidence: [], review: "pending",
})) };

test("wheel over crowded candidates scrolls only the workbench and keeps the player and export fixed", async ({ page }) => {
  await workspace(page, [crowdedProject]);
  const bench = page.getByLabel("剪輯與候選檢查區", { exact: true });
  const candidates = page.getByLabel("候選時間軸定位", { exact: true });
  const player = page.locator(".preview-stage");
  const original = await player.boundingBox();
  await expect(page.getByLabel("開始時間")).toBeInViewport();
  const timing = (await page.getByRole("region", { name: "剪輯設定", exact: true }).boundingBox())!;
  expect(timing.y + timing.height).toBeLessThan((await candidates.boundingBox())!.y);
  await candidates.locator(".candidate-marker").first().hover();
  const before = await bench.evaluate(element => element.scrollTop);
  await page.mouse.wheel(0, 200);
  await expect.poll(() => bench.evaluate(element => element.scrollTop)).toBeGreaterThan(before);
  expect(await candidates.evaluate(element => element.scrollTop)).toBe(0);
  expect(await page.locator(".main-shell").evaluate(element => element.scrollTop)).toBe(0);
  expect(await page.locator(".main-shell").evaluate(element => element.scrollHeight - element.clientHeight)).toBe(0);
  expect(await player.boundingBox()).toEqual(original);
  await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
  await candidates.locator(".candidate-marker").last().focus();
  await expect(candidates.locator(".candidate-marker").last()).toBeInViewport();
  expect(await candidates.evaluate(element => element.scrollTop)).toBe(0);
  await page.screenshot({ path: "../runs/single-scroll-candidates.png" });
});

test("more tools keeps history accessible, contains focus and restores the editor without moving it", async ({ page }) => {
  const jobs = Array.from({ length: 16 }, (_, index) => ({ id: `export:${index}`, project_id: project.id,
    kind: "export", status: "failed", error: "測試匯出失敗，可重試", draft: { ...project.draft, revision: index } }));
  await workspace(page, [project], jobs);
  await page.getByLabel("開始時間").fill("125");
  const player = page.locator(".video-wrap video");
  await player.evaluate((video: HTMLVideoElement) => { video.dataset.instance = "tools-player"; video.currentTime = 160; video.playbackRate = 1.5; });
  const trigger = page.getByRole("button", { name: "更多工具", exact: true });
  const bench = page.getByLabel("剪輯與候選檢查區", { exact: true });
  const before = await bench.evaluate(element => element.scrollTop);
  await expect(trigger).toContainText("需處理");
  await expect(trigger).toHaveAccessibleDescription("需處理");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "更多工具", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.locator(".jobs-details > summary").click();
  await dialog.getByRole("button", { name: "重試", exact: true }).last().focus();
  await expect(dialog.getByRole("button", { name: "重試", exact: true }).last()).toBeInViewport();
  expect(await dialog.locator(".editor-tools-content").evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  await page.route("**/jobs/**/retry", route => route.fulfill({ status: 500, json: { detail: "重試失敗，請稍後再試" } }));
  for (let attempt = 0; attempt < 2; attempt++) {
    await dialog.getByRole("button", { name: "重試", exact: true }).last().click();
    await expect(dialog.getByRole("alert")).toContainText("重試失敗，請稍後再試");
    await expect(dialog.getByRole("alert")).toBeInViewport();
    await expect(dialog.getByRole("alert")).toBeFocused();
  }
  await page.route("**/jobs/**/retry", route => route.fulfill({ json: {} }));
  await dialog.getByRole("button", { name: "重試", exact: true }).last().click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await dialog.getByRole("button", { name: "重試", exact: true }).last().focus();
  await page.keyboard.press("Tab");
  // Native dialogs can pass through browser chrome before starting another Tab cycle.
  if (await page.evaluate(() => document.activeElement === document.body)) await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "關閉更多工具", exact: true })).toBeFocused();
  await page.keyboard.press("i");
  await page.keyboard.press("o");
  await dialog.locator(".editor-tools-content").evaluate(element => { element.scrollTop = 0; });
  await page.screenshot({ path: "../runs/single-scroll-tools.png" });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  expect(await bench.evaluate(element => element.scrollTop)).toBe(before);
  await expect(player).toHaveAttribute("data-instance", "tools-player");
  expect(await player.evaluate((video: HTMLVideoElement) => [video.currentTime, video.playbackRate])).toEqual([160, 1.5]);
  await expect(page.getByLabel("開始時間")).toHaveValue("125");
});

test("short windows and phones scroll the page through candidates without an inner scroll trap", async ({ page }) => {
  await workspace(page, [crowdedProject]);
  await page.getByLabel("關閉 AI 對話").click();
  const bench = page.getByLabel("剪輯與候選檢查區", { exact: true });
  for (const [width, height] of [[1280, 600], [375, 812], [844, 390]]) {
    await page.setViewportSize({ width, height });
    await expect(page.getByRole("separator", { name: "調整剪輯區高度", exact: true })).toHaveCount(0);
    const scroller = page.locator(width <= 640 ? ".app" : ".main-shell");
    const first = page.locator(".candidate-marker").first();
    await first.hover();
    const before = await scroller.evaluate(element => element.scrollTop);
    await page.mouse.wheel(0, 180);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(before);
    expect(await bench.evaluate(element => element.scrollTop)).toBe(0);
    expect(await page.locator(".candidate-overview").evaluate(element => element.scrollTop)).toBe(0);
    await page.getByRole("button", { name: "匯出 MP4", exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "匯出 MP4", exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await scroller.evaluate(element => { element.scrollTop = 0; });
    await page.getByRole("button", { name: "更多工具", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "更多工具", exact: true })).toBeInViewport();
    await page.keyboard.press("Escape");
    await page.screenshot({ path: `../runs/single-scroll-${width}x${height}.png` });
  }
});

test.describe("touch candidate navigation", () => {
  test.use({ hasTouch: true });

  test("vertical swipes scroll without selecting or seeking; taps and horizontal drags still seek", async ({ page }) => {
    await workspace(page, [crowdedProject]);
    const marker = page.locator(".candidate-marker").first();
    const bench = page.getByLabel("剪輯與候選檢查區", { exact: true });
    const player = page.locator(".video-wrap video");
    await marker.scrollIntoViewIfNeeded();
    await player.evaluate((video: HTMLVideoElement) => { video.currentTime = 160; });
    const box = (await marker.boundingBox())!;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    const before = await bench.evaluate(element => element.scrollTop);
    const touch = await page.context().newCDPSession(page);
    await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
    for (const offset of [15, 40, 80, 120]) {
      await touch.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y - offset }] });
    }
    await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect.poll(() => bench.evaluate(element => element.scrollTop)).toBeGreaterThan(before);
    await expect(marker).toHaveAttribute("aria-pressed", "false");
    expect(await player.evaluate((video: HTMLVideoElement) => video.currentTime)).toBe(160);

    await marker.tap();
    await expect(marker).toHaveAttribute("aria-pressed", "true");
    const tapped = await player.evaluate((video: HTMLVideoElement) => video.currentTime);
    expect(tapped).toBeGreaterThan(160);
    const position = (await marker.boundingBox())!;
    const dragX = position.x + position.width / 2;
    const dragY = position.y + position.height / 2;
    await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: dragX, y: dragY }] });
    await touch.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: dragX + 40, y: dragY }] });
    await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    expect(await player.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(tapped);
    await expect(page.getByLabel("開始時間")).toHaveValue("120");
    await touch.detach();
  });
});
