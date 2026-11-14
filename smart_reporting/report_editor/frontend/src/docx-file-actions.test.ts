import { afterEach, expect, it, vi } from 'vitest'
import { createDocxFileActions } from './docx-file-actions'
import type { NativeWordFileResult } from './native-api'
const controls: ReturnType<typeof createDocxFileActions>[] = []
afterEach(() => { controls.splice(0).forEach(control => control.dispose()); document.body.replaceChildren() })
const result = (url = '/reports/v1/native/open/signed-token=='): NativeWordFileResult => ({ documentId: 'separate-document', revision: 1, filename: 'Copy.docx', editor: { openUrl: url, url: '/untrusted-fallback', expiresAt: '2026-11-15T00:00:00Z' } })
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }
function setup() {
  const root = document.createElement('div'); root.innerHTML = '<p>Original saved document</p>'; document.body.append(root)
  let dirty = false, blocked: string | null = null
  const api = { newWord: vi.fn(async () => result()), saveWordAs: vi.fn(async () => result()) }, onError = vi.fn(), navigate = vi.fn(), flush = vi.fn()
  const control = createDocxFileActions({ root, api, sourceSha256: 'a'.repeat(64), displayName: 'Original.docx', blocked: () => blocked, pendingEdits: () => dirty, flush, onError, navigate })
  controls.push(control)
  return { root, api, onError, navigate, flush, control, setDirty(value: boolean) { dirty = value }, setBlocked(value: string | null) { blocked = value }, submit: () => { const form = root.querySelector('form'); expect(form, 'opening a file action must render its form').not.toBeNull(); form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); return settle() } }
}
it('creates a separate named document while the current document is dirty and opens only on explicit link click', async () => {
  const f = setup(); f.setDirty(true); f.control.open('new')
  const input = f.root.querySelector<HTMLInputElement>('input'); expect(input, 'file action must render the filename input').not.toBeNull(); input!.value = 'New document.docx'; await f.submit()
  expect(f.api.newWord).toHaveBeenCalledWith({ requestId: expect.any(String), expectedSha256: 'a'.repeat(64), filename: 'New document.docx' })
  expect(f.api.saveWordAs).not.toHaveBeenCalled(); expect(f.navigate).not.toHaveBeenCalled()
  expect(f.root.querySelector('p')!.textContent).toBe('Original saved document')
  const link = f.root.querySelector<HTMLAnchorElement>('a')!; expect(link.textContent).toBe('打开新文档'); link.click()
  expect(f.navigate).toHaveBeenCalledWith(new URL(result().editor.openUrl, location.origin).href)
})
it('copies only a saved revision and refuses dirty content before and after flushing pending edits', async () => {
  const f = setup(); f.setDirty(true)
  expect(f.control.reason('save-as')?.includes('保存')).toBe(true); f.control.open('save-as')
  expect(f.root.querySelector('[role=dialog]:not([hidden])')).toBeNull(); expect(f.api.saveWordAs).not.toHaveBeenCalled()
  f.setDirty(false); f.control.open('save-as'); f.flush.mockImplementation(() => f.setDirty(true)); await f.submit()
  expect(f.api.saveWordAs).not.toHaveBeenCalled(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('保存')
})
it('submits Save As with a fresh request identity and the expected saved source hash', async () => {
  const f = setup(); f.control.open('save-as'); const input = f.root.querySelector<HTMLInputElement>('input'); expect(input, 'file action must render the filename input').not.toBeNull(); input!.value = 'Named copy.docx'; await f.submit()
  expect(f.api.saveWordAs).toHaveBeenCalledWith({ requestId: expect.any(String), expectedSha256: 'a'.repeat(64), filename: 'Named copy.docx' }); expect(f.flush).toHaveBeenCalledOnce()
  expect(f.root.querySelector('a')!.getAttribute('href')).toBe(new URL(result().editor.openUrl, location.origin).href)
})
it.each(['https://foreign.example/reports/v1/native/open/token', '/reports/v1/native/other/api/file', 'javascript:alert(1)', '/reports/v1/native/open/token?redirect=evil', '/reports/v1/native/open/%2f..'])('rejects an untrusted creation response URL %s', async url => {
  const f = setup(); f.api.newWord.mockResolvedValue(result(url)); f.control.open('new'); await f.submit()
  expect(f.root.querySelector('a')).toBeNull(); expect(f.onError).toHaveBeenCalledOnce(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('地址')
})
it('does not fall back to editor.url and reports a failed request without replacing the current document', async () => {
  const f = setup(); f.api.newWord.mockRejectedValue(new Error('Network request failed')); f.control.open('new'); await f.submit()
  expect(f.root.querySelector('a')).toBeNull(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('Network request failed'); expect(f.navigate).not.toHaveBeenCalled()
  f.api.newWord.mockResolvedValue(result('')); await f.submit(); expect(f.root.querySelector('a')).toBeNull()
})
it.each(['close', 'reopen', 'dispose'] as const)('ignores a late response after %s', async action => {
  const f = setup(); let resolve!: (value: NativeWordFileResult) => void
  f.api.newWord.mockImplementation(() => new Promise(done => { resolve = done })); f.control.open('new'); void f.submit()
  if (action === 'dispose') f.control.dispose()
  else { f.root.querySelector<HTMLButtonElement>('[data-action=cancel]')!.click(); if (action === 'reopen') f.control.open('save-as') }
  resolve(result()); await settle(); expect(f.root.querySelector('a')).toBeNull(); expect(f.navigate).not.toHaveBeenCalled(); expect(f.onError).not.toHaveBeenCalled()
})
it('rejects a Save As result if the current draft becomes dirty while the request is in flight', async () => {
  const f = setup(); let resolve!: (value: NativeWordFileResult) => void
  f.api.saveWordAs.mockImplementation(() => new Promise(done => { resolve = done })); f.control.open('save-as'); void f.submit(); f.setDirty(true); resolve(result()); await settle()
  expect(f.root.querySelector('a')).toBeNull(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('保存')
})
it('checks host blocking and validates filenames before issuing a request', async () => {
  const f = setup(); f.setBlocked('正在保存'); expect(f.control.reason('new')).toBe('正在保存'); f.control.open('new'); expect(f.api.newWord).not.toHaveBeenCalled()
  f.setBlocked(null); f.control.open('new'); f.root.querySelector<HTMLInputElement>('input')!.value = '../outside.docx'; await f.submit(); expect(f.api.newWord).not.toHaveBeenCalled()
})

it('accepts a 160-character filename and rejects 161 characters before requesting creation', async () => {
  const f = setup(); f.control.open('new')
  const input = f.root.querySelector<HTMLInputElement>('input')!
  expect(input.maxLength).toBe(160)
  input.value = '名'.repeat(156) + '.docx'; await f.submit()
  expect(f.api.newWord).not.toHaveBeenCalled(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('160')
  input.value = '名'.repeat(155) + '.docx'; await f.submit()
  expect(f.api.newWord).toHaveBeenCalledWith(expect.objectContaining({ filename: '名'.repeat(155) + '.docx' }))
})

it('counts Unicode filename characters like the backend and includes an appended extension in the limit', async () => {
  const f = setup(); f.control.open('new')
  const input = f.root.querySelector<HTMLInputElement>('input')!
  input.value = '😀'.repeat(156); await f.submit(); expect(f.api.newWord).not.toHaveBeenCalled()
  input.value = '😀'.repeat(155); await f.submit()
  expect(f.api.newWord).toHaveBeenCalledWith(expect.objectContaining({ filename: '😀'.repeat(155) + '.docx' }))
})

it.each(['name:copy.docx', 'name*copy.docx', 'name?copy.docx', 'name"copy.docx', 'name<copy.docx', 'name>copy.docx', 'name|copy.docx', '.hidden.docx', '.docx'])('rejects the backend-invalid filename %s before sending', async filename => {
  const f = setup(); f.control.open('new'); f.root.querySelector<HTMLInputElement>('input')!.value = filename; await f.submit()
  expect(f.api.newWord).not.toHaveBeenCalled(); expect(f.root.querySelector('[role=alert]')!.textContent).toContain('有效文件名')
})
