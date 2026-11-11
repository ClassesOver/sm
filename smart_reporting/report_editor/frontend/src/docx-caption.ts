import { Extension, type Editor } from '@tiptap/core'
import { type Schema } from '@tiptap/pm/model'
import { closeHistory } from '@tiptap/pm/history'
import type { parseDocx } from '@genoffice/docx-engine'
import { docxCaptionNumber, docxCaptionPlan, docxCaptionXml, isDocxCaptionOperation, readDocxCaptionOperation, type CaptionLabel, type CaptionOperation } from '../../../reporting/doc_engine/bridge/docx-caption-core'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { NativeOperation } from './native-draft'
export { isDocxCaptionOperation }
export type { CaptionLabel }
export const NativeDocxCaption = Extension.create({
  name: 'nativeDocxCaption',
  addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeCaptionOperation: { default: null, rendered: false } } }],
})
const batchError = '题注需要单独保存。请先保存当前修改，再插入题注。'
export function assertDocxCaptionBatch(operations: readonly NativeOperation[]) {
  if (operations.some(isDocxCaptionOperation) && operations.length !== 1) throw new Error(batchError)
}
export type DocxCaptionControls = { reason: (label: CaptionLabel, text: string) => string | null; preview: (label: CaptionLabel, text: string) => { number: number; display: string }; run: (label: CaptionLabel, text: string) => void }
type CaptionAnchor = Pick<DocxAnchor, 'docxIndex' | 'blockId' | 'expectedObjectSha256'>
export function createDocxCaption(parsed: Awaited<ReturnType<typeof parseDocx>>, anchors: readonly CaptionAnchor[]) {
  const byId = new Map(anchors.map(anchor => [anchor.blockId, anchor])), byIndex = new Map(anchors.map(anchor => [anchor.docxIndex, anchor]))
  const blocks = new Map(parsed.blocks.map(block => [block.docxIndex, block]))
  const plan = (doc: DocxPmNode, value: unknown, schema: Schema) => {
    const operation = readDocxCaptionOperation(value), source = docxCaptionPlan(parsed, operation)
    const anchor = byId.get(operation.blockId)
    if (!anchor || anchor.expectedObjectSha256 !== operation.expectedObjectSha256) throw new Error('题注锚点不属于当前 Word 文件。')
    const block = blocks.get(anchor.docxIndex), paragraph = source.paragraphs.get(anchor.docxIndex)
    if (!paragraph || !block || !['heading', 'paragraph', 'listItem'].includes(block.type)
      || operation.position === 'after' && /<w:sectPr\b/.test(block.originalXml ?? '')) throw new Error('请选择普通正文或标题段落作为题注插入位置。')
    const index = (doc.content ?? []).findIndex(node => node.attrs?.docxIndex === anchor.docxIndex)
    if (index < 0) throw new Error('题注锚点已变化。')
    const at = operation.position === 'before' ? paragraph.start : paragraph.end
    let number: number
    try { number = docxCaptionNumber(source.xml, operation.label, at) } catch { throw new Error('请在该标签最后一个题注之后插入；已有序号必须是从 1 开始连续且未重置的简单 SEQ 域。') }
    const display = operation.label + ' ' + number + (operation.text ? ' ' + operation.text : '')
    const node = schema.nodeFromJSON({type: 'docProtected', attrs: {docxIndex: null, blockType: 'passthrough', label: '题注', genXml: docxCaptionXml(operation.label, number, operation.text), fieldDisplay: {kind: 'text', left: display}}})
    return {operation, index: index + (operation.position === 'after' ? 1 : 0), node, number, display}
  }
  const controls = (editor: Editor, pending: () => readonly NativeOperation[], reportError: (error: unknown) => void): DocxCaptionControls => {
    const intent = (label: CaptionLabel, text: string) => {
      if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存。')
      if (pending().length) throw new Error(batchError)
      const {empty, $from} = editor.state.selection
      if (!empty || $from.depth !== 1 || ($from.parentOffset !== 0 && $from.parentOffset !== $from.parent.content.size)) throw new Error('请把光标放在正文或标题段落的开头或结尾。')
      const anchor = byIndex.get($from.parent.attrs.docxIndex)
      if (!anchor) throw new Error('请选择普通正文或标题段落作为题注插入位置。')
      const value: CaptionOperation = {kind: 'insertCaption', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, position: $from.parentOffset === 0 ? 'before' : 'after', label, text: text.trim()}
      return plan(editor.getJSON(), value, editor.schema)
    }
    return {
      reason(label, text) { try { intent(label, text); return null } catch (error) { return (error as Error).message } },
      preview(label, text) { const {number, display} = intent(label, text); return {number, display} },
      run(label, text) {
        try {
          const {operation, index, node} = intent(label, text), {doc, tr} = editor.state
          let at = 0
          doc.forEach((child, _offset, i) => { if (i < index) at += child.nodeSize })
          editor.view.dispatch(closeHistory(tr.insert(at, node).setDocAttribute('nativeCaptionOperation', operation)))
          editor.view.focus()
        } catch (error) { reportError(error) }
      },
    }
  }
  return {plan, controls}
}
type DocxCaption = ReturnType<typeof createDocxCaption>
/** Remove only the exact server-derived projection, then let ordinary collectors check all other changes. */
export function normalizeDocxCaption(baseline: DocxPmNode, current: DocxPmNode, source: DocxCaption, schema: Schema) {
  const value = current.attrs?.nativeCaptionOperation
  if (value == null) return {current, operations: [] as NativeOperation[]}
  const {operation, index, node} = source.plan(baseline, value, schema), body = current.content ?? []
  if (JSON.stringify(body[index]) !== JSON.stringify(node.toJSON())) throw new Error('题注结构已变化，请撤销后重新操作。')
  return {current: {...current, attrs: {...current.attrs, nativeCaptionOperation: baseline.attrs?.nativeCaptionOperation ?? null}, content: [...body.slice(0, index), ...body.slice(index + 1)]}, operations: [operation]}
}
export function replayDocxCaption(doc: DocxPmNode, operations: NativeOperation[], source: DocxCaption, schema: Schema): DocxPmNode {
  assertDocxCaptionBatch(operations)
  const value = operations.find(isDocxCaptionOperation)
  if (!value) return doc
  const {operation, index, node} = source.plan(doc, value, schema), body = doc.content ?? []
  return {...doc, attrs: {...doc.attrs, nativeCaptionOperation: operation}, content: [...body.slice(0, index), node.toJSON(), ...body.slice(index)]}
}
