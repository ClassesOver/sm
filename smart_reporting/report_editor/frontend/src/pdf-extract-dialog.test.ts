import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { bindPdfExtractDialog, parsePdfExtractPages } from './pdf-extract-dialog'
import type { NativeSaveResponse } from './native-api'

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

const result = (): NativeSaveResponse => ({ documentId: 'child', revision: 1, parentRevision: null, revisionRegistered: true,
  artifacts: { pdf: { downloadUrl: '/reports/v1/download/verified/pdf', sha256: 'b'.repeat(64), size: 123 } },
  editor: { openUrl: '/reports/v1/native/open/child' }, validation: { ok: false, issues: [{ code: 'pending', message: '业务验收尚未完成' }] } })

function fixture() {
  const root = document.createElement('div'); document.body.append(root)
  let reason: string | null = null
  const extract = vi.fn(async (_payload: {requestId: string; expectedSha256: string; pages: number[]}) => result())
  const view = bindPdfExtractDialog({ root, pageCount: () => 4, currentPage: () => 2, unavailable: () => reason,
    sourceSha256: 'a'.repeat(64), extract })
  const dialog = root.querySelector('dialog')!, input = root.querySelector('input')!, apply = root.querySelector<HTMLButtonElement>('[data-pdf-extract-apply]')!
  return { root, view, dialog, input, apply, extract, block: () => { reason = '请先保存草稿' } }
}

it('parses 1-based ranges in requested order and rejects empty/duplicate/out-of-range selections', () => {
  expect(parsePdfExtractPages('4, 1-2', 4)).toEqual([4, 1, 2])
  for (const text of ['', '0', '5', '1,1', '1-3,2', '3-1', '1.5', '1e2', '1,', '1-1000000000']) expect(() => parsePdfExtractPages(text, 4)).toThrow()
})

it('extracts the saved version without mutating a draft and retains real links on validation failure', async () => {
  const f = fixture(); f.view.open(); expect(f.input.value).toBe('2')
  f.input.value = '4,1-2'; f.apply.click()
  await vi.waitFor(() => expect(f.root.querySelectorAll('a')).toHaveLength(2))
  expect(f.extract).toHaveBeenCalledTimes(1)
  expect(f.extract.mock.calls[0]![0]).toMatchObject({ expectedSha256: 'a'.repeat(64), pages: [4, 1, 2] })
  expect(f.root.textContent).toContain('验收未通过')
  expect(f.root.textContent).toContain('业务验收尚未完成')
  expect(f.root.querySelector('a')!.getAttribute('href')).toBe('/reports/v1/download/verified/pdf')
})

it('rejects forced submit after editing availability changes and invalid selections', async () => {
  const f = fixture(); f.view.open(); f.input.value = '0'; f.apply.click()
  await vi.waitFor(() => expect(f.root.textContent).toContain('页码'))
  expect(f.extract).not.toHaveBeenCalled()
  f.input.value = '1'; f.block(); f.apply.dispatchEvent(new MouseEvent('click'))
  await vi.waitFor(() => expect(f.root.textContent).toContain('请先保存草稿'))
  expect(f.extract).not.toHaveBeenCalled()
  f.dialog.close(); f.view.open(); expect(f.dialog.open).toBe(false)
})

it.each(['close', 'dispose'])('does not paint a late completed extraction after %s', async action => {
  const f = fixture(); let resolve!: (value: NativeSaveResponse) => void
  f.extract.mockImplementation(() => new Promise(done => { resolve = done }))
  f.view.open(); f.apply.click()
  if (action === 'close') f.dialog.close(); else f.view.dispose()
  const before = f.root.innerHTML
  resolve(result()); await new Promise(done => setTimeout(done, 0))
  expect(f.root.innerHTML).toBe(before)
  if (action === 'close') { f.view.open(); expect(f.root.querySelectorAll('a')).toHaveLength(2) }
})

it('does not expose unsafe cross-origin or script links from a result', async () => {
  const f = fixture(); f.extract.mockResolvedValue({ ...result(), artifacts: { pdf: { downloadUrl: 'https://foreign.invalid/file' } }, editor: { openUrl: 'javascript:alert(1)' } })
  f.view.open(); f.apply.click()
  await vi.waitFor(() => expect(f.root.textContent).toContain('验收未通过'))
  expect(f.root.querySelectorAll('a')).toHaveLength(0)
})

it('桌面标题关闭和底部关闭都返回入口，打开时聚焦页码并保留已有输入', () => {
  const f=fixture(),opener=document.createElement('button');document.body.append(opener);opener.focus()
  f.view.open()
  expect(f.dialog.querySelector('header h3')?.textContent).toBe('提取页面为独立 PDF')
  expect(document.activeElement).toBe(f.input)
  f.input.value='4,1-2'
  f.dialog.querySelector<HTMLButtonElement>('[aria-label="关闭提取页面"]')!.click()
  expect(f.dialog.open).toBe(false);expect(document.activeElement).toBe(opener)
  f.view.open();expect(f.input.value).toBe('4,1-2');expect(document.activeElement).toBe(f.input)
  ;[...f.dialog.querySelectorAll('button')].find(button=>button.textContent==='关闭')!.click()
  expect(document.activeElement).toBe(opener);expect(f.extract).not.toHaveBeenCalled()
})

