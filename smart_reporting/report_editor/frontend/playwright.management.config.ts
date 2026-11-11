import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e/management',
  workers: 1,
  fullyParallel: false,
  timeout: 45000,
  outputDir: '../../../output/management-depth/browser-artifacts',
  reporter: [
    ['list'],
    [
      'json',
      { outputFile: '../../../output/management-depth/browser-summary.json' },
    ],
  ],
  use: {
    baseURL: 'http://127.0.0.1:7789',
    browserName: 'chromium',
    launchOptions: {
      executablePath: process.env.MANAGEMENT_CHROMIUM_EXECUTABLE,
    },
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    reducedMotion: 'reduce',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
