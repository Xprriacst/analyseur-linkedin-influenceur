import { defineConfig, devices } from "@playwright/test";

/**
 * Tests E2E de non-régression contre le site dev déployé.
 * Cible et identifiants surchargeables par variables d'env (voir .env.example).
 *
 * Le backend Render free-tier dort (cold start ~30-50 s) → timeouts généreux.
 */
const BASE_URL = process.env.E2E_BASE_URL || "https://lkd-outreach-dev.netlify.app";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: BASE_URL,
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "public",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "authenticated",
      testIgnore: /smoke\.spec\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "playwright/.auth/user.json",
      },
    },
  ],
});
