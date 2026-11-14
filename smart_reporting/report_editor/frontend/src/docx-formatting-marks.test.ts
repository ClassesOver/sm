import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { FormattingMarksExtension, formattingMarksPluginKey, sectionBreakMap } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/formatting-marks'
import { createDocxFormattingMarks } from './docx-formatting-marks'

const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('toggles source formatting marks on screen without changing document or history', () => {
  const root = document.body.appendChild(document.createElement('div'))
  const editor = new Editor({ element: root, extensions: editorExtensions, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'A' }, { type: 'hardBreak', attrs: { pageBreak: true } }, { type: 'text', text: 'B' }] }] } })
  editors.push(editor)
  const marks = createDocxFormattingMarks({ editor, root, sections: [{ lastBlockIndex: 0, startType: 'nextPage' }, { lastBlockIndex: 1, startType: 'continuous' }] as never })
  const before = editor.getJSON(), html = editor.getHTML()
  expect(marks.visible).toBe(false)
  marks.toggle()
  expect(marks.visible).toBe(true)
  expect(root.classList.contains('show-marks')).toBe(true)
  expect(formattingMarksPluginKey.getState(editor.state)?.meta).toEqual({ on: true, breaks: sectionBreakMap([{ lastBlockIndex: 0, startType: 'nextPage' }, { lastBlockIndex: 1, startType: 'continuous' }] as never) })
  marks.toggle()
  expect(root.classList.contains('show-marks')).toBe(false)
  expect(editor.getJSON()).toEqual(before)
  expect(editor.getHTML()).toBe(html)
  marks.dispose()
})
