import { createHash } from 'node:crypto'
import { normalizeTableStylePatch } from '../../../report_editor/frontend/src/docx-table-style-core'
import * as legacyTableStyle from './docx-table-style-legacy'
import type { ParsedDoc } from '@genoffice/docx-engine'
/**
 * 固定源 Docs Ribbon ▸ Table Design（components/Ribbon.tsx TABLE_PRESETS / tableDesign 选项卡，
 * editor/table-properties.ts setTableLookOption / applyTablePreset）的原生写回：
 * - 无样式：删除 w:tblStyle（固定源 updateAttributes tblStyleId:null）；
 * - 文档表格样式：w:tblStyle 指向 styles.xml 中已存在的 table 类型样式；
 * - 表格样式选项：w:tblLook（首行/末行/首列/末列/镶边行/镶边列），写法同引擎 generate.ts tableLookXml；
 * - 五个内置预设：与固定源 applyTablePreset 相同，逐格直接底纹（首行 headerFill、其余行奇偶 band1/band2）
 *   + 四边单线 4/8pt 边框，并删除 tblStyle（直接格式不依赖 styles.xml）。底纹/边框复用既有逐格写回。
 * 只改直属 w:tblPr 的 tblStyle/tblLook 与（预设时）各格 tcPr 的 shd/tcBorders，其余字节保持原样。
 */
