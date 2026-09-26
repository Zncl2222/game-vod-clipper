import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests", testMatch: "storage.spec.ts", workers: 1,
  outputDir: "../runs/storage-ui-tests", timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:8012", viewport: { width: 1440, height: 1080 } },
  webServer: {
    command: "uv run --extra web python web/tests/serve_storage_fixture.py", cwd: "..",
    url: "http://127.0.0.1:8012/api/state", reuseExistingServer: process.env.BOSSCUT_TEST_REUSE_SERVER === "1",
  },
});
