import { normalizeTableStylePatch } from './docx-table-style-core'
import type { Schema } from '@tiptap/pm/model'
import * as legacyTableStyle from './docx-table-style-legacy'
/**
 * 固定源 Docs Ribbon ▸ 表格设计（Ribbon.tsx tableDesign：无样式 / TABLE_PRESETS / 文档表格样式库，
 * 表格样式选项 首行/末行/镶边行/首列/末列/镶边列 → table-properties.ts setTableLookOption）的原生写回前端。
 * 编辑意图记录在 docTable.nativeTableStyle（属性登记在 docx-tables NativeTableStructure；一次整表请求：styleId 或 preset，加可选 look），
 * 预览直接更新 tblStyleId / tblLook（预设时逐格 fill + 四边单线边框，与桥接写法一致）；
 * 保存时整表与“来源 + 意图投影”逐字节比对后才映射为 setTableStyle，同表其他修改须先保存。
 */
import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { NodeSelection, type EditorState } from '@tiptap/pm/state'
import { isInTable, selectedRect } from '@tiptap/pm/tables'
import { DOCX_CELL_BORDER_SIDES, docxCellBorderSideLine } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import { DOCX_TABLE_LOOK_KEYS, DOCX_TABLE_PRESETS, docxTablePresetRowFill, safeDocxTableStyleRequest, type DocxTableLook, type DocxTablePresetName, type DocxTableStyleRequest, type DocxTableStyleState } from '../../../reporting/doc_engine/bridge/docx-table-style-spec'
import type { DocxPmNode } from './docx-operations'
import { createModal } from './modal'
import { buttonClasses } from './button'

export interface DocxTableStyleOption { styleId: string; name: string }
export interface DocxTableStyleAnchor { docxIndex?: number; blockId?: string; expectedObjectSha256?: string; tableStyleSource?: import('./docx-table-style-core').TableStyleSource; tableStyleEditable?: boolean; tableStyleReadOnlyReason?: string | null; tableStyleState?: DocxTableStyleState; tableStyleOptions?: DocxTableStyleOption[]; cells?: { cellId: string }[][] }
export interface DocxTableStyleOperation { [key: string]: unknown; kind: 'setTableStyle'; blockId: string; expectedObjectSha256: string; styleId?: string | null; look?: DocxTableLook; preset?: DocxTablePresetName }

/** Ribbon 命令 → 预设 / 样式选项键（固定源 TABLE_PRESETS 顺序与 tableDesign 选项顺序）。 */
export const DOCX_TABLE_STYLE_PRESET_ACTIONS: Record<string, DocxTablePresetName> = {
  'table-style-grid': 'grid', 'table-style-blue-header': 'blueHeader', 'table-style-blue-banded': 'blueBanded', 'table-style-gray-banded': 'grayBanded', 'table-style-green-header': 'greenHeader',
}
export const DOCX_TABLE_LOOK_ACTIONS: Record<string, keyof DocxTableLook> = {
  'table-look-first-row': 'firstRow', 'table-look-last-row': 'lastRow', 'table-look-banded-rows': 'bandedRows', 'table-look-first-column': 'firstColumn', 'table-look-last-column': 'lastColumn', 'table-look-banded-columns': 'bandedColumns',
}
export const isDocxTableStyleAction = (action: string) => action === 'table-style-none' || action === 'table-style-custom' || !!DOCX_TABLE_STYLE_PRESET_ACTIONS[action] || !!DOCX_TABLE_LOOK_ACTIONS[action]

/** 同表其他编辑意图：表格样式整表写回须与它们分开保存。 */
const OTHER_INTENTS = ['nativeTableProperties', 'nativeTableCellParagraphProperties', 'nativeTableStructure', 'nativeTableCellShape', 'nativeTableColumnWidths', 'nativeTableRowHeights', 'nativeTableAutoFit', 'nativeTableCellTextDirection', 'nativeTableCellAlignment', 'nativeTableCellMargins', 'nativeTableCellMarginOverrides', 'nativeTableRowBreaks', 'nativeTableAlignment', 'nativeTableCellWrap', 'nativeTableAltText', 'nativeTableInsert', 'nativeCellBorders']
const MIXED = '表格样式修改不能与同表文字、格式或其他结构修改混用，请先保存'
const canonical = (v: unknown): unknown => Array.isArray(v) ? v.map(canonical) : v && typeof v === 'object' ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => [k, canonical(x)])) : v
const same = (a: unknown, b: unknown) => JSON.stringify(canonical(a)) === JSON.stringify(canonical(b))
function fail(message = '表格样式来源或草稿无效'): never { throw new Error(message) }

