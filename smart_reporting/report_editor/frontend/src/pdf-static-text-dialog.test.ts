import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { bindPdfStaticText } from './pdf-static-text'

const controllers: ReturnType<typeof bindPdfStaticText>[] = []
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false } })
})
afterEach(() => { controllers.splice(0).forEach(controller => controller.dispose()); document.body.replaceChildren(); vi.restoreAllMocks() })
function fixture() {
  const root = document.body.appendChild(document.createElement('div')), input = root.appendChild(document.createElement('input'))
  const sha = 'a'.repeat(64), pageId = `sha256:${sha}:page:0`
  const draft = new NativeDraft({ documentId: 'static-text-keyboard', revision: 1, sourceSha256: sha, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  let active = false
  const controller = bindPdfStaticText({ root, draft, pages: () => [{ pageId, index: 0, rotation: 0, cropBox: { x: 10, y: 20, width: 300, height: 400 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 } }], unavailable: () => null,
    start: () => { active = true }, stop: () => { active = false }, refresh: async () => {}, status() {} })
  controllers.push(controller)
  controller.open(); root.querySelector<HTMLTextAreaElement>('textarea')!.value = '测试文字'
  root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click(); input.focus()
  return { root, input, controller, draft, pageId, active: () => active }
}
it.each(['consumed', 'composition', '229'])('插入落点等待保留%s输入拥有的Escape', async reason => {
  const f = fixture()
  if (reason === 'consumed') f.input.addEventListener('keydown', event => event.preventDefault())
  f.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: reason === 'composition', keyCode: reason === '229' ? 229 : 27 }))
  expect(f.active()).toBe(true); expect(f.controller.incompleteReason()).toContain('落点')
  await f.controller.place(f.pageId, [75, 120])
  expect(f.draft.operations).toEqual([expect.objectContaining({ kind: 'insertText', origin: [75, 120], text: '测试文字' })])
})
it('普通Escape取消落点等待并不新增草稿', async () => {
  const f = fixture()
  f.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(f.active()).toBe(false); expect(f.controller.incompleteReason()).toBeNull()
  await f.controller.place(f.pageId, [75, 120]); expect(f.draft.operations).toEqual([])
})
