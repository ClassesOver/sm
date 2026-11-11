import { transferableAbortController } from 'node:util'
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ManagementApp } from './app'
let root: Root
const fetcher = vi.fn()
const scope = {
  id: 'org',
  name: '测试机构',
  database: 'warehouse',
  companyId: '100',
}
const draft = {
  source_id: 'operations',
  version: 2,
  name: '经营数仓',
  source_type: 'starrocks',
  database: 'warehouse',
  profile_version_id: 'base:1',
  metadata_version_id: 'operations:1',
  content_hash: 'hash2',
}
const reply = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status })
let detail = {
  draft,
  published: null,
  enabled: true,
  hasUnpublishedChanges: true,
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  window.history.replaceState(
    {},
    '',
    '/management/sources?database=warehouse&companyId=100',
  )
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  vi.stubGlobal(
    'AbortController',
    class {
      constructor() {
        return transferableAbortController()
      }
    },
  )
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string) => {
    if (path.endsWith('/me'))
      return reply({ username: 'admin', csrfToken: 'csrf-secret' })
    if (path.includes('/scopes'))
      return reply({ items: [scope], nextCursor: null })
    if (path.includes('/versions'))
      return reply({ items: [], nextCursor: null })
    if (path.includes('/sources/operations')) return reply(detail)
    return reply({
      items: [
        {
          ...draft,
          enabled: true,
          publishedRevision: null,
          hasUnpublishedChanges: false,
        },
      ],
      nextCursor: null,
    })
  })
  document.body.innerHTML = '<div id="management-root"></div>'
  root = createRoot(document.getElementById('management-root')!)
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.unstubAllGlobals()
  fetcher.mockReset()
})
async function waitFor(check: () => void) {
  for (let n = 0; n < 70; n++) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30))
    })
    try {
      check()
      return
    } catch {}
  }
  check()
}
async function mount() {
  await act(async () => {
    root.render(<ManagementApp />)
  })
  await waitFor(() =>
    expect(document.querySelector('.ant-skeleton')).toBeNull(),
  )
}
async function input(label: string, value: string) {
  await act(async () => {
    const field = document.querySelector<HTMLInputElement>(`#${label}`)!
    expect(field).toBeTruthy()
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function submit() {
  await act(async () => {
    document
      .querySelector('form')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 40))
  })
}
it('未登录时显示登录与初始化说明', async () => {
  fetcher.mockImplementation(async () =>
    reply({ message: '管理会话已失效' }, 401),
  )
  await mount()
  await waitFor(() =>
    expect(document.body.textContent).toContain('bootstrap-admin'),
  )
  expect(document.querySelector('#username')).toHaveProperty('value', 'admin')
  expect(document.querySelector('#password')?.getAttribute('type')).toBe(
    'password',
  )
})
it('登录错误清除密码，不自动重试', async () => {
  fetcher.mockImplementation(async (path: string) =>
    reply(
      {
        message: path.includes('login')
          ? '用户名或密码错误。'
          : '管理会话已失效',
      },
      401,
    ),
  )
  await mount()
  await waitFor(() =>
    expect(document.querySelector('#password')).not.toBeNull(),
  )
  await input('password', 'private-password')
  await submit()
  await waitFor(() =>
    expect(document.body.textContent).toContain('用户名或密码错误'),
  )
  expect(document.querySelector('#password')).toHaveProperty('value', '')
  expect(
    fetcher.mock.calls.filter(([p]) => p.includes('auth/login')),
  ).toHaveLength(1)
  expect(localStorage.length).toBe(0)
})
it('显式URL组织读取列表，显示真实状态', async () => {
  await mount()
  await waitFor(() => expect(document.body.textContent).toContain('经营数仓'))
  expect(
    fetcher.mock.calls.some(([p]) =>
      p.includes('scopeDatabase=warehouse&companyId=100'),
    ),
  ).toBe(true)
  expect(document.body.textContent).toContain('未发布')
  expect(document.body.textContent).not.toContain('连接正常')
})
it('详情深链独立读取，编辑默认保持凭据', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  await mount()
  await waitFor(() =>
    expect(document.querySelector('#name')).toHaveProperty('value', '经营数仓'),
  )
  expect(document.querySelector('#dsn')).toBeNull()
  await input('name', '改名')
  await submit()
  const call = fetcher.mock.calls.find(([, o]) => o?.method === 'PUT')
  expect(call).toBeTruthy()
  const body = JSON.parse(call![1].body)
  expect(body.expectedVersion).toBe(2)
  expect(body.name).toBe('改名')
  expect(body).not.toHaveProperty('dsn')
  expect(call![1].headers['x-csrf-token']).toBe('csrf-secret')
})
it('后台不可用显示实际错误', async () => {
  fetcher.mockImplementation(async () =>
    reply({ message: '管理存储暂时不可用。' }, 503),
  )
  await mount()
  expect(document.body.textContent).toContain('管理存储暂时不可用')
  expect(document.body.textContent).not.toContain('暂无数据源')
})
it('业务401返回登录并清理表单', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  await mount()
  await waitFor(() => expect(document.querySelector('#name')).not.toBeNull())
  await input('name', '改名')
  fetcher.mockImplementation(async () =>
    reply({ message: '管理会话已失效，请重新登录。' }, 401),
  )
  await submit()
  await waitFor(() =>
    expect(document.querySelector('#password')).not.toBeNull(),
  )
  expect(document.querySelector('#name')).toBeNull()
})

it('慢保存期间不能继续修改而误丢未保存输入', async () => {
  window.history.replaceState(
    {},
    '',
    '/management/sources/operations/edit?database=warehouse&companyId=100',
  )
  const standard = fetcher.getMockImplementation()!
  let finish!: (response: Response) => void
  fetcher.mockImplementation((path: string, options?: { method?: string }) =>
    options?.method === 'PUT'
      ? new Promise((resolve) => {
          finish = resolve
        })
      : standard(path, options),
  )
  await mount()
  await waitFor(() => expect(document.querySelector('#name')).not.toBeNull())
  await act(async () => {
    document
      .querySelector<HTMLInputElement>('input[type=radio][value="true"]')!
      .click()
  })
  await input('dsn', 'starrocks://reader:private@localhost:9030/warehouse')
  await input('name', '提交快照')
  await submit()
  expect(document.querySelector('#name')).toHaveProperty('disabled', true)
  expect(document.querySelector('#database')).toHaveProperty('disabled', true)
  await act(async () => {
    finish(reply({ ...draft, name: '提交快照', version: 3 }))
    await new Promise((resolve) => setTimeout(resolve, 30))
  })
  expect(document.querySelector('#name')).toHaveProperty('disabled', false)
  expect(document.querySelector('#name')).toHaveProperty('value', '提交快照')
})
