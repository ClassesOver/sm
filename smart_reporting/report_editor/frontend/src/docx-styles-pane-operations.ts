import { Extension, type Editor } from '@tiptap/core'
import { EditorState, Selection } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import type { Schema } from '@tiptap/pm/model'
import type { StyleInfo, StyleUpsert } from '@genoffice/docx-engine'
import type { DocxPmNode, DocxAnchor } from './docx-operations'
import type { NativeOperation } from './native-draft'
import { shedMajorityDirectFormatting } from './docx-style-majority'
import { docxNativeOperationsOf } from './docx-native-history'
import { stylesPaneCatalog, validateStylesPaneUpserts } from '../../../reporting/doc_engine/bridge/docx-styles-pane'

export type StylesPaneAction = { type: 'paragraph'; styleId: string } | { type: 'character'; styleId: string | null; from: number; to: number }
export interface StylesPaneModel { expectedStylesSha256: string; editable: boolean }
export const NativeStylesPane = Extension.create({ name: 'nativeStylesPane', addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading', 'docListItem'], attributes: { nativeStylesPane: { default: null, rendered: false } } }] })

export function stylesPaneOperations(operations: NativeOperation[], source: ReadonlyMap<string, StyleInfo>, model?: StylesPaneModel): NativeOperation[] {
  const values = operations.filter(op => op.kind === 'upsertStyle')
  for (const op of values) if (!model?.editable || op.expectedStylesSha256 !== model.expectedStylesSha256 || Object.keys(op).some(key => !['kind','expectedStylesSha256','upsert'].includes(key))) throw new Error('样式定义来源身份无效')
  return validateStylesPaneUpserts(values.map(op => op.upsert), source).map(upsert => ({ kind: 'upsertStyle', expectedStylesSha256: model!.expectedStylesSha256, upsert }))
}
export function stylesPaneStyles(source: ReadonlyMap<string, StyleInfo>, operations: NativeOperation[]) {
  return stylesPaneCatalog(source, operations.filter(op => op.kind === 'upsertStyle').map(op => op.upsert as StyleUpsert))
}
export function projectStylesPaneActions(source: DocxPmNode, actions: StylesPaneAction[], styles: ReadonlyMap<string, StyleInfo>, schema: Schema): DocxPmNode {
  if (!['docParagraph','docHeading','docListItem'].includes(source.type) || (source.content ?? []).some(node => node.type !== 'text') || !Array.isArray(actions) || !actions.length || actions.length > 100) throw new Error('此来源段落暂不支持样式窗格')
  const doc = schema.nodeFromJSON({ type: 'doc', content: [source] }), tr = EditorState.create({ schema, doc }).tr
  for (const action of actions) {
    const style = styles.get(action.styleId ?? '')
    if (!['paragraph','character'].includes(action.type) || action.styleId !== null && (!style || style.type !== action.type || style.linkedCharShell)) throw new Error('样式类型或来源无效')
    if (action.type === 'paragraph') {
      if (!style || Object.keys(action).some(key => !['type','styleId'].includes(key))) throw new Error('段落样式意图无效')
      const node = tr.doc.firstChild!, level = style.headingLevel
      const type = level ? schema.nodes.docHeading! : node.type.name === 'docHeading' ? schema.nodes.docParagraph! : node.type
      tr.setNodeMarkup(0, type, { ...node.attrs, styleId: action.styleId, ...(level ? { level, outlineOnly: null } : {}) })
      shedMajorityDirectFormatting(tr, 0)
    } else {
      const { from, to } = action, text = tr.doc.firstChild!.textContent
      if (Object.keys(action).some(key => !['type','styleId','from','to'].includes(key)) || !Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to <= from || to > text.length || /[\uDC00-\uDFFF]/.test(text[from] ?? '') || /[\uDC00-\uDFFF]/.test(text[to] ?? '')) throw new Error('字符样式范围无效')
      const mark = schema.marks.docTextStyle!
      if (action.styleId === null) tr.removeMark(from + 1, to + 1, mark)
      else {
        const node = tr.doc.firstChild!
        node.forEach((run, offset) => {
          const start = Math.max(from, offset), end = Math.min(to, offset + run.nodeSize)
          if (start < end) tr.addMark(start + 1, end + 1, mark.create({ ...run.marks.find(item => item.type === mark)?.attrs, styleId: action.styleId }))
        })
      }
    }
  }
  const result = tr.doc.firstChild!.toJSON() as DocxPmNode
  result.attrs = { ...result.attrs, nativeStylesPane: actions }
  return schema.nodeFromJSON(result).toJSON() as DocxPmNode
}
export function normalizeStylesPane(baseline: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[], styles: ReadonlyMap<string, StyleInfo>, schema: Schema) {
  const value = structuredClone(current), operations: NativeOperation[] = []
  for (let index = 0; index < (value.content ?? []).length; index++) {
    const node = value.content![index]!, actions = node.attrs?.nativeStylesPane as StylesPaneAction[] | undefined
    if (!actions) continue
    const anchor = anchors.find(item => item.docxIndex === node.attrs?.docxIndex), old = baseline.content?.find(item => item.attrs?.docxIndex === node.attrs?.docxIndex)
    if (!old || !anchor?.editable || anchor.fontDialogEditable === false || value.content!.filter(item => item.attrs?.docxIndex === node.attrs?.docxIndex).length !== 1) throw new Error('样式窗格来源已变化或不可编辑')
    if (JSON.stringify(schema.nodeFromJSON(node).toJSON()) !== JSON.stringify(projectStylesPaneActions(old, actions, styles, schema))) throw new Error('样式应用与同段其他修改请分开保存')
    value.content![index] = structuredClone(old)
    operations.push({ kind: 'applyDocumentStyle', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, actions })
  }
  return { current: value, operations }
}
export function stylesPaneSelectionEditable(editor: Editor, anchors: DocxAnchor[]): boolean {
  let found = false, supported = true
  const { from, to } = editor.state.selection
  editor.state.doc.nodesBetween(from, to, (node, _pos, parent) => {
    if (parent !== editor.state.doc) return false
    found = true
    const matches = anchors.filter(item => item.docxIndex === node.attrs.docxIndex)
    if (matches.length !== 1 || !matches[0]!.editable || matches[0]!.fontDialogEditable === false
      || !['docParagraph','docHeading','docListItem'].includes(node.type.name) || node.content.content.some(child => !child.isText)
      || editor.state.doc.content.content.filter(item => item.attrs.docxIndex === node.attrs.docxIndex).length !== 1) supported = false
    return false
  })
  return found && supported
}
export function applyStylesPaneAction(editor: Editor, styleId: string, type: 'paragraph' | 'character', anchors: DocxAnchor[], source: ReadonlyMap<string, StyleInfo>, toggle = false) {
  if (!editor.isEditable) return
  const styles = stylesPaneStyles(source, docxNativeOperationsOf(editor.getJSON()))
  const info = styles.get(styleId)
  if (!info || info.type !== type || info.linkedCharShell) throw new Error('样式类型或来源无效')
  if (!stylesPaneSelectionEditable(editor, anchors)) throw new Error('请选择可信的正文、标题或列表文字')
  const { from, to, empty } = editor.state.selection
  if (type === 'character' && empty) {
    if (toggle) editor.chain().focus().unsetMark('docTextStyle').run()
    else editor.chain().focus().setMark('docTextStyle', { styleId }).run()
    return
  }
  const targets: { pos: number; node: import('@tiptap/pm/model').Node; action: StylesPaneAction }[] = []
  let unsupported = false
  editor.state.doc.nodesBetween(from, to, (node, pos, parent) => {
    if (parent !== editor.state.doc) { unsupported = true; return false }
    const anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex)
    if (!anchor?.editable || anchor.fontDialogEditable === false || !['docParagraph','docHeading','docListItem'].includes(node.type.name) || node.content.content.some(child => !child.isText)) { unsupported = true; return false }
    const action: StylesPaneAction = type === 'paragraph' ? { type, styleId } : { type, styleId: toggle ? null : styleId, from: Math.max(0, from-pos-1), to: Math.min(node.content.size, to-pos-1) }
    if (action.type === 'paragraph' || action.to > action.from) targets.push({ pos,node,action })
    return false
  })
  if (unsupported || !targets.length) throw new Error('请选择可信的正文、标题或列表文字')
  const tr = closeHistory(editor.state.tr)
  for (const { pos,node,action } of targets) {
    const projected = projectStylesPaneActions(node.toJSON(), [action], styles, editor.schema)
    projected.attrs!.nativeStylesPane = [...(node.attrs.nativeStylesPane ?? []), action]
    tr.replaceWith(pos, pos + node.nodeSize, editor.schema.nodeFromJSON(projected))
  }
  tr.setSelection(Selection.fromJSON(tr.doc, editor.state.selection.toJSON()))
  editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); editor.view.focus()
}
