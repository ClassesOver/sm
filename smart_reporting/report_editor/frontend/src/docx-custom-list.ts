import { Extension, type Editor } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import type { Node as PmNode } from '@tiptap/pm/model'
import { computeListValues, numberingLevelFromCustom, type NumberingDef } from '@genoffice/docx-engine'
import { normalizeDocxCustomList, customListLevel } from '../../../reporting/doc_engine/bridge/docx-custom-list'
import { normalizeDocxNumberingBinding, docxNumberingBindingId, docxDefaultNumberingLevels, type DocxNumberingBinding } from '../../../reporting/doc_engine/bridge/docx-numbering-value'
import { docxOperations, type DocxAnchor } from './docx-operations'

declare module '@tiptap/core' { interface Storage { nativeDocxCustomList: { sourceDoc: PmNode | null } } }

/** 覆盖层只由当前文档推导，Undo/Redo/恢复均与原生编辑历史一致。 */
export const NativeDocxCustomList = Extension.create({
  name: 'nativeDocxCustomList',
  priority: 1000,
  addStorage: () => ({ sourceDoc: null as PmNode | null }),
  addGlobalAttributes: () => [{ types: ['docParagraph', 'docHeading', 'docListItem'], attributes: { nativeListDefinition: { default: null, rendered: false }, nativeNumberingBinding: { default: null, rendered: false } } }],
  addProseMirrorPlugins() {
    const editor = this.editor
    const update = (doc: PmNode) => {
      const storage = (editor.storage as unknown as { listNumbering?: { defs: Map<string, NumberingDef> } }).listNumbering
      if (!storage?.defs) return
      const definitions = new Map([...storage.defs].filter(([id]) => !id.startsWith('native-custom-') && !id.startsWith('native-value-') && !id.startsWith('native-default-')))
      doc.descendants(node => {
        if (node.type.name !== 'docListItem') return
        const raw = node.attrs.nativeListDefinition ?? node.attrs.nativeNumberingBinding?.custom
        if (!raw) return
        const definition = normalizeDocxCustomList(raw)
        const list = customListLevel(definition, node.attrs.ilvl)
        definitions.set(list.numId, { numId: list.numId, abstractNumId: list.numId, startOverrides: {}, levels: Object.fromEntries(definition.levels.map((level, i) => [i, numberingLevelFromCustom(level)])) })
      })
      doc.descendants(node => {
        if (node.type.name !== 'docListItem' || !node.attrs.nativeNumberingBinding) return
        const binding = normalizeDocxNumberingBinding(node.attrs.nativeNumberingBinding)
        if (binding.defaultNumbering) {
          const { id, kind } = binding.defaultNumbering, numId = `native-default-${id}`
          definitions.set(numId, { numId, abstractNumId: numId, startOverrides: {}, levels: docxDefaultNumberingLevels(kind) })
        }
        const base = definitions.get(binding.sourceNumId ?? (binding.custom ? `native-custom-${binding.custom.id}` : `native-default-${binding.defaultNumbering!.id}`))
        if (!base) throw new Error('编号值来源定义缺失')
        const numId = docxNumberingBindingId(binding)
        definitions.set(numId, { ...base, numId, startOverrides: binding.startOverrides ?? base.startOverrides })
      })
      storage.defs = definitions
    }
    return [new Plugin({ state: {
      init: (_config, state) => { this.storage.sourceDoc ??= state.doc; update(state.doc); return null },
      apply(tr) { if (tr.docChanged) update(tr.doc); return null },
    } })]
  },
})

