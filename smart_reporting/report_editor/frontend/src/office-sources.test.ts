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

it('admin manages member table scope from workspace grants and preserves other drafts', async () => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true, value: function (this: HTMLDialogElement) { this.open = true },
  })
  const tables = ['db.orders', 'db.items']
  let memberTables: string[] | null = null
  const updates: (string[] | null)[] = []
  vi.stubGlobal('fetch', async (url: string, request: RequestInit) => {
    if (request.method === 'PUT') {
      memberTables = JSON.parse(String(request.body)).tables
      updates.push(memberTables)
      return Response.json({})
    }
    if (url.endsWith('/sales/members')) {
      return Response.json({ tables, members: [{ user: 'member', name: '成员' }, { user: 'other', name: '另一位成员' }], items: memberTables === null ? [] : [{ user: 'member', tables: memberTables }] })
    }
    if (url.endsWith('/members')) return Response.json({
      items: [{ user: 'member', name: '成员' }, { user: 'other', name: '另一位成员' }],
    })
    if (url.endsWith('/admin/workspaces')) return Response.json({ items: [{id: 'team', name: '团队'}] })
    if (url.endsWith('/table-access')) return Response.json({publishedTables: [{database: 'db', name: 'orders'}, {database: 'db', name: 'items'}]})
    if (url.endsWith('/data-sources/sales')) return Response.json({tables})
    return Response.json({ items: [{ source_id: 'sales', name: '销售', database: 'db', publishedRevision: 1 }], nextCursor: null })
  })
  const host = document.body.appendChild(document.createElement('div'))
  await showOfficeSources(host, { admin: true })
  const click = (label: string) => [...host.querySelectorAll('button')].find(button => button.textContent === label)!.click()
  click('工作区授权')
  await vi.waitFor(() => expect([...host.querySelectorAll('button')].some(button => button.textContent === '成员表权限')).toBe(true))
  click('成员表权限')
  await vi.waitFor(() => expect(host.textContent).toContain('继承工作区范围 · 2 张表'))
  const boxes = (member: string) => {
    const heading = [...host.querySelectorAll('h4')].find(node => node.textContent === member)!
    return [...heading.parentElement!.querySelectorAll<HTMLInputElement>('input[type=checkbox]')]
  }
  boxes('另一位成员')[0].checked = false
  for (const input of boxes('成员')) input.checked = false
  click('保存成员范围')
  await vi.waitFor(() => expect(host.textContent).toContain('自定义范围 · 无可访问表'))
  expect(boxes('另一位成员').map(box => box.checked)).toEqual([false, true])
  click('继承工作区范围')
  await vi.waitFor(() => expect(host.textContent).not.toContain('自定义范围 · 无可访问表'))
  expect(boxes('另一位成员').map(box => box.checked)).toEqual([false, true])
  expect(updates).toEqual([[], null])
})


it('workspace ownership does not expose member data-source administration', async () => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true, value(this: HTMLDialogElement) { this.open = true },
  })
  vi.stubGlobal('fetch', async () => Response.json({items: [{id: 'sales', name: '销售', available: true, tables: ['db.orders']}]}))
  const host = document.body.appendChild(document.createElement('div'))
  await showOfficeSources(host, {admin: false, space: {id: 'team', name: 'Team', role: 'owner', personal_user: null, archived: false}})
  expect(host.textContent).not.toContain('成员表权限')
  expect(host.textContent).toContain('执行查询')
})

it.each([200, 503])('source draft freezes editable fields and retains immutable identity after HTTP %s', async status => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true, value(this: HTMLDialogElement) { this.open = true },
  })
  let finish!: (response: Response) => void
  let body: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', async (url: string, request: RequestInit) => {
    if (request.method === 'PUT') {
      body = JSON.parse(String(request.body))
      return await new Promise<Response>(resolve => {finish = resolve})
    }
    if (url.endsWith('/table-access')) return Response.json({draftTables: [], publishedTables: [], discoveryId: null})
    if (url.endsWith('/sales')) return Response.json({draft: {source_id: 'sales', name: body?.name ?? 'Sales', database: 'db', version: 1, metadata_version_id: null}})
    return Response.json({items: [{source_id: 'sales', name: 'Sales', database: 'db', publishedRevision: null}], nextCursor: null})
  })
  const host = document.body.appendChild(document.createElement('div'))
  await showOfficeSources(host, {admin: true})
  ;[...host.querySelectorAll('button')].find(x => x.textContent === '连接与表范围')!.click()
  await vi.waitFor(() => expect(host.querySelector('dialog')!.getAttribute('aria-busy')).toBeNull())
  const get = (label: string) => host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
  const identity = get('数据源标识'), name = get('名称'), database = get('数据库'), dsn = get('更换连接地址（留空保留）')
  name.value = 'Changed sales'; dsn.value = 'starrocks://user:test@db.example/db'
  host.querySelector('form')!.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))
  expect([identity, name, database, dsn].every(input => input.disabled)).toBe(true)
  expect(body).toMatchObject({name: 'Changed sales', dsn: 'starrocks://user:test@db.example/db'})
  finish(Response.json(status === 200 ? {} : {message: '暂时不可用'}, {status}))
  await vi.waitFor(() => expect(host.querySelector('dialog')!.getAttribute('aria-busy')).toBeNull())
  expect(get('数据源标识').disabled).toBe(true)
  expect(get('名称').disabled).toBe(false)
  expect(get('名称').value).toBe('Changed sales')
  expect(get('更换连接地址（留空保留）').value).toBe(status === 200 ? '' : 'starrocks://user:test@db.example/db')
  if (status === 503) expect(host.textContent).toContain('暂时不可用')
})
