import { expect, it } from 'vitest'
import { safeReturnTo } from './login'
it('returnTo只接受管理页面同源白名单', () => {
  for (const value of [
    'https://evil.test/management/sources',
    '//evil.test/management/sources',
    '/management/api/v1/me',
    '/management/assets/app.js',
    '/management/../evil',
    '/management/sources/../../evil',
    '/management/sources%2F..%2Fapi',
  ]) {
    expect(safeReturnTo(value)).toBe('/management/sources')
  }
  expect(
    safeReturnTo(
      '/management/sources/operations/edit?database=warehouse&companyId=100',
    ),
  ).toBe('/management/sources/operations/edit?database=warehouse&companyId=100')
})
it.each([
  '/management/metrics?editMetric=budget&metricId=budget&revision=1',
  '/management/statistical-policies?editPolicy=monthly',
  '/management/knowledge?documentId=rules&revision=2',
  '/management/report-issues?issueId=review-1',
  '/management/system-configuration',
  '/management/preferences',
])('重新登录保留当前维护任务及精确版本：%s', value => {
  expect(safeReturnTo(value)).toBe(value)
})
it('已移除的组织页面不能作为登录后返回入口', () => {
  expect(safeReturnTo('/management/organizations')).toBe('/management/sources')
})
