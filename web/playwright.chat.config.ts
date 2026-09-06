import { defineConfig } from "@playwright/test";

// Isolated UI tests: mocked API, no media fixture, backend, or real AI requests.
export default defineConfig({
  testDir: "./tests", testMatch: "chat.spec.ts", workers: 1,
  outputDir: "../runs/chat-ui-tests", timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:8011", viewport: { width: 1440, height: 900 } },
  webServer: { command: "npm run dev -- --port 8011", url: "http://127.0.0.1:8011", reuseExistingServer: false },
});
