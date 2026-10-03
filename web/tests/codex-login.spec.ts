import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { Connection } from "../src/components/ai/AIConnection";

const guest: Connection = { available: false, model: "model-a", detail: "尚未連接 ChatGPT 帳號。" };
const pending: Connection = { ...guest, login: { status: "pending", userCode: "TEST-1234", url: "https://auth.openai.com/codex/device" } };
const signedIn: Connection = { available: true, model: "model-a", auth_mode: "chatgpt", email: "demo@example.test", detail: "已登入 ChatGPT。", login: { status: "succeeded" } };

async function fixture(page: Page, initial: Connection = guest, options: { collapsed?: boolean; holdStatus?: Promise<void> } = {}) {
  const server = { account: initial, logins: 0, logouts: 0, tests: 0, failLogin: false, failLogout: false };
  if (options.collapsed) await page.addInitScript(() => {
    if (!localStorage.getItem("bosscut:panel-visibility")) localStorage.setItem("bosscut:panel-visibility", JSON.stringify({ library: true, chat: false }));
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/events") return route.fulfill({ contentType: "text/event-stream", body: 'data: {"projects":[],"jobs":[]}\n\n' });
    if (path === "/api/codex") {
      await options.holdStatus;
      return route.fulfill({ json: server.account });
    }
    if (path === "/api/codex/login") {
      server.logins++;
      expect(route.request().postDataJSON()).toEqual({ method: "chatgptDeviceCode" });
      if (server.failLogin) return route.fulfill({ status: 500, json: { detail: "測試：登入服務暫時無法使用" } });
      server.account = pending;
      return route.fulfill({ json: pending.login });
    }
    if (path === "/api/codex/login/cancel") {
      server.account = guest;
      return route.fulfill({ json: { cancelled: true } });
    }
    if (path === "/api/codex/logout") {
      expect(route.request().method()).toBe("POST");
      server.logouts++;
      if (server.failLogout) return route.fulfill({ status: 503, json: { detail: "測試：暫時無法登出" } });
      server.account = guest;
      return route.fulfill({ json: { logged_out: true } });
    }
    if (path === "/api/codex/test") server.tests++;
    if (path === "/api/codex/models") return route.fulfill({ json: { models: [{ id: "model-a", name: "Model A", is_default: true }] } });
    if (path === "/api/codex/rate-limits") return route.fulfill({ json: { available: false, buckets: [] } });
    if (path === "/api/codex/usage") return route.fulfill({ json: { requests: 0, sessions: [], recent_requests: [], project_requests: [] } });
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  return server;
}

test("loading status does not falsely claim the user is logged out", async ({ page }) => {
  let release!: () => void;
  const holdStatus = new Promise<void>(resolve => { release = resolve; });
  const server = await fixture(page, guest, { holdStatus });
  await expect(page.getByText("正在確認帳號…", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".codex-login-reminder")).toHaveCount(0);
  server.account = signedIn;
  release();
  await expect(page.getByText("Codex 已連接", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".codex-login-reminder")).toHaveCount(0);
  expect(server.logins).toBe(0);
});

test("homepage starts device login, prevents duplicate requests, and hides guidance after success", async ({ page }) => {
  const server = await fixture(page, guest, { collapsed: true });
  const reminder = page.locator(".codex-login-reminder");
  await expect(reminder).toContainText("使用 AI 前，記得登入你的 Codex 帳號");
  await page.screenshot({ path: "../runs/codex-login-desktop-reminder.png", fullPage: true });
  await reminder.getByRole("button", { name: "使用 ChatGPT 登入", exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  const steps = page.getByRole("list", { name: "Codex 登入步驟" });
  await expect(steps).toBeVisible();
  await expect(steps).toContainText("TEST-1234");
  await expect(steps.getByRole("link", { name: "前往 OpenAI 官方登入頁" })).toHaveAttribute("href", pending.login!.url!);
  await expect(reminder).toContainText("還差一步：完成 Codex 登入");
  expect(server.logins).toBe(1);
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { document.body.dataset.copied = value; } } }));
  await steps.getByRole("button", { name: "複製驗證碼" }).click();
  await expect(steps.getByRole("button", { name: "已複製" })).toBeVisible();
  expect(await page.locator("body").getAttribute("data-copied")).toBe("TEST-1234");
  await page.screenshot({ path: "../runs/codex-login-desktop-steps.png", fullPage: true });
  const accessibility = await new AxeBuilder({ page }).include(".codex-login-reminder").include("#codex-account-settings").analyze();
  expect(accessibility.violations).toEqual([]);
  server.account = signedIn;
  await expect(reminder).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Codex 登入步驟" })).toHaveCount(0);
  await expect(page.locator("#codex-account-settings")).not.toBeVisible();
  await expect(page.getByText("Codex 已連接", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "帳號設定", exact: true }).click();
  await expect(page.getByText("demo@example.test", { exact: false })).toBeVisible();
  expect(server.tests).toBe(0);
});

