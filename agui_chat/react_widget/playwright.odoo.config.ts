import { defineConfig, devices } from '@playwright/test'
import chromium from '@sparticuz/chromium'
import { existsSync } from 'node:fs'

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || await chromium.executablePath()
const launchArgs = chromium.args.filter((arg) => !['--single-process', '--no-zygote'].includes(arg))
const localTestModule = new URL('../../agui_chat_test/__manifest__.py', import.meta.url)
const testModuleSetting = process.env.ODOO_E2E_WITH_AGUI_CHAT_TEST
const hasTestModule = testModuleSetting === '1' || (testModuleSetting !== '0' && existsSync(localTestModule))

export default defineConfig({
  workers: 1,
  fullyParallel: false,
  testDir: './integration-tests',
  testIgnore: hasTestModule ? [] : [
    '**/complex-document.spec.ts',
    '**/odoo-agentos.spec.ts',
    '**/qunit-complex.spec.ts'
  ],
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
