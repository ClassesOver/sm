import { expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import type { DocxHeaderFooterController } from './docx-hf-source'

it.each(['insert-header', 'insert-footer', 'insert-page-number'])('opens the source %s menu when a writable HF controller exists', async action => {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'Body' }] }] } })
  const controller: DocxHeaderFooterController = {
    editable: true,
    anchor: { sectionId: 'section0', expectedSectionSha256: 'source0' },
    model: { titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: {} },
    valueOf: () => null,
    onCommit: vi.fn(),
  }
  controller.prepareEdges = async () => ({ header: { controller, part: 'header', variant: 'default' }, footer: { controller, part: 'footer', variant: 'default' }, assertCurrent() {} })
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, [], undefined, undefined, undefined, undefined, controller)
  document.body.append(ribbon)
  try {
    ribbon.querySelector<HTMLButtonElement>('[data-tab-id="insert"]')!.click()
    const button = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
    expect(button).not.toBeNull()
    expect(button.disabled).toBe(false)
    button.click()
    await vi.waitFor(() => expect(ribbon.querySelector('[data-rb-panel]')).not.toBeNull())
    await vi.waitFor(() => expect(ribbon.querySelector('[data-rb-panel] [role="status"]')).toBeNull())
  } finally {
    editor.destroy()
    ribbon.remove()
  }
})
