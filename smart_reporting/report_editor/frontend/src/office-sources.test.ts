import { afterEach, expect, it, vi } from 'vitest'
import { showOfficeSources } from './office-sources'

afterEach(() => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

it.each([403, 409])('clears query results and reloads table access after HTTP %s', async status => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true, value: function (this: HTMLDialogElement) { this.open = true },
  })
  let queries = 0
  const original = 'SELECT amount FROM db.old_table'
  const transport = vi.fn(async (url: string) => {
    if (url.endsWith('/query')) {
      if (++queries === 1) return Response.json({ columns: ['amount'], rows: [[42]], source: { queryId: 'first' } })
      return Response.json({ message: '数据源授权或版本已变化，请重新查询。' }, { status })
    }
    if (queries >= 2 && status === 403) return Response.json({ items: [{ id: 'sales', available: false, reason: '数据源授权已撤销' }] })
    return Response.json({ items: [{ id: 'sales', name: '销售', available: true,
      tables: queries < 2 ? ['db.old_table'] : ['db.new_table'] }] })
  })
  vi.stubGlobal('fetch', transport)
  const host = document.body.appendChild(document.createElement('div'))
  await showOfficeSources(host, { admin: false, space: {
    id: 'team', name: '团队', role: 'viewer', personal_user: null, archived: false,
  } })
  const input = host.querySelector('textarea')!
  const execute = [...host.querySelectorAll('button')].find(button => button.textContent === '执行查询')!
  input.value = original
  input.dispatchEvent(new Event('input'))
  execute.click()
  await vi.waitFor(() => expect(host.querySelector('.source-query-result td')?.textContent).toBe('42'))
  execute.click()
  await vi.waitFor(() => expect(host.textContent).toContain(status === 403 ? '数据源授权已撤销' : '可访问表：db.new_table'))
  expect(host.textContent).not.toContain('可访问表：db.old_table')
  expect(host.querySelector('.source-query-result td')).toBeNull()
  expect(host.querySelector('textarea')?.value).toBe(status === 403 ? undefined : original)
  expect(host.querySelector('[role=status]')?.textContent).toContain('数据源授权或版本已变化')
})
