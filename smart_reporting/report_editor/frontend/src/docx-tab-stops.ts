import { Extension, type Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { docxOperations, type DocxPmNode } from './docx-operations'
import { normalizeDocxTabStops } from '../../../reporting/doc_engine/bridge/docx-tab-stops'
export { normalizeDocxTabStops }
export interface DocxTabStopsAnchor {
  blockId: string
  expectedObjectSha256: string
  editable: boolean
  tabStopsEditable?: boolean
  tabStopsReadOnlyReason?: string | null
}
export const NativeDocxTabStops = Extension.create({
  name: 'nativeDocxTabStops',
  addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading'], attributes: { nativeTabStops: { default: null, rendered: false } } }],
})
export function projectDocxTabStops(source: DocxPmNode, anchor: DocxTabStopsAnchor, value: unknown): DocxPmNode {
  if (!anchor.editable || anchor.tabStopsEditable !== true || !['docParagraph','docHeading'].includes(source.type)
    || source.attrs?.bidi || source.attrs?.bidiInherited || source.attrs?.bidiInferred) throw new Error(anchor.tabStopsReadOnlyReason ?? '此来源段落暂不支持制表位编辑')
  const stops = normalizeDocxTabStops(value), result = structuredClone(source)
  result.attrs = { ...result.attrs, nativeTabStops: stops, tabStops: stops.length ? JSON.stringify(stops) : null }
  return result
}
const withoutIntent = (node: DocxPmNode) => {
  const result = structuredClone(node)
  if (result.attrs) delete result.attrs.nativeTabStops
  return result
}
export function docxTabStopsOperation(source: DocxPmNode, edited: DocxPmNode, anchor: DocxTabStopsAnchor) {
  const stops = normalizeDocxTabStops(edited.attrs?.nativeTabStops)
  const projected = projectDocxTabStops(source, anchor, stops)
  if (JSON.stringify(withoutIntent(projected)) !== JSON.stringify(withoutIntent(edited))) throw new Error('制表位不能与同段正文或其它格式混改，请先保存')
  if ((source.attrs?.tabStops ?? null) === (edited.attrs?.tabStops ?? null)) return null
  return { kind: 'setParagraphTabStops', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, stops }
}
export function replayDocxTabStops(source: DocxPmNode, anchor: DocxTabStopsAnchor, operation: Record<string, unknown>) {
  if (operation.kind !== 'setParagraphTabStops' || operation.blockId !== anchor.blockId || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
    || Object.keys(operation).some(key => !['kind','blockId','expectedObjectSha256','stops'].includes(key))) throw new Error('草稿制表位字段或来源身份无效')
  return projectDocxTabStops(source, anchor, operation.stops)
}
export function applyDocxTabStops(editor: Editor, anchors: Array<DocxTabStopsAnchor & { docxIndex: number }>, stops: unknown) {
  const { $from, $to } = editor.state.selection
  if (!editor.isEditable || $from.depth !== 1 || $to.depth !== 1 || !$from.sameParent($to)) throw new Error('请选择同一可编辑原有段落')
  const matches = anchors.filter(anchor => anchor.docxIndex === $from.parent.attrs.docxIndex)
  if (matches.length !== 1) throw new Error('制表位来源锚点不唯一')
  const projected = projectDocxTabStops($from.parent.toJSON(), matches[0]!, stops), before = editor.state.doc
  const tr = closeHistory(editor.state.tr).setNodeMarkup($from.before(1), undefined, projected.attrs)
  if (tr.doc.eq(before)) return
  docxOperations(before.toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('制表位与现有编辑不兼容，请先保存')
  editor.view.dispatch(closeHistory(editor.state.tr))
}
