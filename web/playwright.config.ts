import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testIgnore: ["chat.spec.ts", "codex-login.spec.ts", "studio.spec.ts", "clip-library.spec.ts", "youtube.spec.ts", "usage.spec.ts", "workspace-tools.spec.ts", "storage.spec.ts"],
  workers: 1,
  outputDir: "../runs/editor-ui-tests",
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:8010",
    viewport: { width: 1440, height: 1080 },
  },
  webServer: {
    command: "uv run --extra web python web/tests/serve_fixture.py",
    cwd: "..",
    url: "http://127.0.0.1:8010/api/state",
    reuseExistingServer: process.env.BOSSCUT_TEST_REUSE_SERVER === "1",
    timeout: 60_000,
  },
});