import type { Block } from '@genoffice/docx-engine'
import { XMLValidator } from 'fast-xml-parser'
import { splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate'
import { docxCellShadingCapability, patchDocxCellShading } from './docx-cell-shading'
import { docxCellBordersCapability, patchDocxTableCellBorders } from './docx-cell-borders'
import { DOCX_TABLE_PRESETS, docxTablePresetRowFill, safeDocxTableStyleRequest, type DocxTableLook, type DocxTableStyleState } from './docx-table-style-spec'

export { DOCX_TABLE_PRESETS, type DocxTableLook, type DocxTablePreset, type DocxTablePresetName, type DocxTableStyleRequest, type DocxTableStyleState } from './docx-table-style-spec'
const LOOK_ATTRS = ['w:val', 'w:firstRow', 'w:lastRow', 'w:firstColumn', 'w:lastColumn', 'w:noHBand', 'w:noVBand']
/** 与 generate.ts TBL_PR_ORDER 相同的 tblPr 子元素顺序。 */
const TBL_PR_ORDER = ['w:tblStyle', 'w:tblpPr', 'w:tblOverlap', 'w:bidiVisual', 'w:tblStyleRowBandSize', 'w:tblStyleColBandSize', 'w:tblW', 'w:jc', 'w:tblCellSpacing', 'w:tblInd', 'w:tblBorders', 'w:shd', 'w:tblLayout', 'w:tblCellMar', 'w:tblLook', 'w:tblCaption', 'w:tblDescription']

function fail(reason = 'unsupported'): never { throw new Error(`docx_table_style_${reason}`) }
const openTag = (xml: string) => /^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/.exec(xml)?.[0] ?? fail()
function attrsOf(xml: string) {
  const result: Record<string, string> = {}
  for (const m of openTag(xml).matchAll(/([^\s=<>/]+)\s*=\s*(["'])([\s\S]*?)\2/g)) { if (Object.hasOwn(result, m[1]!)) fail(); result[m[1]!] = m[3]! }
  return result
}
function childrenOf(xml: string) {
  const open = openTag(xml)
  if (open.endsWith('/>')) return []
  const inner = xml.slice(open.length, xml.lastIndexOf('</')), parts = splitXmlChildren(inner)
  if (inner.replace(/<!--[\s\S]*?-->/g, '').replace(/\s/g, '') !== parts.map(part => part.xml).join('').replace(/<!--[\s\S]*?-->/g, '').replace(/\s/g, '')) fail()
  return parts
}
const leafOnly = (xml: string) => { if (!openTag(xml).endsWith('/>') && xml.slice(openTag(xml).length, xml.lastIndexOf('</')).trim()) fail() }

/** 固定源 parse.ts tblLookFlags 的读取语义（显式属性 > w:val 位 > 默认）。 */
function readLook(lookXml: string | undefined): DocxTableLook {
  const look = lookXml ? attrsOf(lookXml) : {}
  const bits = parseInt(look['w:val'] ?? '', 16)
  const flag = (attr: string, bit: number, fallback: boolean) => look[attr] !== undefined ? look[attr] !== '0' && look[attr] !== 'false' : Number.isFinite(bits) ? (bits & bit) !== 0 : fallback
  return { firstRow: flag('w:firstRow', 0x20, true), lastRow: flag('w:lastRow', 0x40, false), firstColumn: flag('w:firstColumn', 0x80, true), lastColumn: flag('w:lastColumn', 0x100, false), bandedRows: !flag('w:noHBand', 0x200, false), bandedColumns: !flag('w:noVBand', 0x400, true) }
}
/** 与 generate.ts tableLookXml 相同的写法（十六进制 w:val 与显式属性并存）。 */
function lookXml(look: DocxTableLook): string {
  const val = (look.firstRow ? 0x20 : 0) | (look.lastRow ? 0x40 : 0) | (look.firstColumn ? 0x80 : 0) | (look.lastColumn ? 0x100 : 0) | (look.bandedRows ? 0 : 0x200) | (look.bandedColumns ? 0 : 0x400)
  return `<w:tblLook w:val="${val.toString(16).toUpperCase().padStart(4, '0')}" w:firstRow="${look.firstRow ? 1 : 0}" w:lastRow="${look.lastRow ? 1 : 0}" w:firstColumn="${look.firstColumn ? 1 : 0}" w:lastColumn="${look.lastColumn ? 1 : 0}" w:noHBand="${look.bandedRows ? 0 : 1}" w:noVBand="${look.bandedColumns ? 0 : 1}"/>`
}
/** 替换/删除/插入直属 tblPr 的一个子元素，保留其余字节。 */
function setTblPrChild(tableXml: string, name: string, replacement: string | null): string {
  const tblOpen = openTag(tableXml), inner = tableXml.slice(tblOpen.length, tableXml.lastIndexOf('</w:tbl>'))
  const parts = splitXmlChildren(inner), props = parts.filter(part => part.name === 'w:tblPr')
  if (props.length > 1) fail()
  if (!props.length) {
    if (!replacement) return tableXml
    return tblOpen + `<w:tblPr>${replacement}</w:tblPr>` + tableXml.slice(tblOpen.length)
  }
  const prop = props[0]!.xml, at = tableXml.indexOf(prop, tblOpen.length)
  let next: string
  const open = openTag(prop)
  if (open.endsWith('/>')) next = replacement ? `${open.slice(0, -2)}>${replacement}</w:tblPr>` : prop
  else {
    const children = childrenOf(prop), matches = children.filter(child => child.name === name)
    if (matches.length > 1) fail()
    if (matches.length) { const old = matches[0]!.xml, index = prop.indexOf(old, open.length); next = prop.slice(0, index) + (replacement ?? '') + prop.slice(index + old.length) }
    else if (!replacement) next = prop
    else {
      const rank = TBL_PR_ORDER.indexOf(name), following = children.find(child => TBL_PR_ORDER.indexOf(child.name) > rank || child.name === 'w:tblPrChange')
      const index = following ? prop.indexOf(following.xml, open.length) : prop.lastIndexOf('</w:tblPr>')
      next = prop.slice(0, index) + replacement + prop.slice(index)
    }
  }
  return tableXml.slice(0, at) + next + tableXml.slice(at + prop.length)
}
const rowsOf = (xml: string) => xmlSegments(xml, 'w:tr', 0, xml.length).map(row => xmlSegments(xml, 'w:tc', row.start, row.end))

function sourceOf(block: Block) {
  const xml = block.originalXml
  if (block.type !== 'table' || !block.table || !xml || xml.length > 1024 * 1024 || XMLValidator.validate(xml) !== true || !/^<w:tbl(?:\s|>)/.test(xml)
    || (xml.match(/<w:tbl\b/g) ?? []).length !== 1 || /<!DOCTYPE|<!ENTITY|<w:(?:tblPrChange|trPrChange|tcPrChange|tblGridChange|tblPrExChange|ins|del|moveFrom|moveTo|cellIns|cellDel|cellMerge)\b/.test(xml)) fail()
  const parts = childrenOf(xml), props = parts.filter(part => part.name === 'w:tblPr')
  if (props.length > 1) fail()
  const children = props.length ? childrenOf(props[0]!.xml) : []
  const style = children.filter(child => child.name === 'w:tblStyle'), look = children.filter(child => child.name === 'w:tblLook')
  if (style.length > 1 || look.length > 1) fail()
  let styleId: string | null = null
  if (style.length) { leafOnly(style[0]!.xml); const a = attrsOf(style[0]!.xml); if (Object.keys(a).some(key => key !== 'w:val') || !a['w:val']) fail(); styleId = a['w:val']! }
  if (look.length) { leafOnly(look[0]!.xml); const a = attrsOf(look[0]!.xml); if (Object.keys(a).some(key => !LOOK_ATTRS.includes(key)) || (a['w:val'] !== undefined && !/^[0-9A-Fa-f]{1,4}$/.test(a['w:val']))) fail() }
  if ((block.table as { tblStyleId?: string }).tblStyleId !== undefined && (block.table as { tblStyleId?: string }).tblStyleId !== styleId) fail()
  const rows = rowsOf(xml)
  for (const row of rows) for (const cell of row) {
    const props = childrenOf(xml.slice(cell.start, cell.end)).filter(child => child.name === 'w:tcPr')
    if (props.length > 1) fail()
    if (props.length) { const children = childrenOf(props[0]!.xml); for (const name of ['w:shd', 'w:tcBorders']) if (children.filter(child => child.name === name).length > 1) fail() }
  }
  const presetEditable = rows.length > 0 && rows.length <= 100 && docxCellBordersCapability(xml).bordersEditable
    && rows.every(row => row.every(cell => docxCellShadingCapability(xml, xml.slice(cell.start, cell.end)).shadingEditable))
  return { xml, rows, state: { styleId, look: readLook(look[0]?.xml), presetEditable } satisfies DocxTableStyleState }
}

export function tableStyleAvailability(block: Block, context?: Pick<ParsedDoc, 'styles' | 'protection'>) {
  if (context?.protection?.enforced) return legacyTableStyle.tableStyleAvailability(block, context)
  try { const s = sourceOf(block); return { tableStyleEditable: true, tableStyleReadOnlyReason: null, tableStyleState: s.state, tableStyleSource: {styleId: s.state.styleId, look: s.state.look}, ...(context ? {tableStyleOptions: [...context.styles.values()].filter(style => style.type === 'table' && style.styleId !== 'TableNormal').map(style => ({styleId:style.styleId,name:style.name}))} : {}) } }
  catch (error) { return { tableStyleEditable: false, tableStyleReadOnlyReason: error instanceof Error ? error.message : 'docx_table_style_unsupported' } }
}

/** tableStyles：styles.xml 中 table 类型样式的 id 集合。 */
export function editTableStyle(block: Block, tableStylesOrRaw: ReadonlySet<string> | unknown, rawOrContext: unknown) {
  if (!(tableStylesOrRaw instanceof Set)) return legacyTableStyle.editTableStyle(block, tableStylesOrRaw, rawOrContext as Pick<ParsedDoc, 'styles' | 'protection'>)
  const tableStyles = tableStylesOrRaw as ReadonlySet<string>, raw = rawOrContext
  const request = safeDocxTableStyleRequest(raw, tableStyles), look = request.look
  const s = sourceOf(block)
  let xml = s.xml, styleId = s.state.styleId
  if (request.preset !== undefined) {
    if (!s.state.presetEditable) fail('preset_unsupported')
    const preset = DOCX_TABLE_PRESETS[request.preset]
    for (let r = s.rows.length - 1; r >= 0; r--) {
      const fill = docxTablePresetRowFill(preset, r)
      const cells = rowsOf(xml)[r]!
      for (let c = cells.length - 1; c >= 0; c--) { const cell = cells[c]!; xml = xml.slice(0, cell.start) + patchDocxCellShading(xml.slice(cell.start, cell.end), fill) + xml.slice(cell.end) }
    }
    const ids = rowsOf(xml).map((row, r) => row.map((_, c) => ({ cellId: `${r}:${c}` })))
    xml = patchDocxTableCellBorders(xml, [{ range: null, mode: 'all', pen: { style: 'single', szEighths: 4, color: preset.borderColor } }], ids)
    xml = setTblPrChild(xml, 'w:tblStyle', null); styleId = null
  } else if (request.styleId !== undefined) {
    styleId = request.styleId
    xml = setTblPrChild(xml, 'w:tblStyle', styleId === null ? null : `<w:tblStyle w:val="${styleId.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')}"/>`)
  }
  if (look) xml = setTblPrChild(xml, 'w:tblLook', lookXml(look))
  if (XMLValidator.validate(xml) !== true) fail('xml_invalid')
  return { xml, styleId, look: look ?? s.state.look, preset: request.preset ?? null }
}

/** 保存后复读：表格字节与写入一致，样式引用与样式选项按请求生效。 */
export function verifyTableStyleResult(block: Block, result: ReturnType<typeof editTableStyle>) {
  if ('patch' in result) { legacyTableStyle.verifyTableStyleResult(block, result); return }
  const s = sourceOf(block)
  if (block.originalXml !== result.xml || s.state.styleId !== result.styleId || JSON.stringify(s.state.look) !== JSON.stringify(result.look)) fail('write_not_applied')
}

export function validateTableStyleOperation(block: Block, input: unknown, context: Pick<ParsedDoc, 'styles' | 'protection'>) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) fail('invalid')
  const op = input as Record<string, unknown>
  if (Object.keys(op).some(key => !['kind','blockId','expectedObjectSha256','style','look','preset'].includes(key)) || op.kind !== 'setTableStyle' || typeof op.blockId !== 'string' || !op.blockId || op.expectedObjectSha256 !== createHash('sha256').update(block.originalXml ?? '').digest('hex')) fail('anchor_invalid')
  const { kind, blockId, expectedObjectSha256, ...raw } = op
  const patch = normalizeTableStylePatch(raw)
  if (patch.preset || patch.style?.kind === 'preset') return legacyTableStyle.validateTableStyleOperation(block, input, context)
  if (context.protection?.enforced) fail('protected')
  return editTableStyle(block, new Set([...context.styles.values()].filter(style => style.type === 'table').map(style => style.styleId)), { ...(patch.style ? { styleId: patch.style.kind === 'document' ? patch.style.styleId : null } : {}), ...(patch.look ? {look:patch.look} : {}) })
}
