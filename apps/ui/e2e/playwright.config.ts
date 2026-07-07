/**
 * Live E2E + media Playwright config.
 *
 * Drives the REAL production frontend (vite preview of the built app) in a
 * real headed Chromium against the REAL engine sidecar (booted, seeded, and
 * health-gated in global-setup). Monochrome 1440-canvas viewport to match the
 * design brief. workers=1 + a shared singleton engine ⇒ the specs run against
 * one honest stack; nothing is mocked.
 */
import { defineConfig, devices } from "@playwright/test";
import { BASE_URL, PREVIEW_PORT, UI_DIR, VIDEO_DIR } from "./harness/e2e-env";

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  globalSetup: "./harness/global-setup.ts",
  globalTeardown: "./harness/global-teardown.ts",

  use: {
    baseURL: BASE_URL,
    headless: false, // §4.9: proven by clicking through the RUNNING app
    viewport: { width: 1440, height: 900 }, // design canvas
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },

  projects: [
    {
      name: "e2e",
      testMatch: /.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], channel: undefined },
    },
    {
      name: "media",
      testMatch: /.*\.media\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        // Genuinely RECORD the running app (§4.9.8) — never generated video.
        video: { mode: "on", size: { width: 1440, height: 900 } },
        contextOptions: { recordVideo: { dir: VIDEO_DIR, size: { width: 1440, height: 900 } } },
      },
    },
  ],

  webServer: {
    // Build then serve the REAL production frontend (not the dev server, not
    // mock mode). Reused across runs so reruns are fast.
    command: "npm run build && npm run preview -- --port " + PREVIEW_PORT + " --strictPort --host 127.0.0.1",
    cwd: UI_DIR,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
