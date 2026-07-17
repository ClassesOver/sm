import { expect, test } from '@playwright/test'


const database = process.env.ODOO_E2E_DB || 'odoo12_agui_e2e'
const login = process.env.ODOO_E2E_LOGIN || 'admin'
const password = process.env.ODOO_E2E_PASSWORD || 'admin'


test('通用单据真实 BasicModel/FormController QUnit', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto(`/web/login?db=${encodeURIComponent(database)}`)
  await page.locator('input[name="login"]').fill(login)
  await page.locator('input[name="password"]').fill(password)
  await Promise.all([
    page.waitForURL(/\/web(?:#|$)/),
    page.locator('button[type="submit"]').click()
  ])

  const moduleName = 'agui_chat_test real form integration'
  await page.goto(
    `/web/tests?db=${encodeURIComponent(database)}&mod=agui_chat_test&module=${encodeURIComponent(moduleName)}&failfast`
  )
  await page.waitForFunction(() => {
    const result = document.querySelector('#qunit-testresult')
    return Boolean(result?.textContent?.includes('completed'))
  }, undefined, { timeout: 150_000 })

  const result = await page.evaluate(() => ({
    failed: Number(document.querySelector('#qunit-testresult .failed')?.textContent || '0'),
    passed: Number(document.querySelector('#qunit-testresult .passed')?.textContent || '0'),
    total: Number(document.querySelector('#qunit-testresult .total')?.textContent || '0'),
    executedTests: document.querySelectorAll('#qunit-tests > li.pass, #qunit-tests > li.fail').length,
    failures: Array.from(document.querySelectorAll('#qunit-tests > li.fail'))
      .map((item) => item.textContent?.replace(/\s+/g, ' ').trim())
  }))

  expect(result.failures).toEqual([])
  expect(result.failed).toBe(0)
  expect(result.passed).toBeGreaterThan(0)
  expect(result.total).toBe(result.passed)
  expect(result.executedTests).toBe(13)
})
