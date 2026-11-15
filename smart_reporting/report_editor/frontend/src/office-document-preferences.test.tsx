import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { DocumentPreferencesPanel } from './office-document-preferences'
import { formatOptions } from './management/features/configuration/format-labels'
let root: Root
const initial = { version: 3, document: { common: { signer: 'Alice', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' } } }
const button = (label: string) => [...document.querySelectorAll('button')].find(x => x.textContent === label)!
beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })); Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); document.body.innerHTML = '<main></main>'; root = createRoot(document.querySelector('main')!) })
afterEach(async () => { await act(async () => root.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('只提供通用及四种文档偏好，不提供 Markdown 和导出设置', async () => {
  await act(async () => root.render(<DocumentPreferencesPanel initial={initial} save={async x => x} close={() => {}} />))
  expect([...document.querySelectorAll('[role="tab"]')].map(x => x.textContent)).toEqual(['通用', '文档', '表格', '演示', '版式文档'])
  expect(formatOptions.some(x => x.key === 'md')).toBe(false)
  expect(document.body.textContent).not.toMatch(/Markdown|导出设置|生成目录|压缩/)
})
it('失败保留草稿和版本，关闭提示，重试成功后可以关闭', async () => {
  let fail = true
  const close = vi.fn(), save = vi.fn(async (value: typeof initial) => { if (fail) throw new Error('版本冲突'); return {...value, version: 4} })
  await act(async () => root.render(<DocumentPreferencesPanel initial={initial} save={save as never} close={close} />))
  const input = document.querySelector<HTMLInputElement>('[aria-label="署名"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'New signer'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  await act(async () => button('保存文档偏好').click())
  expect(document.querySelector('[role="alert"]')?.textContent).toBe('版本冲突')
  expect(input.value).toBe('New signer')
  expect(save.mock.calls[0][0].version).toBe(3)
  await act(async () => button('关闭').click())
  expect(close).not.toHaveBeenCalled()
  await act(async () => button('继续编辑').click())
  fail = false
  await act(async () => button('保存文档偏好').click())
  expect(document.querySelector('[role="status"]')?.textContent).toBe('已保存')
  await act(async () => button('关闭').click())
  expect(close).toHaveBeenCalledOnce()
})
it('保存期间落款样式所有输入禁用，避免回读覆盖输入', async () => {
  let finish!: (value: typeof initial) => void
  await act(async () => root.render(<DocumentPreferencesPanel initial={initial} save={() => new Promise(resolve => { finish = resolve })} close={() => {}} />))
  await act(async () => button('文档').click())
  await act(async () => button('落款样式').click())
  const input = document.querySelector<HTMLInputElement>('[aria-label="署名"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'New signer'); input.dispatchEvent(new Event('input', {bubbles: true})) })
  await act(async () => button('保存文档偏好').click())
  expect(finish).toBeDefined()
  expect(document.querySelector<HTMLInputElement>('[aria-label="落款颜色"]')!.disabled).toBe(true)
  expect(document.querySelector<HTMLInputElement>('[aria-label="落款字体"]')!.disabled).toBe(true)
  await act(async () => finish(initial))
})