function selectedListParagraphs(editor: Editor, anchors: DocxAnchor[]) {
  if (!editor.isEditable || editor.isDestroyed) throw new Error('当前文档不可编辑或正在保存')
  const { from, to, $from, $to } = editor.state.selection
  if ($from.depth !== 1 || $to.depth !== 1) throw new Error('请选择原有顶层正文段落')
  const selected: { node: PmNode; pos: number }[] = []
  editor.state.doc.nodesBetween(from, to, (node, pos, parent) => {
    if (parent !== editor.state.doc) return false
    if (!['docParagraph', 'docHeading', 'docListItem'].includes(node.type.name)) throw new Error('选区包含暂不支持的对象')
    const matches = anchors.filter(anchor => anchor.docxIndex === node.attrs.docxIndex)
    if (node.attrs.docxIndex == null || matches.length !== 1 || !matches[0]!.editable) throw new Error('选区包含只读段落或来源身份缺失')
    selected.push({ node, pos }); return false
  })
  if (!selected.length) throw new Error('请选择原有顶层正文段落')
  return selected
}
export function docxCustomListReason(editor: Editor, anchors: DocxAnchor[]): string | null {
  try { selectedListParagraphs(editor, anchors); return null } catch (error) { return error instanceof Error ? error.message : String(error) }
}
/** 源 allocateListNumId：复用即使未被正文引用的同类原定义，每次新列表从1开始。 */
export function applyDocxHomeList(editor: Editor, anchors: DocxAnchor[], kind: 'bullet' | 'ordered') {
  const selected = selectedListParagraphs(editor, anchors)
  const existing = [...editor.storage.listNumbering.defs.values()].find(def => /^[1-9][0-9]*$/.test(def.numId)
    && (def.levels[0]?.numFmt === 'bullet') === (kind === 'bullet'))
  const id = crypto.randomUUID()
  const binding: DocxNumberingBinding = existing
    ? { id, sourceNumId: existing.numId, startOverrides: { 0: 1 } }
    : { id, defaultNumbering: { id, kind } }
  const before = editor.state.doc, tr = closeHistory(editor.state.tr)
  for (const { node, pos } of selected) tr.setNodeMarkup(pos, editor.schema.nodes.docListItem, {
    ...node.attrs, kind, numId: docxNumberingBindingId(binding), ilvl: 0, nativeListDefinition: null, nativeNumberingBinding: binding,
  })
  docxOperations(before.toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('列表与当前草稿不兼容，请先保存')
}

export function applyDocxCustomList(editor: Editor, anchors: DocxAnchor[], levels: unknown) {
  const selected = selectedListParagraphs(editor, anchors)
  const definition = normalizeDocxCustomList({ id: crypto.randomUUID(), levels })
  const before = editor.state.doc, tr = closeHistory(editor.state.tr)
  for (const { node, pos } of selected) {
    const ilvl = node.type.name === 'docListItem' ? Math.min(Number(node.attrs.ilvl) || 0, definition.levels.length - 1) : 0
    tr.setNodeMarkup(pos, editor.schema.nodes.docListItem, { ...node.attrs, ...customListLevel(definition, ilvl), nativeListDefinition: definition, nativeNumberingBinding: null })
  }
  docxOperations(before.toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('多级列表与当前修改不兼容，请先保存')
}
export function changeDocxCustomListLevel(editor: Editor, ilvl: number) {
  if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
  const { $from } = editor.state.selection, node = $from.parent
  if (node.type.name !== 'docListItem' || !node.attrs.nativeListDefinition || $from.depth !== 1) throw new Error('此段落不是待保存的多级列表')
  const definition = normalizeDocxCustomList(node.attrs.nativeListDefinition)
  editor.view.dispatch(editor.state.tr.setNodeMarkup($from.before(1), undefined, { ...node.attrs, ...customListLevel(definition, ilvl) }))
}

export function clearDocxCustomList(editor: Editor, anchors: DocxAnchor[]) {
  const selected = selectedListParagraphs(editor, anchors), before = editor.state.doc, tr = closeHistory(editor.state.tr)
  const source = editor.storage.nativeDocxCustomList.sourceDoc as PmNode | null
  for (const { node, pos } of selected) {
    if (node.type.name !== 'docListItem') continue
    let original: PmNode | undefined
    source?.forEach(child => { if (child.attrs.docxIndex === node.attrs.docxIndex) original = child })
    const restoreHeading = !!(node.attrs.nativeListDefinition || node.attrs.nativeNumberingBinding) && original?.type.name === 'docHeading'
    const type = restoreHeading ? editor.schema.nodes.docHeading : editor.schema.nodes.docParagraph
    tr.setNodeMarkup(pos, type, { ...node.attrs, nativeListDefinition: null, nativeNumberingBinding: null, ...(restoreHeading ? { level: original!.attrs.level, outlineOnly: original!.attrs.outlineOnly } : {}) })
  }
  if (!tr.docChanged) return
  docxOperations((source ?? before).toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('清除列表与当前修改不兼容，请先保存')
}

/** GenOffice numbering-actions: 最近不同numId、当前值、从光标向后同身份改写。 */
export function docxNumberingValueTarget(editor: Editor, anchors: DocxAnchor[]) {
  selectedListParagraphs(editor, anchors)
  const { $from } = editor.state.selection, node = $from.parent
  if (node.type.name !== 'docListItem') throw new Error('请先选择编号列表项')
  const numId = String(node.attrs.numId), ilvl = Number(node.attrs.ilvl) || 0
  const definition = editor.storage.listNumbering.defs.get(numId)
  if (!definition?.levels[ilvl]) throw new Error('此列表没有可核验的编号定义，请先保存或选择列表库')
  let previous: PmNode | undefined
  const refs: { numId: string | null; ilvl: number }[] = []; let caret = -1
  editor.state.doc.descendants((item, pos) => {
    if (item.type.name !== 'docListItem') return true
    if (pos <= $from.pos && $from.pos <= pos + item.nodeSize) caret = refs.length
    refs.push({ numId: item.attrs.numId ?? null, ilvl: Number(item.attrs.ilvl) || 0 }); return false
  })
  editor.state.doc.forEach((item, _pos, index) => {
    if (index < $from.index(0) && item.type.name === 'docListItem' && item.attrs.numId && item.attrs.numId !== numId) previous = item
  })
  return { node, numId, ilvl, definition, previous, currentValue: computeListValues(refs, editor.storage.listNumbering.defs)[caret] ?? 1 }
}

export function setDocxNumberingValue(editor: Editor, anchors: DocxAnchor[], options: { mode: 'restart' | 'continue'; value?: number }) {
  const target = docxNumberingValueTarget(editor, anchors)
  if (!['restart', 'continue'].includes(options.mode) || options.value !== undefined && (!Number.isInteger(options.value) || options.value < 0 || options.value > 32767)) throw new Error('编号值必须为0至32767的整数')
  if (options.mode === 'continue' && !target.previous) throw new Error('没有可继续的前序列表')
  const source = options.mode === 'continue' ? target.previous! : target.node
  const base: DocxNumberingBinding = source.attrs.nativeNumberingBinding
    ? normalizeDocxNumberingBinding(source.attrs.nativeNumberingBinding)
    : source.attrs.nativeListDefinition ? { id: source.attrs.nativeListDefinition.id, custom: normalizeDocxCustomList(source.attrs.nativeListDefinition) }
    : normalizeDocxNumberingBinding({ id: `source-${source.attrs.numId}`, sourceNumId: String(source.attrs.numId) })
  const restart = options.mode === 'restart' || options.value !== undefined
  const binding = restart ? { ...base, id: crypto.randomUUID(), startOverrides: { [target.ilvl]: options.value ?? 1 } } : base
  const numId = docxNumberingBindingId(binding), before = editor.state.doc, tr = closeHistory(editor.state.tr)
  const baseDef = editor.storage.listNumbering.defs.get(String(source.attrs.numId))
  if (!baseDef?.levels[target.ilvl]) throw new Error('前序编号定义不包含当前级别')
  const start = editor.state.selection.$from.index(0)
  before.forEach((node, pos, index) => {
    if (index < start || node.type.name !== 'docListItem' || node.attrs.numId !== target.numId
      && !(options.mode === 'continue' && restart && node.attrs.numId === source.attrs.numId)) return
    const matches = anchors.filter(a => a.docxIndex === node.attrs.docxIndex)
    if (matches.length !== 1 || !matches[0]!.editable) throw new Error('后续列表包含只读项或来源身份缺失')
    const level = baseDef.levels[Number(node.attrs.ilvl) || 0]
    if (!level) throw new Error('后续列表级别与来源定义不兼容')
    tr.setNodeMarkup(pos, undefined, { ...node.attrs, numId, kind: level.numFmt === 'bullet' || level.picBulletId != null ? 'bullet' : 'ordered', nativeListDefinition: null, nativeNumberingBinding: binding })
  })
  docxOperations(before.toJSON(), tr.doc.toJSON(), anchors)
  editor.view.dispatch(tr)
  if (editor.state.doc === before) throw new Error('编号值与当前草稿不兼容，请先保存')
}
