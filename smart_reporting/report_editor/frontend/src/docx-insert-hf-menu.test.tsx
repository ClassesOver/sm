import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Editor } from '@tiptap/core'
import { PAGE_MARK, TOTAL_PAGES_MARK } from '@genoffice/docx-engine'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { DocxInsertSource } from './docx-insert-source'
import type { DocxHeaderFooterController, DocxPreparedHfEdges } from './docx-hf-source'

const cleanups: (() => void)[] = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.replaceChildren() })
function setup(editable = true) {
  const editor = new Editor({ extensions: editorExtensions, editable, editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'Body' }] }] } })
  const controller = (sectionId: string): DocxHeaderFooterController => ({ editable, anchor: { sectionId, expectedSectionSha256: 'sha' },
    model: { titlePg: true, evenAndOddHeaders: true, pageNumberFmt: null, pageNumberStart: null, parts: {} },
    valueOf: () => ({ value: { text: `before${PAGE_MARK}${TOTAL_PAGES_MARK}after`, pageNumber: true }, anchor: { rId: 'rId1', expectedPartSha256: 'part-sha', text: '', hasPageNumber: true, editable } }), onCommit: vi.fn() })
  const header = controller('first'), footer = controller('last')
  const assertCurrent = vi.fn(), edit = vi.fn()
  const edges: DocxPreparedHfEdges = { header: { controller: header, part: 'header', variant: 'first' }, footer: { controller: footer, part: 'footer', variant: 'even' }, assertCurrent }
  const prepare = vi.fn(async () => edges)
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host)
  flushSync(() => root.render(<DocxInsertSource editor={editor} editable={editable} headerFooter={{ prepare, edit }} />))
  cleanups.push(() => { flushSync(() => root.unmount()); editor.destroy(); host.remove() })
  const click = (button: HTMLButtonElement) => flushSync(() => button.click())
  const trigger = (kind: string) => host.querySelector<HTMLButtonElement>(`[data-action="insert-${kind}"]`)!
  const open = async (kind: string) => { click(trigger(kind)); await vi.waitFor(() => expect(host.querySelector('[data-rb-panel] [role="status"]')).toBeNull()) }
  const item = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('[data-rb-panel] button')].find(button => button.textContent === label)!
  return { host, header, footer, prepare, edit, edges, assertCurrent, click, trigger, open, item }
}

it.each((['header', 'footer'] as const).flatMap(part => (['left', 'center', 'right'] as const).map(align => [part, align] as const)))('applies source %s/%s page-number gallery to its captured part and variant', async (part, align) => {
  const current = setup(); await current.open('page-number')
  current.click(current.host.querySelector<HTMLButtonElement>(`[data-source-action="insert-page-number-${part}-${align}"]`)!)
  expect(current[part].onCommit).toHaveBeenCalledExactlyOnceWith(part, part === 'header' ? 'first' : 'even', { text: PAGE_MARK, pageNumber: true, paras: [{ align, runs: [{ text: PAGE_MARK }] }] })
  expect(current[part === 'header' ? 'footer' : 'header'].onCommit).not.toHaveBeenCalled()
  expect(current.host.querySelector('[data-rb-panel]')).toBeNull()
})

it.each(['header', 'footer'] as const)('deletes source %s by committing empty content to the captured target', async part => {
  const current = setup(); await current.open(part); current.click(current.item(part === 'header' ? '删除页眉' : '删除页脚'))
  expect(current[part].onCommit).toHaveBeenCalledExactlyOnceWith(part, part === 'header' ? 'first' : 'even', { text: '' })
})

it('removes source PAGE while preserving NUMPAGES and surrounding text in both captured edge parts', async () => {
  const current = setup(); await current.open('page-number'); current.click(current.item('移除页码'))
  for (const part of ['header', 'footer'] as const) expect(current[part].onCommit).toHaveBeenCalledExactlyOnceWith(part, part === 'header' ? 'first' : 'even', { text: `before${TOTAL_PAGES_MARK}after`, pageNumber: false })
})

it('refuses a menu action after its measured document identity becomes stale', async () => {
  const current = setup(); await current.open('footer')
  current.assertCurrent.mockImplementation(() => { throw new Error('stale captured target') })
  current.click(current.item('删除页脚'))
  expect(current.footer.onCommit).not.toHaveBeenCalled()
  expect(current.host.querySelector('[role="alert"]')!.textContent).toContain('stale captured target')
})

it('ignores an old asynchronous preparation after the same menu was closed', async () => {
  const current = setup(); let resolve!: (value: DocxPreparedHfEdges) => void
  current.prepare.mockImplementationOnce(() => new Promise<DocxPreparedHfEdges>(done => { resolve = done }))
  current.click(current.trigger('footer')); expect(current.host.querySelector('[role="status"]')).not.toBeNull()
  current.click(current.trigger('footer')); await resolve(current.edges)
  await Promise.resolve()
  expect(current.host.querySelector('[data-rb-panel]')).toBeNull()
  expect(current.footer.onCommit).not.toHaveBeenCalled()
})

it('keeps all source modification menus disabled for a read-only document', () => {
  const current = setup(false)
  for (const kind of ['header', 'footer', 'page-number']) { expect(current.trigger(kind).disabled).toBe(true); current.click(current.trigger(kind)) }
  expect(current.prepare).not.toHaveBeenCalled()
})