test("failure and expired login remain visible and allow retry or cancellation", async ({ page }) => {
  const server = await fixture(page);
  const account = page.locator("#codex-account-settings");
  await expect(account).toBeVisible();
  server.failLogin = true;
  await account.getByRole("button", { name: "使用 ChatGPT 登入", exact: true }).click();
  await expect(account.getByRole("alert")).toContainText("登入服務暫時無法使用");
  await expect(page.locator(".codex-login-reminder")).toBeVisible();
  server.failLogin = false;
  await account.getByRole("button", { name: "使用 ChatGPT 登入", exact: true }).click();
  await expect(account).toContainText("TEST-1234");
  server.account = { ...guest, login: { status: "failed" } };
  await expect(account.getByRole("alert")).toContainText("登入未完成或已過期");
  await account.getByRole("button", { name: "使用 ChatGPT 登入", exact: true }).click();
  await account.getByRole("button", { name: "取消登入" }).click();
  await expect(page.locator(".codex-login-reminder")).toContainText("使用 AI 前，記得登入");
  await expect(account.getByRole("button", { name: "使用 ChatGPT 登入", exact: true })).toBeEnabled();
  expect(server.logins).toBe(3);
});

test("returning to the workspace checks status and reminds a signed-out user even with chat history", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("bosscut:chat:v3", JSON.stringify({ messages: [{ id: "old", role: "assistant", content: "先前的對話" }], input: "" })));
  const server = await fixture(page, signedIn);
  await expect(page.getByText("Codex 已連接", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".codex-login-reminder")).toHaveCount(0);
  server.account = guest;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.locator(".codex-login-reminder")).toBeVisible();
  await expect(page.locator("#codex-account-settings")).toBeVisible();
  await expect(page.getByRole("list", { name: "Codex 登入步驟" })).toBeVisible();
});

test("mobile can resume a pending login from a collapsed sidebar without starting another login", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  const server = await fixture(page, pending, { collapsed: true });
  await page.locator(".codex-login-reminder").getByRole("button", { name: "查看登入步驟" }).click();
  const steps = page.getByRole("list", { name: "Codex 登入步驟" });
  await expect(steps).toBeVisible();
  await expect(steps).toContainText("TEST-1234");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../runs/codex-login-mobile.png", fullPage: true });
  expect(server.logins).toBe(0);
  await page.reload();
  await expect(steps).toBeVisible();
  expect(server.logins).toBe(0);
});

test("logout in account settings restores onboarding, clears the old chat and persists after reload", async ({ page }) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("bosscut:chat:v3")) sessionStorage.setItem("bosscut:chat:v3", JSON.stringify({ messages: [{ id: "old", role: "assistant", content: "舊帳號的對話" }], input: "未送出的內容" }));
  });
  const server = await fixture(page, signedIn);
  await expect(page.getByText("Codex 已連接", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "帳號設定", exact: true }).click();
  const account = page.locator("#codex-account-settings");
  await account.getByRole("button", { name: "登出 Codex", exact: true }).evaluate(button => { (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click(); });
  await expect(page.locator(".codex-login-reminder")).toBeVisible();
  await expect(account.getByRole("list", { name: "Codex 登入步驟" })).toBeVisible();
  await expect(account.getByRole("button", { name: "登出 Codex", exact: true })).toHaveCount(0);
  await expect(page.getByRole("log")).not.toContainText("舊帳號的對話");
  await expect(page.getByLabel("輸入訊息")).toHaveValue("");
  expect(server.logouts).toBe(1);
  expect(server.tests).toBe(0);
  await page.reload();
  await expect(page.locator(".codex-login-reminder")).toBeVisible();
  await expect(account.getByRole("button", { name: "使用 ChatGPT 登入", exact: true })).toBeEnabled();
});

test("failed logout preserves the signed-in account and offers a working retry", async ({ page }) => {
  const server = await fixture(page, signedIn);
  await expect(page.getByText("Codex 已連接", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "帳號設定", exact: true }).click();
  const account = page.locator("#codex-account-settings");
  server.failLogout = true;
  await account.getByRole("button", { name: "登出 Codex", exact: true }).click();
  await expect(account.getByRole("alert")).toContainText("暫時無法登出");
  await expect(account).toContainText("demo@example.test");
  await expect(page.locator(".codex-login-reminder")).toHaveCount(0);
  server.failLogout = false;
  await account.getByRole("button", { name: "登出 Codex", exact: true }).click();
  await expect(page.locator(".codex-login-reminder")).toBeVisible();
  expect(server.logouts).toBe(2);
});
