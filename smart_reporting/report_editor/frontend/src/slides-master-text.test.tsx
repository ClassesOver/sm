import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSlidesEditorView } from './slides-main'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
vi.mock('./vendor/genoffice/renderer/SlideThumb', () => ({ SlideThumb: () => <figure data-source-master-thumbnail /> }))
beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} }) })
const views: ReturnType<typeof createSlidesEditorView>[] = []
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.unstubAllGlobals() })
async function fixture() {
  const masterTextParts = ['master', 'layout'].map((kind, index) => ({ kind, partPath: `ppt/${index ? 'slideLayouts/slideLayout' : 'slideMasters/slideMaster'}1.xml`, name: kind, elements: [{ spid: 7, name: '正文', text: `${kind}来源`, paragraphs: [{ srcPara: 0, runs: [{ srcRun: 0, text: `${kind}来源`, bold: true, italic: false, underline: false, strike: false }] }], editable: true, reason: null }] }))
  const deck = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, masterTextParts,
    slides: [{ slideIndex: 0, elements: [], animations: [] }] }
  const tree = { slides: [{ slideIndex: 0, widthPx: 960, heightPx: 540, nodes: [] }], masterTextParts: masterTextParts.map(part => ({ ...part, slide: { widthPx: 960, heightPx: 540, nodes: [] } })) }
  const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx')
  const draft = new NativeDraft({ documentId: 'master-text', revision: 1, sourceSha256: deck.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} })
  const request = vi.fn(async (path: string) => path === 'deck' ? deck : tree)
  const view = createSlidesEditorView(shell.editor, { native: true, draft, request: request as never, save: shell.save, download: shell.exportPptx }); views.push(view); await view.ready
  const open = async () => {
    shell.editor.querySelector<HTMLButtonElement>('[data-command=slideMaster]')!.click()
    await vi.waitFor(() => expect(shell.editor.querySelector('.slides-master-text-dialog[open]'), shell.editor.textContent).not.toBeNull())
    return shell.editor.querySelector<HTMLDialogElement>('.slides-master-text-dialog')!
  }
  return { shell, draft, request, view, open, deck }
}
it('母版入口接实际onSlideMaster，选部件文字后采纳进入同一草稿预览和撤销重做', async () => {
  const app = await fixture(), button = app.shell.editor.querySelector<HTMLButtonElement>('[data-command=slideMaster]')!
  expect(button.disabled).toBe(false); expect(button.dataset.sourceAction).toBe('onSlideMaster')
  const dialog = await app.open()
  expect(app.draft.operations).toEqual([])
  expect(dialog.querySelectorAll('[data-master-part]')).toHaveLength(2)
  dialog.querySelector<HTMLButtonElement>('[data-master-part="ppt/slideLayouts/slideLayout1.xml"]')!.click()
  const input = dialog.querySelector<HTMLElement>('[data-master-rich-text]')!; expect(input.textContent).toBe('layout来源')
  input.innerHTML = '<div data-src-para="0"><span data-src-run="0" style="font-weight:700">版式新文字 &lt;&amp;&gt; 😀</span></div>'; input.dispatchEvent(new Event('input', { bubbles: true }))
  dialog.querySelector<HTMLButtonElement>('[data-master-apply]')!.click()
  expect(dialog.textContent).not.toContain('来源或草稿已变化')
  expect(app.draft.operations, dialog.querySelector('[data-master-status]')?.textContent).toMatchObject([{ masterTextEdits: [{ partPath: 'ppt/slideLayouts/slideLayout1.xml', spid: 7, paragraphs: [{ srcPara: 0, runs: [{ srcRun: 0, text: '版式新文字 <&> 😀', bold: true }] }] }] }])
  await vi.waitFor(() => expect(app.request).toHaveBeenCalledWith('render-tree', expect.objectContaining({ body: expect.stringContaining('masterTextEdits') })))
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onUndo]')!.click(); expect(app.draft.operations).toEqual([])
  app.shell.editor.querySelector<HTMLButtonElement>('[data-source-action=onRedo]')!.click(); expect(app.draft.operations[0]).toHaveProperty('masterTextEdits')
})
it('母版纯文字改写明确源run语义，IME拒绝采纳，同值不制造修改，旧对话框不会覆盖新草稿', async () => {
  const app = await fixture(), dialog = await app.open(), input = dialog.querySelector<HTMLElement>('[data-master-rich-text]')!
  expect(dialog.textContent).toContain('run'); expect(dialog.textContent).toContain('动态字段')
  dialog.querySelector<HTMLButtonElement>('[data-master-apply]')!.click(); expect(app.draft.operations).toEqual([])
  const again = await app.open(), text = again.querySelector<HTMLElement>('[data-master-rich-text]')!, apply = again.querySelector<HTMLButtonElement>('[data-master-apply]')!
  text.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })); text.textContent = '输入中'; text.dispatchEvent(new Event('input', { bubbles: true })); apply.click(); expect(app.draft.operations).toEqual([])
  text.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true })); app.draft.setOperations([{ kind: 'editSlides', edits: [] }]); apply.click()
  expect(app.draft.operations).toEqual([{ kind: 'editSlides', edits: [] }]); expect(again.textContent).toContain('草稿已变化')
})