export function safeDocxTableStyleOptions(value: unknown): DocxTableStyleOption[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > 500) fail('表格样式库无效')
  return value.map(item => {
    if (!item || typeof item !== 'object' || typeof item.styleId !== 'string' || !item.styleId || (item.name !== undefined && item.name !== null && typeof item.name !== 'string')) fail('表格样式库无效')
    return { styleId: item.styleId, name: item.name || item.styleId }
  })
}
const styleSet = (styles: readonly DocxTableStyleOption[]) => new Set(styles.map(style => style.styleId))

/** 来源表格 + 意图 → 预览/核验用的表格 JSON。 */
export function projectDocxTableStyle(source: DocxPmNode, anchor: DocxTableStyleAnchor, raw: unknown, schema?: Schema): DocxPmNode {
  if (schema && anchor.tableStyleState && !anchor.tableStyleState.presetEditable && raw && typeof raw === 'object' && !('styleId' in raw)) {
    const patch = normalizeTableStylePatch(raw)
    if (patch.preset || patch.style?.kind === 'preset') fail('当前表格含合并、嵌套或无法逐格写入的单元格，内置样式暂不支持')
    return projectDocxTableStyle(source, anchor, { ...((source.attrs?.nativeTableStyle as object | undefined) ?? {}), ...(patch.style ? { styleId: patch.style.kind === 'document' ? patch.style.styleId : null } : {}), ...(patch.look ? {look:patch.look} : {}) })
  }
  const legacy = raw && typeof raw === 'object' && ('style' in raw || ('preset' in raw && String(raw.preset).includes('-')))
  const pending = source.attrs?.nativeTableStyle as Record<string, unknown> | undefined
  if (legacy || (schema && !anchor.tableStyleState) || (schema && pending && ('style' in pending || (typeof pending.preset === 'string' && pending.preset.includes('-'))))) return legacyTableStyle.projectDocxTableStyle(source, anchor, raw, schema)

  const state = anchor.tableStyleState
  if (source.type !== 'docTable' || !anchor.tableStyleEditable || !state) fail(anchor.tableStyleReadOnlyReason ?? '当前来源表格不支持修改表格样式')
  let request: DocxTableStyleRequest
  try { request = safeDocxTableStyleRequest(raw, styleSet(anchor.tableStyleOptions ?? [])) } catch { fail('表格样式草稿无效') }
  const table = structuredClone(source)
  if (OTHER_INTENTS.some(key => table.attrs?.[key] != null)) fail(MIXED)
  if (request.preset) {
    const cells = anchor.cells
    if (!state.presetEditable || !cells || table.content?.length !== cells.length || table.content.some((row, r) => row.content?.length !== cells[r]?.length)) fail('当前表格含合并、嵌套或无法逐格写入的单元格，内置样式暂不支持')
    const preset = DOCX_TABLE_PRESETS[request.preset], pen = { style: 'single', szEighths: 4, color: preset.borderColor }
    table.content!.forEach((row, r) => row.content!.forEach((cell, c) => {
      const borders = { ...((cell.attrs?.borders as Record<string, unknown> | null) ?? {}) }
      for (const side of DOCX_CELL_BORDER_SIDES) {
        const line = docxCellBorderSideLine('all', side, { top: r === 0, bottom: r === cells.length - 1, left: c === 0, right: c === row.content!.length - 1 }, pen)
        if (line) borders[side] = line
      }
      cell.attrs = { ...cell.attrs, fill: docxTablePresetRowFill(preset, r), borders }
    }))
  }
  const styleId = request.preset ? null : request.styleId !== undefined ? request.styleId : state.styleId
  table.attrs = { ...table.attrs, tblStyleId: styleId, ...(request.look ? { tblLook: { ...request.look } } : {}), nativeTableStyle: request }
  return table
}

