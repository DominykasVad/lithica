/**
 * The browser tests (e2e/), against the e2e stack: e2e/stack.sh up, then
 * pnpm e2e. A setup project imports the cards and makes the accounts once;
 * then each browser (Chromium, Firefox, WebKit) runs every test, one after
 * the other (the tests share one site).
 */
import { defineConfig, devices } from "@playwright/test";

const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "e2e",
  // one site for all: the tests run one at a time
  workers: 1,
  fullyParallel: false,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: process.env.E2E_URL ?? "http://localhost:8092",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /\.setup\.ts$/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
      testMatch: /\.spec\.ts$/,
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
      dependencies: ["setup"],
      testMatch: /\.spec\.ts$/,
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
      dependencies: ["setup"],
      testMatch: /\.spec\.ts$/,
    },
  ],
});
