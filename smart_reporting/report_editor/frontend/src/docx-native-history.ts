import { Extension, type Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import type { NativeOperation } from './native-draft'
import type { DocxPmNode } from './docx-operations'

/** 非正文编辑意图属于同一份 Word 文档，也须由原生事务历史撤销。 */
export const NativeDocxHistory = Extension.create({
  name: 'nativeDocxHistory',
  addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeDocxOperations: { default: null, rendered: false } } }],
})

export function docxNativeOperations(operations: NativeOperation[]): NativeOperation[] {
  return JSON.parse(JSON.stringify(operations.filter(operation => ['setSectionLayout', 'setHeaderFooter', 'setHeaderFooterLink', 'setPageColor', 'setWatermark'].includes(operation.kind))))
}

export function docxNativeOperationsOf(doc: DocxPmNode): NativeOperation[] {
  return docxNativeOperations((doc.attrs?.nativeDocxOperations ?? []) as NativeOperation[])
}

/** 恢复草稿时播种；须在用户开始编辑之前调用，不生成可撤销步骤。 */
export function seedDocxNativeOperations(editor: Editor, operations: NativeOperation[]): void {
  const values = docxNativeOperations(operations)
  editor.view.dispatch(editor.state.tr.setMeta('addToHistory', false).setDocAttribute('nativeDocxOperations', values.length ? values : null))
}

export function commitDocxNativeOperations(editor: Editor, operations: NativeOperation[], canEdit = () => editor.isEditable): boolean {
  if (!canEdit()) return false
  const values = docxNativeOperations(operations)
  if (JSON.stringify(docxNativeOperationsOf(editor.getJSON())) === JSON.stringify(values)) return false
  const previous = editor.state.doc
  editor.view.dispatch(closeHistory(editor.state.tr).setDocAttribute('nativeDocxOperations', values.length ? values : null))
  if (editor.state.doc === previous) return false
  // 前后均断开历史分组，避免紧邻正文输入吞并一次布局或部件编辑。
  editor.view.dispatch(closeHistory(editor.state.tr))
  return true
}