function target(state: EditorState) {
  let table = state.selection instanceof NodeSelection && state.selection.node.type.name === 'docTable' ? state.selection.node : null, pos = table ? state.selection.from : -1
  if (!table) {
    if (!isInTable(state)) return null
    const rect = selectedRect(state)
    table = rect.table; pos = rect.tableStart - 1
  }
  return { table, pos }
}
function context(editor: Editor, baseline: DocxPmNode, anchors: readonly DocxTableStyleAnchor[]) {
  if (!editor.isEditable) fail('当前文档只读')
  const current = target(editor.state)
  if (!current) fail('请先在表格内定位')
  const anchor = anchors.find(item => item.docxIndex === current.table.attrs.docxIndex)
  const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === current.table.attrs.docxIndex)
  if (!anchor || !source || current.table.attrs.docxIndex == null) fail('请先保存新增表格，再修改表格样式')
  if (!anchor.tableStyleEditable || !anchor.tableStyleState) fail(anchor.tableStyleReadOnlyReason ?? '当前来源表格不支持修改表格样式')
  const pending = current.table.attrs.nativeTableStyle as DocxTableStyleRequest | null
  if (!same(current.table.toJSON(), pending ? projectDocxTableStyle(source, anchor, pending) : source)) fail(MIXED)
  return { ...current, anchor, source, pending, state: anchor.tableStyleState }
}
/** 当前有效状态（来源 + 待保存意图）。 */
function effective(pending: DocxTableStyleRequest | null, state: DocxTableStyleState) {
  return { styleId: pending?.preset ? null : pending?.styleId !== undefined ? pending.styleId : state.styleId, preset: pending?.preset ?? null, look: pending?.look ?? state.look }
}

/** 合并新命令到待保存意图；与来源一致的字段剔除，全部一致时清空意图。 */
export function mergeDocxTableStyleRequest(pending: DocxTableStyleRequest | null, next: DocxTableStyleRequest, state: DocxTableStyleState): DocxTableStyleRequest | null {
  const merged: DocxTableStyleRequest = { ...(pending ?? {}) }
  if (next.preset) { delete merged.styleId; merged.preset = next.preset }
  if (next.styleId !== undefined) { delete merged.preset; merged.styleId = next.styleId }
  if (next.look) merged.look = next.look
  if (merged.styleId !== undefined && merged.styleId === state.styleId) delete merged.styleId
  if (merged.look && same(merged.look, state.look)) delete merged.look
  return Object.keys(merged).length ? merged : null
}

export function docxTableStyleRequestFor(action: string, pending: DocxTableStyleRequest | null, state: DocxTableStyleState, styleId?: string): DocxTableStyleRequest {
  if (action === 'table-style-none') return { styleId: null }
  if (action === 'table-style-custom') { if (!styleId) fail('请选择表格样式'); return { styleId } }
  const preset = DOCX_TABLE_STYLE_PRESET_ACTIONS[action]
  if (preset) return { preset }
  const key = DOCX_TABLE_LOOK_ACTIONS[action]
  if (!key) fail('未知的表格样式命令')
  const look = effective(pending, state).look
  return { look: { ...look, [key]: !look[key] } }
}

export function docxTableStyleUnavailable(editor: Editor, baseline: DocxPmNode, anchors: readonly DocxTableStyleAnchor[], action: string): string | null {
  try {
    const current = context(editor, baseline, anchors)
    if (DOCX_TABLE_STYLE_PRESET_ACTIONS[action] && !current.state.presetEditable) return '当前表格含合并、嵌套或无法逐格写入的单元格，内置样式暂不支持'
    if (action === 'table-style-custom' && !current.anchor.tableStyleOptions?.length) return '此文档没有可用的表格样式'
    return null
  } catch (error) { return error instanceof Error ? error.message : '当前表格不支持修改表格样式' }
}
export function docxTableStyleActive(editor: Editor, baseline: DocxPmNode, anchors: readonly DocxTableStyleAnchor[], action: string): boolean {
  try {
    const current = context(editor, baseline, anchors), value = effective(current.pending, current.state)
    const key = DOCX_TABLE_LOOK_ACTIONS[action]
    if (key) return value.look[key]
    if (action === 'table-style-none') return value.styleId === null && value.preset === null
    return DOCX_TABLE_STYLE_PRESET_ACTIONS[action] === value.preset
  } catch { return false }
}
/** 应用一个 Ribbon 命令；返回是否产生了修改。 */
export function applyDocxTableStyle(editor: Editor, baseline: DocxPmNode, anchors: readonly DocxTableStyleAnchor[], action: string, styleId?: string): boolean {
  const current = context(editor, baseline, anchors)
  const request = mergeDocxTableStyleRequest(current.pending, docxTableStyleRequestFor(action, current.pending, current.state, styleId), current.state)
  const next = request ? projectDocxTableStyle(current.source, current.anchor, request) : structuredClone(current.source)
  if (same(next, current.table.toJSON())) return false
  editor.view.focus()
  // 只改表格与单元格属性（setNodeMarkup），保留光标与选区
  let tr = closeHistory(editor.state.tr)
  // JSON children are physical cells; a grid map repeats merged cells across slots.
  current.table.forEach((row, rowOffset, r) => row.forEach((_cell, cellOffset, c) => {
    const attrs = next.content![r]!.content![c]!.attrs, pos = current.pos + 2 + rowOffset + cellOffset
    if (!same(tr.doc.nodeAt(pos)!.attrs, attrs)) tr = tr.setNodeMarkup(pos, undefined, attrs)
  }))
  tr = tr.setNodeMarkup(current.pos, undefined, next.attrs)
  if (!same(tr.doc.nodeAt(current.pos)!.toJSON(), next)) fail(MIXED)
  editor.view.dispatch(tr)
  return true
}

