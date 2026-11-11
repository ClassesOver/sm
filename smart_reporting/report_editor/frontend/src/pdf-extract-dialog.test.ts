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