it('结果区域展示具体失败原因和下载入口，重开不再发送提取请求', async () => {
  const f=fixture();f.view.open()
  const region=f.dialog.querySelector<HTMLElement>('[aria-label="提取结果"]')!
  expect(region).not.toBeNull();expect(region.hidden).toBe(true)
  f.apply.click();await vi.waitFor(()=>expect(region.querySelectorAll('a')).toHaveLength(2))
  expect(region.hidden).toBe(false);expect(region.dataset.state).toBe('warning')
  expect(region.textContent).toContain('业务验收尚未完成')
  f.dialog.close();f.view.open()
  expect(region.querySelectorAll('a')).toHaveLength(2);expect(f.extract).toHaveBeenCalledTimes(1)
})

it('等待期间显示繁忙状态并锁定页码和生成，仍可关闭并在完成后重开结果', async () => {
  const f=fixture();let done!:(value:NativeSaveResponse)=>void
  f.extract.mockImplementation(()=>new Promise(resolve=>{done=resolve}))
  f.view.open();f.apply.click()
  expect(f.dialog.getAttribute('aria-busy')).toBe('true');expect(f.input.disabled).toBe(true);expect(f.apply.disabled).toBe(true)
  const close=f.dialog.querySelector<HTMLButtonElement>('[aria-label="关闭提取页面"]')!
  expect(close.disabled).toBe(false);close.click()
  done(result());await new Promise(resolve=>setTimeout(resolve,0));f.view.open()
  expect(f.dialog.getAttribute('aria-busy')).toBe('false');expect(f.input.disabled).toBe(false);expect(f.apply.disabled).toBe(false)
  expect(f.dialog.querySelectorAll('a')).toHaveLength(2);expect(f.extract).toHaveBeenCalledTimes(1)
})

it('请求失败保留输入和请求身份，可重试且不会残留繁忙状态', async () => {
  const f=fixture();f.extract.mockRejectedValueOnce(new Error('连接暂时不可用'))
  f.view.open();f.input.value='4,1-2';f.apply.click()
  await vi.waitFor(()=>expect(f.root.textContent).toContain('连接暂时不可用'))
  expect(f.dialog.getAttribute('aria-busy')).toBe('false');expect(f.input.value).toBe('4,1-2')
  expect(f.dialog.querySelector<HTMLElement>('[aria-label="提取结果"]')?.dataset.state).toBe('error')
  f.apply.click();await vi.waitFor(()=>expect(f.dialog.querySelectorAll('a')).toHaveLength(2))
  expect(f.extract.mock.calls[1]![0]).toEqual(f.extract.mock.calls[0]![0])
})

it.each([false, true])('页码提取窗口在等待=%s时首尾Tab循环，销毁后移除焦点监听', waiting => {
  const f = fixture()
  if (waiting) f.extract.mockImplementation(() => new Promise(() => {}))
  f.view.open()
  if (waiting) f.apply.click()
  const controls = [...f.dialog.querySelectorAll<HTMLElement>('input,button')]
  for (const control of controls) Object.defineProperty(control, 'offsetParent', { value: document.body })
  const first = f.dialog.querySelector<HTMLButtonElement>('[aria-label="关闭提取页面"]')!
  const last = waiting ? [...f.dialog.querySelectorAll<HTMLButtonElement>('footer button')][0] : f.apply
  last.focus()
  const forward = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  last.dispatchEvent(forward)
  expect(forward.defaultPrevented).toBe(true); expect(document.activeElement).toBe(first)
  const backward = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })
  first.dispatchEvent(backward)
  expect(backward.defaultPrevented).toBe(true); expect(document.activeElement).toBe(last)
  expect(f.extract).toHaveBeenCalledTimes(waiting ? 1 : 0)
  f.view.dispose()
  const afterDispose = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  last.dispatchEvent(afterDispose); expect(afterDispose.defaultPrevented).toBe(false)
})

it('提取说明与进度滚动区在页码被禁用后仍有独立键盘阅读入口', () => {
  const f = fixture(); f.view.open()
  const region = f.dialog.querySelector<HTMLElement>('[role="region"][aria-label="提取说明与进度"]')
  expect(region).not.toBeNull()
  expect(region?.tabIndex).toBe(0)
  f.input.disabled = true
  region?.focus(); expect(document.activeElement).toBe(region)
  expect(region?.textContent).toContain('从已保存版本提取')
  f.view.dispose()
})
