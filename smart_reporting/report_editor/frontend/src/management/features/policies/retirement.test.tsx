import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PolicyRetirement } from './retirement'

let root: Root
let retired: unknown = null
let client: QueryClient
const fetcher = vi.fn()
const scope = { database: 'warehouse', companyId: 'a' }
const response = (body: unknown) => new Response(JSON.stringify(body))
beforeEach(() => {
  sessionStorage.clear(); retired = null
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      retired = { assetType: 'statistical_policy', assetId: 'monthly', revision: 1, reason: body.reason, replacement: body.replacement }
      return response(retired)
    }
    if (path.includes('/impact?')) return response({ items: [{ kind: 'default', referenceId: 'monthly-report', policyRevision: 1, basisId: null }], nextCursor: null })
    if (path.includes('/statistical-policies?')) return response({ items: [{ policyId: 'monthly', name: '月报口径', publishedRevision: 2 }], nextCursor: null })
    if (path.includes('revision=2')) return response({ published: { revision: 2, document: { name: '月报修正版' }, contentHash: 'hash-2' }, retirement: null })
    return response({ published: { revision: 1, document: { name: '月报口径' }, contentHash: 'hash-1' }, retirement: retired })
  })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset() })
async function until(check: () => void) {
  for (let i = 0; i < 70; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} }
  check()
}
const button = (name: string) => [...document.querySelectorAll('button')].find(item => item.textContent?.replaceAll(' ', '').includes(name))!
async function click(name: string) { await act(async () => button(name).click()) }
async function mount() {
  await act(async () => root.render(<QueryClientProvider client={client}><PolicyRetirement scope={scope} policyId="monthly" revision={1} username="admin" csrf="csrf" /></QueryClientProvider>))
  await until(() => expect(document.body.textContent).toContain('monthly-report'))
}
async function fill() {
  const input = document.querySelector<HTMLTextAreaElement>('[aria-label="退役原因"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, '原版本重复计算，停止用于新报告。'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认退役影响"]')!.click())
}
it('requires reviewed exact-version impact, reason and explicit confirmation', async () => {
  await mount(); expect(button('确认退役此版本').disabled).toBe(true)
  await fill(); await click('确认退役此版本')
  await until(() => expect(document.body.textContent).toContain('退役已登记'))
  const post = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(post).toHaveLength(1); expect(post[0][0]).toContain('/monthly/versions/1/retire')
  expect(JSON.parse(String(post[0][1].body))).toEqual({ scopeDatabase: 'warehouse', companyId: 'a', reason: '原版本重复计算，停止用于新报告。', replacement: null })
  expect(document.body.textContent).toContain('历史报告继续使用原依据')
})
it('recovers committed response loss after remount using exact-version GET only', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { const result = await handler(path, init); if (init?.method === 'POST') throw Error('lost'); return result })
  await mount(); await fill(); await click('确认退役此版本')
  await until(() => expect(document.body.textContent).toContain('退役结果待确认'))
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!)
  await mount(); await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('已确认原退役登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(fetcher.mock.calls.filter(([path, init]) => init?.method === 'GET' && path.includes('revision=1')).length).toBeGreaterThan(0)
})
it('preserves the original request when a different retirement is read back', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { if (init?.method === 'POST') { retired = { assetType: 'statistical_policy', assetId: 'monthly', revision: 1, reason: '另一管理员的原因', replacement: null }; throw Error('lost') } return handler(path, init) })
  await mount(); await fill(); await click('确认退役此版本'); await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('退役记录与原提交不同'))
  expect(sessionStorage.length).toBe(1); expect(button('确认退役此版本').disabled).toBe(true)
})
it('does not POST if the pending request cannot be persisted', async () => {
  await mount(); await fill()
  const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('disabled') })
  await click('确认退役此版本')
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  expect(document.body.textContent).toContain('无法保存退役请求'); setter.mockRestore()
})
it('requires all impact pages before confirmation', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => path.includes('/impact?') && !path.includes('after=')
    ? response({ items: [{ kind: 'report', referenceId: 'old-report', policyRevision: 1, basisId: 'basis-1' }], nextCursor: 'report:old-report' }) : handler(path, init))
  await act(async () => root.render(<QueryClientProvider client={client}><PolicyRetirement scope={scope} policyId="monthly" revision={1} username="admin" csrf="csrf" /></QueryClientProvider>))
  await until(() => expect(document.body.textContent).toContain('old-report'))
  await fill(); expect(button('确认退役此版本').disabled).toBe(true)
  await click('加载更多影响'); await until(() => expect(button('确认退役此版本').disabled).toBe(false))
})

