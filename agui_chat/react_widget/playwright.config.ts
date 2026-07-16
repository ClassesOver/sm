import { defineConfig, devices } from '@playwright/test'
import chromium from '@sparticuz/chromium'

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || await chromium.executablePath()

export default defineConfig({
  workers: 1,
  testDir: './visual-tests',
  outputDir: './test-results/visual',
  snapshotPathTemplate: '{testDir}/__screenshots__/{projectName}/{arg}{ext}',
  expect: { toHaveScreenshot: { animations: 'disabled', maxDiffPixelRatio: 0.01 } },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    colorScheme: 'light',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath,
      args: chromium.args
    }
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, isMobile: true } }
  ],
  webServer: {
    command: 'pnpm dev --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
    timeout: 120_000
  }
})
