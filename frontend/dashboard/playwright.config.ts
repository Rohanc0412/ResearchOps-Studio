import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  workers: 1,
  timeout: 600_000, // 10 min — research runs can take several minutes
  expect: { timeout: 30_000 },
  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  outputDir: './playwright-results',
});
