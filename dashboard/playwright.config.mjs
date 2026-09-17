import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 30000,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://localhost:3011', channel: process.env.CI ? undefined : 'chrome', headless: true },
  webServer: {
    command: 'npm run dev -- --port 3011',
    url: 'http://localhost:3011/setup-guide',
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === '1',
    timeout: 120000,
    env: { WRANGLER_SEND_METRICS: 'false' },
  },
});
