import { expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'

it.each([true, false])('selects the loaded document from the source Home button with editable=%s', editable => {
  const element = document.createElement('div')
  document.body.append(element)
  const editor = new Editor({
    element,
    editable,
    extensions: editorExtensions,
    editorProps: { handleScrollToSelection: () => true },
    content: { type: 'doc', content: [
      { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'First' }] },
      { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: 'Second' }] },
    ] },
  })
  const ribbon = createDocxRibbon(editor, editable)
  document.body.append(ribbon)
  try {
    const baseline = editor.getJSON()
    const button = ribbon.querySelector<HTMLButtonElement>('[data-action="select"]')!
    expect(button).not.toBeNull()
    expect(button.disabled).toBe(false)
    expect(button.textContent).toContain('全选')
    button.click()
    expect(editor.state.selection.from).toBe(0)
    expect(editor.state.selection.to).toBe(editor.state.doc.content.size)
    expect(editor.getJSON()).toEqual(baseline)
  } finally {
    editor.destroy()
    ribbon.remove()
    element.remove()
  }
})
