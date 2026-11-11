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
