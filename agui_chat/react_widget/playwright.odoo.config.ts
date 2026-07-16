import { defineConfig, devices } from '@playwright/test'
import chromium from '@sparticuz/chromium'

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || await chromium.executablePath()
const launchArgs = chromium.args.filter((arg) => !['--single-process', '--no-zygote'].includes(arg))

export default defineConfig({
  workers: 1,
  fullyParallel: false,
  testDir: './integration-tests',
  outputDir: './test-results/odoo',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: process.env.ODOO_E2E_URL || 'http://127.0.0.1:18069',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath,
      args: launchArgs
    }
  },
  projects: [
    {
      name: 'odoo-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }
    }
  ]
})