it('permits only an explicitly confirmed retry after reading no retirement for the same immutable version', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { if (init?.method === 'POST') throw Error('not committed'); return handler(path, init) })
  await mount(); await fill(); await click('确认退役此版本'); await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('尚无退役记录'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  expect(button('确认重提原退役请求').disabled).toBe(true)
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="确认退役影响"]')!.click())
  fetcher.mockImplementation(handler); await click('确认重提原退役请求')
  await until(() => expect(document.body.textContent).toContain('退役已登记'))
  const bodies = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST').map(([, init]) => init?.body)
  expect(bodies).toHaveLength(2); expect(bodies[0]).toBe(bodies[1])
})

it('blocks writes when a pending cache is malformed', async () => {
  sessionStorage.setItem('management-policy-retirement:' + JSON.stringify(['admin', 'warehouse', 'a', 'monthly', 1]), '{broken')
  await mount(); expect(document.body.textContent).toContain('退役请求缓存无法读取')
  expect(button('确认退役此版本').disabled).toBe(true)
  expect(sessionStorage.getItem('management-policy-retirement:' + JSON.stringify(['admin', 'warehouse', 'a', 'monthly', 1]))).toBe('{broken')
})

async function chooseReplacement(version: string) {
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="登记替代版本"]')!.click())
  await until(() => expect(button('选择月报口径')).toBeTruthy())
  await click('选择月报口径')
  await act(async () => document.querySelector('[aria-label="替代发布版本"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  await until(() => expect(document.querySelector('.ant-select-item-option-content')).toBeTruthy())
  await act(async () => [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(item => item.textContent === version)!.click())
}

it('requires an explicit exact replacement and preserves it through lost-response recovery', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => { const value = await handler(path, init); if (init?.method === 'POST') throw Error('lost'); return value })
  await mount(); await chooseReplacement('版本 2')
  await until(() => expect(document.body.textContent).toContain('月报修正版'))
  await fill(); await click('确认退役此版本')
  await until(() => expect(document.body.textContent).toContain('退役结果待确认'))
  const post = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(String(post[1].body)).replacement).toEqual({ policyId: 'monthly', revision: 2 })
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root')!); await mount()
  await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('已确认原退役登记'))
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})

it('blocks an unfinished replacement selection and the version being retired', async () => {
  await mount(); await act(async () => document.querySelector<HTMLInputElement>('[aria-label="登记替代版本"]')!.click())
  await fill(); expect(button('确认退役此版本').disabled).toBe(true)
  await act(async () => document.querySelector<HTMLInputElement>('[aria-label="登记替代版本"]')!.click())
  await chooseReplacement('版本 1'); await fill()
  await until(() => expect(document.body.textContent).toContain('替代版本不能指向自身'))
  expect(button('确认退役此版本').disabled).toBe(true)
})

it('blocks an already retired replacement', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => path.includes('revision=2')
    ? response({ published: { revision: 2, document: { name: '月报修正版' }, contentHash: 'hash-2' },
      retirement: { assetType: 'statistical_policy', assetId: 'monthly', revision: 2, reason: '已退役', replacement: null } }) : handler(path, init))
  await mount(); await chooseReplacement('版本 2')
  await until(() => expect(document.body.textContent).toContain('替代版本已退役'))
  await fill(); expect(button('确认退役此版本').disabled).toBe(true)
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
})

it('retains a pending request when readback has the same reason but a different replacement', async () => {
  const handler = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { await handler(path, init); (retired as { replacement: unknown }).replacement = null; throw Error('lost') }
    return handler(path, init)
  })
  await mount(); await chooseReplacement('版本 2'); await until(() => expect(document.body.textContent).toContain('月报修正版'))
  await fill(); await click('确认退役此版本'); await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('退役记录与原提交不同'))
  expect(sessionStorage.length).toBe(1); expect(button('确认退役此版本').disabled).toBe(true)
})

it('archives an uncommitted request before allowing a retired replacement to be reselected', async () => {
  const handler = fetcher.getMockImplementation()!
  let replacementRetired = false
  fetcher.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === 'POST') { replacementRetired = true; throw Error('not committed') }
    if (replacementRetired && path.includes('revision=2')) return response({ published: { revision: 2, document: { name: '月报修正版' }, contentHash: 'hash-2' },
      retirement: { assetType: 'statistical_policy', assetId: 'monthly', revision: 2, reason: '后来退役', replacement: null } })
    return handler(path, init)
  })
  await mount(); await chooseReplacement('版本 2'); await until(() => expect(document.body.textContent).toContain('月报修正版'))
  await fill(); await click('确认退役此版本'); await click('读取原退役结果')
  await until(() => expect(document.body.textContent).toContain('原替代版本已不可用'))
  await click('保留原请求并重新选择替代版本')
  expect(button('确认退役此版本').disabled).toBe(true)
  const savedKey = 'management-policy-retirement:' + JSON.stringify(['admin', 'warehouse', 'a', 'monthly', 1])
  expect(sessionStorage.getItem(savedKey)).toBeNull()
  expect(JSON.parse(sessionStorage.getItem(savedKey + ':prior')!)[0].replacement).toEqual({ policyId: 'monthly', revision: 2 })
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
})