/** 保存前：整表与“来源 + 意图投影”逐字节一致才映射为 setTableStyle，并把该表还原为来源供后续差异比对。 */
export function normalizeDocxTableStyle(baseline: DocxPmNode, live: DocxPmNode, anchors: readonly DocxTableStyleAnchor[], schema?: Schema) {
  const current = structuredClone(live), operations: DocxTableStyleOperation[] = []
  for (const [index, table] of (current.content ?? []).entries()) if (table.type === 'docTable' && table.attrs?.nativeTableStyle != null) {
    const anchor = anchors.find(item => item.docxIndex === table.attrs!.docxIndex)
    const source = baseline.content?.find(node => node.type === 'docTable' && node.attrs?.docxIndex === table.attrs!.docxIndex)
    if (!anchor || !source) fail()
    const request = table.attrs.nativeTableStyle as DocxTableStyleRequest
    if (!same(table, projectDocxTableStyle(source, anchor, request, table.attrs?.tblLookEdited || (request && 'style' in request) ? schema : undefined))) fail(MIXED)
    current.content![index] = structuredClone(source)
    operations.push({ kind: 'setTableStyle', blockId: anchor.blockId!, expectedObjectSha256: anchor.expectedObjectSha256!, ...request })
  }
  return { current, operations }
}
/** 草稿恢复：按来源身份重放 setTableStyle。 */
export function replayDocxTableStyle(baseline: DocxPmNode, operations: readonly Record<string, any>[], anchors: readonly DocxTableStyleAnchor[], schema?: Schema): DocxPmNode {
  const current = structuredClone(baseline), seen = new Set<string>()
  for (const operation of operations) if (operation.kind === 'setTableStyle') {
    const { kind: _kind, blockId, expectedObjectSha256, ...request } = operation
    const anchor = anchors.find(item => item.blockId === blockId)
    if (!anchor || expectedObjectSha256 !== anchor.expectedObjectSha256 || seen.has(blockId) || operations.some(other => other !== operation && other.blockId === blockId)) fail('表格样式草稿的来源身份无效或与同表其他修改混合')
    const index = current.content?.findIndex(node => node.type === 'docTable' && node.attrs?.docxIndex === anchor.docxIndex) ?? -1
    if (index < 0) fail()
    seen.add(blockId)
    current.content![index] = projectDocxTableStyle(current.content![index]!, anchor, request, schema)
  }
  return current
}
/** 当前表格可选的文档表格样式（来自 styles.xml，由 inspect 返回）。 */
export function docxTableStyleOptionsAt(editor: Editor, baseline: DocxPmNode, anchors: readonly DocxTableStyleAnchor[]) {
  const current = context(editor, baseline, anchors)
  return { options: current.anchor.tableStyleOptions ?? [], styleId: effective(current.pending, current.state).styleId }
}
/** 固定源 Ribbon “其他表格样式”：文档中已有的表格样式列表。 */
export function openDocxTableStyleGallery(root: HTMLElement, options: readonly DocxTableStyleOption[], current: string | null, apply: (styleId: string) => void) {
  const modal = createModal({ root, label: '表格样式', closeLabel: '关闭表格样式', onRequestClose: () => modal.remove(), content: `
    <h2>表格样式</h2><form><label>文档中的表格样式<select aria-label="文档表格样式" size="8"></select></label>
      <p>引用文档 styles.xml 中已有的表格样式；首行、镶边行等外观随“表格样式选项”生效。</p>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">应用</button></form>` })
  const select = modal.card.querySelector<HTMLSelectElement>('select')!
  for (const option of options) { const item = document.createElement('option'); item.value = option.styleId; item.textContent = option.name === option.styleId ? option.name : `${option.name}（${option.styleId}）`; select.append(item) }
  select.value = current && options.some(option => option.styleId === current) ? current : options[0]?.styleId ?? ''
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { if (!options.some(option => option.styleId === select.value)) throw new Error('请选择表格样式'); apply(select.value); modal.remove() }
    catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(select)
}
export { DOCX_TABLE_LOOK_KEYS }
