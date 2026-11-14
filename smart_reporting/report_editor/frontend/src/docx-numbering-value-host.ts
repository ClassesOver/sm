import type { Editor } from '@tiptap/core'
import type { DocxAnchor } from './docx-operations'
import { docxNumberingValueTarget, setDocxNumberingValue } from './docx-custom-list'

/** 将编号值对话框生命周期保留在列表模块，避免主编辑块继续增长。 */
export function createDocxNumberingValueControl(editor: Editor, editable: boolean, anchors: DocxAnchor[], report: (error: unknown) => void) {
  let close: (() => void) | undefined, token = 0, destroyed = false
  const reason = () => {
    try {
      if (!editable || !editor.isEditable) return '当前文档不可编辑'
      docxNumberingValueTarget(editor, anchors); return null
    } catch (error) { return error instanceof Error ? error.message : String(error) }
  }
  const open = async () => {
    close?.()
    const current = ++token, doc = editor.state.doc, selection = editor.state.selection
    const check = () => {
      if (destroyed || editor.isDestroyed || current !== token || editor.state.doc !== doc || !editor.state.selection.eq(selection)) throw new Error('编号值选区或来源已变化，请重新打开')
      const unavailable = reason(); if (unavailable) throw new Error(unavailable)
    }
    try {
      check()
      const target = docxNumberingValueTarget(editor, anchors)
      const { openDocxNumberingValueDialog } = await import('./docx-numbering-value-control')
      if (destroyed || editor.isDestroyed || current !== token) return
      check()
      close = openDocxNumberingValueDialog(target, (mode, value) => { check(); setDocxNumberingValue(editor, anchors, { mode, value }) }, report)
    } catch (error) { if (!destroyed) report(error) }
  }
  return { reason, open, destroy() { destroyed = true; token++; close?.() } }
}
