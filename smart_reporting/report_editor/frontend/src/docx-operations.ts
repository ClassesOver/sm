import {projectDocxTableProperties,type DocxTablePropertiesAnchor} from './docx-table-properties'
import { projectDocxPicture, type DocxPictureAnchor } from './docx-pictures'
import { projectStylesPaneActions, type StylesPaneAction } from './docx-styles-pane-operations'
import { DOCX_FONT_PROPERTIES, DOCX_FONT_DISPLAY, docxFontProperties } from '../../../reporting/doc_engine/bridge/docx-font-properties'
import { normalizeDocxDropCaps, replayDocxDropCap } from './docx-drop-cap'
import { docxDropCapAttribute, normalizeDocxDropCap } from '../../../reporting/doc_engine/bridge/docx-drop-cap'
import { fontDialogMarkAttrs } from './docx-font-properties'
import { docxParagraphPropertiesOperation, replayDocxParagraphProperties } from './docx-paragraph-properties'
import { docxTableCellParagraphPropertiesOperation, projectDocxTableCellParagraphProperties } from './docx-table-cell-paragraph-properties'
import { normalizeDocxTextRevisions, replayDocxTextRevisions, type DocxTextRevisionAnchor } from './docx-text-revisions'
import { assertDocxTextRevisionBatch } from './docx-text-revisions-core'
import { projectDocxTableAltText, type DocxTableAltTextAnchor } from './docx-table-alt-text'
import { projectDocxCellWrap, type DocxCellWrapAnchor } from './docx-table-cell-wrap'
import type { TableCellWrapStep } from './docx-table-cell-wrap-core'
import { projectDocxTableAlignment, type DocxTableAlignmentAnchor } from './docx-table-alignment'
import type { TableAlignment } from './docx-table-alignment-core'
import { projectDocxRowBreaks, type DocxRowBreakAnchor } from './docx-table-row-breaks'
import type { TableRowBreakStep } from './docx-table-row-breaks-core'
import { projectDocxCellMarginOverrides, type DocxCellMarginOverridesAnchor } from './docx-table-cell-margin-overrides'
import type { TableCellMarginOverrideStep } from './docx-table-cell-margin-overrides-core'
import { projectTableHeaders, tableHeaderOperation } from './docx-table-headers'
import { projectDocxCellShape, type DocxCellShapeSource } from './docx-table-cell-shape'
import { projectDocxColumnWidths, type DocxColumnWidthAnchor } from './docx-table-column-width'
import { projectDocxRowHeights, type DocxRowHeightAnchor } from './docx-table-row-height'
import type { TableRowHeightStep } from './docx-table-row-height-core'
import { projectDocxAutoFit, type DocxAutoFitAnchor } from './docx-table-autofit'
import type { TableAutoFitStep } from './docx-table-autofit-core'
import { projectDocxCellTextDirection, type DocxCellTextDirectionAnchor } from './docx-table-cell-text-direction'
import type { TableCellTextDirectionStep } from './docx-table-cell-text-direction-core'
import { projectDocxCellAlignment, type DocxCellAlignmentAnchor } from './docx-table-cell-alignment'
import type { TableCellAlignmentStep } from './docx-table-cell-alignment-core'
import { projectDocxCellMargins, type DocxCellMarginsAnchor } from './docx-table-cell-margins'
import type { TableColumnWidthStep } from './docx-table-column-width-core'
import type { TableCellShapeStep } from './docx-table-cell-shape-core'
import { assertDocxNestedOperationBatch, normalizeDocxNestedTables, replayDocxNestedTables, type DocxNestedTableAnchor } from './docx-nested-tables'
import { projectRibbonStyle } from './docx-style-majority'
import { docxFontPickAttrs } from '../../../reporting/doc_engine/bridge/docx-font-slots'
import { DOCX_LINE_SPACING_FIELDS, docxLineSpacingPatch } from '../../../reporting/doc_engine/bridge/docx-line-spacing'
import { validDocxSpecialIndent } from '../../../reporting/doc_engine/bridge/docx-special-indent'
import { normalizeDocxCustomList, customListLevel } from '../../../reporting/doc_engine/bridge/docx-custom-list'
import { normalizeDocxNumberingBinding, docxNumberingBindingId } from '../../../reporting/doc_engine/bridge/docx-numbering-value'
import { docxRulerIndentOperation, replayDocxRulerIndent, type DocxRulerIndentAnchor } from './docx-ruler-indent'
import { docxTabStopsOperation, replayDocxTabStops, type DocxTabStopsAnchor } from './docx-tab-stops'
import { normalizeDocxCellBorders, projectedDocxCellBordersBaseline, replayDocxCellBorders } from './docx-cell-borders'
import { normalizeDocxTableStyle, replayDocxTableStyle, type DocxTableStyleAnchor } from './docx-table-style'
import { highlightMap, paragraphHighlight, safeDocxHighlight, withoutHighlight } from './docx-highlight'
import { docxBorderAttrs, paragraphBorders, safeDocxBorderSpec } from './docx-borders'
import { safeDocxShading } from './docx-shading'
import { normalizeDocxCellShading, replayDocxCellShading } from './docx-cell-shading'
import { paragraphVerticalAlign, withoutVerticalAlign, verticalAlignMap } from './docx-vertical'
import { TABLE_KINDS, projectDocxTable, projectDocxTableSteps, tableIntent, tableSteps } from './docx-tables'
import { newTableMatchesProjection, newTableNodeCells, newTableSize, projectNewDocxTable } from './docx-new-table'
import { coverGroupMatchesProjection, coverGroupParas, isCoverEndNode, projectCoverNodes } from './docx-cover-page'
import type { Schema } from '@tiptap/pm/model'
import type { NativeOperation } from './native-draft'
import type { SectionSettings } from '@genoffice/docx-engine'
import { validDocxPageBorderValues } from './docx-page-borders'
export interface DocxCellAnchor { cellId: string; expectedObjectSha256: string; editable: boolean; paragraphs?: { index: number; expectedObjectSha256: string; editable: boolean }[]; shadingEditable?: boolean; shadingReadOnlyReason?: string }
import { safeParagraphStyle, type DocxStyleInfo } from './docx-styles'
import { restoredDocxHeaderFooterOperations } from './docx-hf'
export interface DocxAnchor extends DocxPictureAnchor, DocxTablePropertiesAnchor {
  fontDialogEditable?: boolean; nestedTables?: DocxNestedTableAnchor[]; bordersEditable?: boolean; bordersReadOnlyReason?: string; docxIndex: number; blockId: string; expectedObjectSha256: string; editable: boolean; deletable?: boolean; paragraphShadingEditable?: boolean; paragraphBordersEditable?: boolean; paragraphLayoutEditable?: boolean; paragraphStyleEditable?: boolean; paragraphStyleReadOnlyReason?: string | null; links?: { from: number; to: number; href: string }[]; cells?: DocxCellAnchor[][]; structureEditable?: boolean; structureReadOnlyReason?: string | null; tableWidthsTwips?: number[]; tableHeaderCount?: number }
export interface DocxAnchor { cellShapeEditable?: boolean; cellShapeReadOnlyReason?: string | null; cellShapeWidthsTwips?: number[]; cellShapeCells?: DocxCellShapeSource[] }
export interface DocxAnchor extends DocxTextRevisionAnchor, DocxTableAltTextAnchor, DocxCellWrapAnchor, DocxColumnWidthAnchor, DocxRowHeightAnchor, DocxAutoFitAnchor, DocxCellTextDirectionAnchor, DocxCellAlignmentAnchor, DocxCellMarginsAnchor, DocxCellMarginOverridesAnchor, DocxRowBreakAnchor, DocxTableAlignmentAnchor, DocxTableStyleAnchor, DocxRulerIndentAnchor { columnWidthSectionId?: string; rowHeightSectionId?: string; autoFitSectionId?: string; sourceSectionId?: string }
export interface DocxPmNode { type: string; attrs?: Record<string, unknown>; text?: string; marks?: { type: string; attrs?: Record<string, unknown> }[]; content?: DocxPmNode[] }
export interface DocxAnchor extends DocxTabStopsAnchor { paragraphPropertiesEditable?: boolean; dropCapEditable?: boolean }
/** 固定源 ribbon-tabs.tsx clearAllFormatting：先清选区 marks，再应用默认样式及 Ctrl+Q。 */
export const DOCX_CLEAR_PARAGRAPH_ATTRS: Record<string, unknown> = { ...Object.fromEntries([
  'align', 'lineSpacing', 'lineRule', 'lineRawTwips', 'indentLeft', 'indentRight', 'indentFirstLine',
  'indentFirstLineChars', 'spaceBefore', 'spaceAfter', 'spaceBeforeAuto', 'spaceAfterAuto',
  'contextualSpacing', 'keepNext', 'keepLines', 'widowControl', 'suppressLineNumbers', 'shadingFill',
  'borders', 'borderLines', 'tabStops', 'dropCap',
].map(key => [key, null])), pageBreakBefore: false }
export interface DocxClearRange { from: number; to: number }
export function docxClearRanges(value: unknown, text: string): DocxClearRange[] {
  if (!Array.isArray(value) || !value.length || value.length > 100) throw new Error('清除格式范围无效')
  return value.map(range => {
    if (!range || typeof range !== 'object' || Object.keys(range).some(key => !['from', 'to'].includes(key))
      || !(text.length === 0 && range.from === 0 && range.to === 0) && !validDocxLinkRange(text, range.from, range.to)) throw new Error('清除格式范围无效')
    return { from: range.from, to: range.to }
  })
}
export function projectClearedDocxParagraph(source: DocxPmNode, value: unknown, defaultStyleId: string | null, schema: Schema): DocxPmNode {
  if (!['docParagraph', 'docHeading', 'docListItem'].includes(source.type) || (source.content ?? []).some(run => run.type !== 'text')) throw new Error('此段落的内联对象暂不支持清除格式')
  const length = textOf(source).length, ranges = docxClearRanges(value, textOf(source))
  let node = structuredClone(source)
  for (const range of ranges) {
    let offset = 0
    node.content = (node.content ?? []).flatMap(run => {
      const start = offset, stop = offset += run.text!.length
      const cuts = [...new Set([start, stop, Math.max(start, Math.min(stop, range.from)), Math.max(start, Math.min(stop, range.to))])].sort((a, b) => a - b)
      return cuts.slice(0, -1).map((at, index) => {
        const end = cuts[index + 1]!, part = { ...run, text: run.text!.slice(at - start, end - start) }
        if (at >= range.from && end <= range.to) delete part.marks
        return part
      })
    })
    // 应用样式时，覆盖超过半段的 B/I/U/strike 和四项字体属性按固定源规则整段移除。
    const counts = new Map<string, number>(), direct = ['bold', 'italic', 'underline', 'strike'], attrs = ['color', 'sizeHalfPoints', 'font', 'fontAscii']
    for (const run of node.content) for (const mark of run.marks ?? []) {
      if (direct.includes(mark.type)) counts.set(mark.type, (counts.get(mark.type) ?? 0) + run.text!.length)
      if (mark.type === 'docTextStyle') for (const key of attrs) if (mark.attrs?.[key] != null) counts.set(`ts:${key}`, (counts.get(`ts:${key}`) ?? 0) + run.text!.length)
    }
    const shed = new Set([...counts].filter(([, count]) => count * 2 > length).map(([key]) => key))
    for (const run of node.content) {
      run.marks = (run.marks ?? []).filter(mark => !shed.has(mark.type)).flatMap(mark => {
        if (mark.type !== 'docTextStyle') return [mark]
        const next = { ...mark, attrs: { ...mark.attrs } }
        for (const key of attrs) if (shed.has(`ts:${key}`)) next.attrs[key] = null
        return Object.values(next.attrs).some(v => v != null && v !== false) ? [next] : []
      })
      if (!run.marks.length) delete run.marks
    }
  }
  node.type = node.type === 'docHeading' ? 'docParagraph' : node.type
  node.attrs = { ...node.attrs, ...DOCX_CLEAR_PARAGRAPH_ATTRS, styleId: defaultStyleId }
  return schema.nodeFromJSON(node).toJSON() as DocxPmNode
}
export const PAGE_NUMBER_FORMATS = ['decimal', 'numberInDash', 'lowerLetter', 'upperLetter', 'lowerRoman', 'upperRoman', 'chineseCounting'] as const
export interface DocxSectionAnchor { headersFooters?: import('./docx-hf-sections').SectionHfModel; pageNumberFmt?: string | null; pageNumberStart?: number | null; pageNumberReadOnlyReason?: string; sectionId: string; expectedSectionSha256: string; settings: SectionSettings; firstBlockIndex?: number; lastBlockIndex?: number; titlePg?: boolean | null; titlePgReadOnlyReason?: string; evenAndOddHeaders?: boolean | null; evenAndOddHeadersReadOnlyReason?: string }
export const SECTION_BREAK_TYPES = ['nextPage', 'continuous', 'evenPage', 'oddPage'] as const
export type SectionBreakType = typeof SECTION_BREAK_TYPES[number]
export const SECTION_BREAK_LABELS: Record<SectionBreakType, string> = { nextPage: '分节符（下一页）', continuous: '分节符（连续）', evenPage: '分节符（偶数页）', oddPage: '分节符（奇数页）' }
/** 编辑器中的新分节符：与固定源一样以只读 docProtected 呈现，nativeSectionBreak 携带起始方式意图。 */
export function sectionBreakNode(type: SectionBreakType): DocxPmNode {
  return { type: 'docProtected', attrs: { blockType: 'passthrough', label: SECTION_BREAK_LABELS[type], previewText: '', nativeSectionBreak: type } }
}
/** 多节草稿：每节至多一条合并后的 setSectionLayout（节身份逐一校验）。 */
export function restoredDocxSectionOperations(operations: NativeOperation[], sections: readonly DocxSectionAnchor[]): NativeOperation[] {
  const byId = new Map(sections.map(section => [section.sectionId, section]))
  for (const operation of operations) if (operation.kind === 'setSectionLayout' && !byId.has(String(operation.sectionId))) throw new Error('草稿页面设置的节身份与当前来源不一致')
  return sections.flatMap(section => {
    const restored = restoredDocxSectionOperation(operations.filter(operation => operation.kind === 'setSectionLayout' && operation.sectionId === section.sectionId), section)
    if (typeof restored?.values.titlePg === 'boolean' && operations.some(operation => operation.kind === 'setHeaderFooter'
      && operation.sectionId === section.sectionId && typeof operation.titlePg === 'boolean' && operation.titlePg !== restored.values.titlePg)) {
      throw new Error('草稿同一节的首页不同设置冲突，请恢复一致的草稿后重试')
    }
    if (typeof restored?.values.evenAndOddHeaders === 'boolean' && operations.some(operation => operation.kind === 'setHeaderFooter'
      && typeof operation.evenAndOddHeaders === 'boolean' && operation.evenAndOddHeaders !== restored.values.evenAndOddHeaders)) {
      throw new Error('草稿文档级奇偶页不同设置冲突，请恢复一致的草稿后重试')
    }
    for (const key of ['pageNumberFmt', 'pageNumberStart'] as const) {
      if (restored && Object.hasOwn(restored.values, key) && operations.some(operation => operation.kind === 'setHeaderFooter'
        && operation.sectionId === section.sectionId && operation[key] !== undefined && operation[key] !== restored.values[key])) throw new Error('草稿同一节的页码格式设置冲突，请恢复一致的草稿后重试')
    }
    return restored ? [restored] : []
  })
}
export type SectionValues = Partial<Pick<SectionSettings, 'orientation' | 'pageWidth' | 'pageHeight' | 'marginTop' | 'marginRight' | 'marginBottom' | 'marginLeft' | 'columns' | 'headerDist' | 'footerDist' | 'pageBorder'>> & { pageBorderProps?: SectionSettings['pageBorderProps'] | null; titlePg?: boolean; evenAndOddHeaders?: boolean; pageNumberFmt?: string | null; pageNumberStart?: number | null }
export type SectionChangeResult = void | { error: string }
export function restoredDocxSectionOperation(operations: NativeOperation[], section?: DocxSectionAnchor) {
  let values: SectionValues | undefined
  const numericLimits: Record<string, [number, number]> = { pageWidth: [1440, 31680], pageHeight: [1440, 31680],
    marginTop: [0, 14400], marginRight: [0, 14400], marginBottom: [0, 14400], marginLeft: [0, 14400], columns: [1, 3], headerDist: [0, 31680], footerDist: [0, 31680] }
  for (const operation of operations) {
    if (operation.kind !== 'setSectionLayout') continue
    if (!section || operation.sectionId !== section.sectionId || operation.expectedSectionSha256 !== section.expectedSectionSha256) throw new Error('草稿页面设置的节身份与当前来源不一致')
    const patch = operation.values
    if (Object.keys(operation).some(key => !['kind', 'sectionId', 'expectedSectionSha256', 'values'].includes(key))
      || !patch || typeof patch !== 'object' || Array.isArray(patch) || !Object.keys(patch).length) throw new Error('草稿页面设置无效')
    // 固定源 Page Borders：pageBorder / pageBorderProps 整体按桥接同一规则校验
    if (!validDocxPageBorderValues(patch as Record<string, unknown>)) throw new Error('草稿页面边框设置无效')
    for (const [key, value] of Object.entries(patch)) {
      if (key === 'pageBorder' || key === 'pageBorderProps') continue
      if (key === 'orientation') { if (value !== 'portrait' && value !== 'landscape') throw new Error('草稿纸张方向无效') }
      else if (key === 'pageNumberFmt' || key === 'pageNumberStart') {
        if (!Object.hasOwn(section, key) || section[key] === undefined || section.pageNumberReadOnlyReason) throw new Error('草稿页码格式来源标记不可解释')
        if (value !== null && (key === 'pageNumberFmt' ? !PAGE_NUMBER_FORMATS.includes(value as typeof PAGE_NUMBER_FORMATS[number])
          : typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0)) throw new Error('草稿页码格式无效')
      }
      else if (key === 'titlePg') {
        if (typeof value !== 'boolean' || typeof section.titlePg !== 'boolean' || section.titlePgReadOnlyReason) throw new Error('草稿首页不同设置无效或来源标记不可解释')
      }
      else if (key === 'evenAndOddHeaders') {
        if (!Object.hasOwn(section, 'evenAndOddHeaders')) throw new Error('奇偶页不同须使用文档级设置身份')
        if (typeof value !== 'boolean' || typeof section.evenAndOddHeaders !== 'boolean' || section.evenAndOddHeadersReadOnlyReason) throw new Error('草稿奇偶页不同设置无效或来源标记不可解释')
      }
      else {
        const limit = numericLimits[key]
        if (!limit || typeof value !== 'number' || !Number.isInteger(value) || value < limit[0] || value > limit[1]) throw new Error('草稿页面设置数值无效')
      }
    }
    values = { ...values, ...patch }
  }
  if (!values || !section) return undefined
  if (!validDocxPageBorderValues(values as Record<string, unknown>)) throw new Error('草稿页面边框设置无效')
  const settings = { ...section.settings, ...values }
  if (settings.marginLeft + settings.marginRight >= settings.pageWidth || settings.marginTop + settings.marginBottom >= settings.pageHeight) throw new Error('草稿页边距超出纸张大小')
  return { kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values }
}
/** 一次原子更新所选节的页面边框；各节保留自己的其它页面设置。 */
export function docxPageBorderSectionOperations(operations: NativeOperation[], sections: readonly DocxSectionAnchor[], targetIndexes: readonly number[], props: SectionSettings['pageBorderProps'] | null): NativeOperation[] {
  const targets = new Set<number>()
  for (const index of targetIndexes) {
    if (!Number.isInteger(index) || index < 0 || index >= sections.length || targets.has(index)) throw new Error('草稿页面边框的节身份无效')
    targets.add(index)
  }
  if (!targets.size) throw new Error('草稿页面边框没有目标节')
  const targetIds = new Set([...targets].map(index => sections[index]!.sectionId))
  const next = operations.filter(operation => operation.kind !== 'setSectionLayout' || !targetIds.has(String(operation.sectionId)))
  for (const index of targets) {
    const section = sections[index]!
    const prior = restoredDocxSectionOperation(operations.filter(operation => operation.kind === 'setSectionLayout' && operation.sectionId === section.sectionId), section)
    const values: SectionValues = { ...prior?.values, pageBorder: props !== null, pageBorderProps: props }
    const layout = restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values }], section)
    if (layout) next.push(layout)
  }
  return restoredDocxSectionOperations(next, sections)
}
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const textOf = (node: DocxPmNode): string => node.text ?? (node.type === 'docHardBreak' ? '\n' : (node.content ?? []).map(textOf).join(''))
const paragraph = (node: DocxPmNode) => ['docParagraph', 'docHeading', 'docListItem'].includes(node.type)
const idOf = (node: DocxPmNode) => node.attrs?.docxIndex
const baseOp = (a: DocxAnchor) => ({ blockId: a.blockId, expectedObjectSha256: a.expectedObjectSha256 })
const withoutAlignment = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => key !== 'align'))
const withoutIndent = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['indentLeft', 'indentRight', 'indentFirstLine', 'indentFirstLineChars'].includes(key)))
const paragraphSpacingKeys = ['spaceBefore', 'spaceAfter', 'lineSpacing', 'lineRule', 'lineRawTwips', 'spaceBeforeAuto', 'spaceAfterAuto']
const withoutParagraphSpacing = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !paragraphSpacingKeys.includes(key)))
const withoutParagraphShading = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['shadingFill', 'shadingClear'].includes(key)))
const withoutParagraphBorders = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['borders', 'borderLines'].includes(key)))
const withoutPageBreakBefore = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => key !== 'pageBreakBefore'))
const withoutList = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['kind', 'numId', 'ilvl', 'nativeListDefinition', 'nativeNumberingBinding'].includes(key)))
const listOf = (node: DocxPmNode) => node.type === 'docListItem' ? { kind: node.attrs?.kind, numId: node.attrs?.numId, ilvl: node.attrs?.ilvl } : null
function structure(node: DocxPmNode, marks = true): unknown {
  const content: unknown[] = []
  for (const child of node.content ?? []) {
    if (child.type === 'text' && !marks) continue
    const shape = structure(child, marks)
    if (child.type === 'text' && content.length && same(content[content.length - 1], shape)) continue
    content.push(shape)
  }
  return { type: node.type, attrs: node.attrs, marks: marks ? node.marks : undefined, content }
}
const plainTyping = (run: DocxPmNode) => (run.marks ?? []).every(mark => mark.type === 'textStyle' && Object.values(mark.attrs ?? {}).every(value => value == null || value === false))
/** 单元格只改文字：段落结构与属性不变；有文字的段落保持 run 格式，空段落（如新建表格的空格子）只允许新增普通文字。 */
export function cellTextEditOnly(cell: DocxPmNode, changed: DocxPmNode): boolean {
  if (!same(structure(cell, false), structure(changed, false))) return false
  return (cell.content ?? []).every((left, index) => {
    const right = changed.content![index]
    if (same(structure(left), structure(right))) return true
    return !(left.content ?? []).some(run => run.type === 'text') && (right.content ?? []).every(run => run.type !== 'text' || plainTyping(run))
  })
}
/** Cells a restructured table changed only by text, at final coordinates; anything else is refused. */
export function restructuredTableTexts(projected: DocxPmNode, edited: DocxPmNode): { row: number; column: number; text: string }[] {
  if (!same(projected.attrs, edited.attrs) || projected.content?.length !== edited.content?.length) throw new Error('表格结构修改后暂不支持同时修改表格属性')
  const texts: { row: number; column: number; text: string }[] = []
  projected.content!.forEach((left, row) => {
    const right = edited.content![row]!
    if (!same(left.attrs, right.attrs) || left.content?.length !== right.content?.length) throw new Error('表格结构修改后暂不支持同时修改行属性')
    left.content!.forEach((cell, column) => {
      const changed = right.content![column]!
      if (same(cell, changed)) return
      if (!cellTextEditOnly(cell, changed)) throw new Error('表格结构修改后单元格只支持修改文字')
      texts.push({ row, column, text: (changed.content ?? []).map(textOf).join('\n') })
    })
  })
  return texts
}
function markSequence(node: DocxPmNode): unknown[] {
  const result: unknown[] = []
  for (const run of node.content ?? []) if (run.type === 'text') {
    const marks = run.marks ?? []
    if (!result.length || !same(result[result.length - 1], marks)) result.push(marks)
  }
  return result
}
export function safeDocxLink(value: unknown): string {
  if (typeof value !== 'string') throw new Error('请输入有效的链接地址')
  const href = value.trim()
  if (!href || href.length > 4096 || /[\s\u0000-\u001f\u007f]/u.test(href)) throw new Error('链接地址不能包含空白或控制字符')
  let url: URL
  try { url = new URL(href) } catch { throw new Error('仅支持完整的 http、https 或 mailto 链接') }
  if (!['http:', 'https:', 'mailto:'].includes(url.protocol) || (url.protocol !== 'mailto:' && !/^https?:\/\//i.test(href)) || url.username || url.password
    || (url.protocol === 'mailto:' && (!url.pathname || url.pathname.startsWith('//')))) throw new Error('仅支持安全的 http、https 或 mailto 链接')
  return href
}
export function validDocxLinkRange(text: string, from: unknown, to: unknown): boolean {
  const boundary = (at: number) => !(at > 0 && at < text.length && /[\uD800-\uDBFF]/.test(text[at - 1]) && /[\uDC00-\uDFFF]/.test(text[at]))
  return typeof from === 'number' && typeof to === 'number' && Number.isInteger(from) && Number.isInteger(to)
    && from >= 0 && to > from && to <= text.length && boundary(from) && boundary(to)
}
const withoutLinks = (node: DocxPmNode): DocxPmNode => ({ ...node, content: node.content?.map(run => ({ ...run, marks: (run.marks ?? []).filter(mark => mark.type !== 'link') })) })
/** 保存协议开放的粘贴图片格式（引擎 NewImage 另支持 gif，粘贴不开放） */
export const DOCX_PASTE_IMAGE_MIMES = ['image/png', 'image/jpeg'] as const
export const DOCX_PASTE_IMAGE_MAX_BYTES = 8 * 1024 * 1024
export const DOCX_PASTE_IMAGE_MAX_EDGE_PX = 10000
export interface DocxPastedImage { mime: (typeof DOCX_PASTE_IMAGE_MIMES)[number]; base64: string; widthPx: number; heightPx: number }
const CANONICAL_BASE64 = /^[A-Za-z0-9+/]+={0,2}$/
/** 新插入粘贴图片节点（docProtected/genImage）的协议内载荷；null = 非图片新增节点。 */
export function pastedDocxImage(node: DocxPmNode): DocxPastedImage | null {
  if (node.type !== 'docProtected' || node.attrs?.blockType !== 'image') return null
  const gen = node.attrs.genImage as Record<string, unknown> | null | undefined
  if (!gen || typeof gen !== 'object' || Array.isArray(gen)) throw new Error('新增图片缺少可保存的图片数据')
  if (Object.keys(gen).some(key => !['mime', 'base64', 'widthPx', 'heightPx'].includes(key))) throw new Error('新增图片数据包含不支持的字段')
  if (!(DOCX_PASTE_IMAGE_MIMES as readonly string[]).includes(String(gen.mime))) throw new Error('仅支持粘贴 PNG 或 JPEG 图片')
  const base64 = gen.base64
  if (typeof base64 !== 'string' || !base64.length || base64.length % 4 !== 0 || !CANONICAL_BASE64.test(base64)
    || base64.length > Math.ceil(DOCX_PASTE_IMAGE_MAX_BYTES / 3) * 4) throw new Error('粘贴图片数据无效或超过 8MB 大小上限')
  let rawLength = 0
  try { rawLength = atob(base64).length } catch { throw new Error('粘贴图片数据不是有效的 base64') }
  if (rawLength < 1 || rawLength > DOCX_PASTE_IMAGE_MAX_BYTES) throw new Error('粘贴图片超过 8MB 大小上限')
  for (const key of ['widthPx', 'heightPx'] as const) {
    const value = gen[key]
    if (!Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > DOCX_PASTE_IMAGE_MAX_EDGE_PX) throw new Error('粘贴图片的显示尺寸超出可保存范围')
  }
  return { mime: gen.mime as DocxPastedImage['mime'], base64, widthPx: Number(gen.widthPx), heightPx: Number(gen.heightPx) }
}
function draftImagePayload(value: unknown): DocxPastedImage {
  const gen = value
  if (!gen || typeof gen !== 'object' || Array.isArray(gen)) throw new Error('草稿图片粘贴数据无效')
  return pastedDocxImage({ type: 'docProtected', attrs: { blockType: 'image', genImage: gen } })
    ?? (() => { throw new Error('草稿图片粘贴数据无效') })()
}
function linkMap(node: DocxPmNode): (string | null)[] {
  return (node.content ?? []).flatMap(run => Array.from({ length: textOf(run).length }, () => {
    const marks = (run.marks ?? []).filter(mark => mark.type === 'link')
    if (marks.length > 1) throw new Error('链接标记无效')
    return marks.length ? safeDocxLink(marks[0].attrs?.href) : null
  }))
}
function linkMetadata(node: DocxPmNode) {
  return (node.content ?? []).flatMap(run => Array.from({ length: textOf(run).length }, () => {
    const attrs = run.marks?.find(mark => mark.type === 'link')?.attrs
    return attrs ? { tooltip: attrs.tooltip ?? null, plain: attrs.plain ?? false } : undefined
  }))
}
function compatibleLinkGroups(node: DocxPmNode) {
  let previous: Record<string, unknown> | undefined
  for (const run of node.content ?? []) {
    const link = run.marks?.find(mark => mark.type === 'link')?.attrs
    if (link && previous && link.href === previous.href && !(link.rId && previous.rId && link.rId !== previous.rId)) {
      if ((link.tooltip ?? '') !== (previous.tooltip ?? '')) throw new Error('相邻同地址链接的提示不同，暂不支持此链接修改')
      previous = { ...previous, rId: previous.rId ?? link.rId }
    } else previous = link
  }
}
/** Split only targeted text; keep every unrelated mark and link attribute unchanged. */
function applyLink(node: DocxPmNode, from: number, to: number, href: string | null) {
  if ((node.content ?? []).some(run => run.type !== 'text')) throw new Error('含复杂内联对象的段落暂不支持链接修改')
  let offset = 0
  node.content = (node.content ?? []).flatMap(run => {
    const start = offset, end = offset += (run.text ?? '').length
    const cuts = [start, ...[from, to].filter(at => at > start && at < end), end].sort((a, b) => a - b)
    return cuts.slice(0, -1).map((at, index) => {
      const next = { ...run, text: run.text!.slice(at - start, cuts[index + 1] - start) }
      if (at >= from && at < to) next.marks = [...(run.marks ?? []).filter(mark => mark.type !== 'link'), ...(href === null ? [] : [{ type: 'link', attrs: { ...run.marks?.find(mark => mark.type === 'link')?.attrs, href, rId: null } }])]
      return next
    })
  })
  compatibleLinkGroups(node)
}
function runStyle(run: DocxPmNode): Record<string, unknown> {
  const style: Record<string, unknown> = { bold: false, italic: false, underline: false, strike: false, vertAlign: 'baseline' }
  for (const mark of run.marks ?? []) {
    if (['bold', 'italic', 'underline', 'strike'].includes(mark.type)) style[mark.type] = true
    else if (mark.type === 'textStyle' || mark.type === 'docTextStyle') for (const [key, value] of Object.entries(mark.attrs ?? {})) {
      if (value == null || value === false) continue
      if (key === 'styleId') style.styleId = value
      else if (key === 'color') style.color = String(value).replace(/^#/, '')
      else if (key === 'sizeHalfPoints' || key === 'fontSize') style.fontSize = key === 'sizeHalfPoints' ? Number(value) / 2 : Number(value)
      else if (key === 'highlight') style.highlight = safeDocxHighlight(value)
      else if (key === 'vertAlign') {
        if (!['baseline', 'superscript', 'subscript'].includes(String(value))) throw new Error('文字上下标状态无效')
        style.vertAlign = value
      }
      else if (key === 'font' || key === 'fontFamily') style.fontFamily = value
      else if (['fontAscii', 'eastAsiaFont', 'fontCs', 'csFont', 'themeRFonts'].includes(key)) style[`font-slot:${key}`] = value
      else style[`unsupported:${key}`] = value
    }
    else style[`unsupported-mark:${mark.type}`] = mark
  }
  return style
}
/** FontDialog preserves separate authored slots; computed display twins do not enter the wire style. */
function fontDialogRunStyle(run: DocxPmNode): Record<string, unknown> {
  const basic = runStyle({ ...run, marks: (run.marks ?? []).map(mark => !['textStyle', 'docTextStyle'].includes(mark.type) ? mark : { ...mark, attrs: Object.fromEntries(Object.entries(mark.attrs ?? {}).filter(([key]) => ![...DOCX_FONT_PROPERTIES, ...DOCX_FONT_DISPLAY, 'font', 'fontFamily'].includes(key as never))) }) })
  const attrs = run.marks?.find(mark => ['textStyle', 'docTextStyle'].includes(mark.type))?.attrs ?? {}
  for (const key of DOCX_FONT_PROPERTIES) basic[key] = attrs[key] ?? (key === 'eastAsiaFont' ? attrs.eaSlotEmpty ? null : attrs.font ?? attrs.fontFamily ?? null : null)
  return basic
}
function fontDialogRangeChanges(node: DocxPmNode, edited: DocxPmNode) {
  const expand = (paragraph: DocxPmNode) => (paragraph.content ?? []).flatMap(run => run.type === 'text' ? Array.from({ length: (run.text ?? '').length }, () => fontDialogRunStyle(run)) : [])
  const before = expand(node), after = expand(edited)
  if (before.length !== after.length) throw new Error('局部格式修改要求段落文字不变')
  const expandAttrs = (paragraph: DocxPmNode) => (paragraph.content ?? []).flatMap(run => Array.from({ length: (run.text ?? '').length }, () => run.marks?.find(mark => ['docTextStyle','textStyle'].includes(mark.type))?.attrs ?? {}))
  const beforeAttrs = expandAttrs(node), afterAttrs = expandAttrs(edited)
  const segments: { from: number; to: number; style: Record<string, unknown> }[] = []
  after.forEach((value, at) => {
    const old = before[at]!
    for (const key of new Set([...Object.keys(old), ...Object.keys(value)])) if ((key.startsWith('unsupported') || key.startsWith('font-slot:')) && !same(old[key], value[key])) throw new Error('此文字样式暂不支持保存')
    for (const key of ['color','fontSize','styleId']) if (key in old && !(key in value)) value[key] = null
    if ('highlight' in old && !('highlight' in value)) value.highlight = 'none'
    const delta = Object.fromEntries(Object.entries(value).filter(([key,v]) => !key.startsWith('unsupported') && !key.startsWith('font-slot:') && !same(old[key],v)))
    for (const [derived,authored] of [['kern','kernHalfPoints'],['charScaleEm','charScalePct']]) if (!same(beforeAttrs[at]![derived!],afterAttrs[at]![derived!])) delta[authored!] = value[authored!] ?? null
    if (!Object.keys(delta).length) return
    docxFontProperties(delta); delta.fontDialog = true
    const last = segments.at(-1)
    if (last && last.to === at && same(last.style,delta)) last.to++
    else segments.push({ from: at, to: at + 1, style: delta })
  })
  return segments
}
function fontDialogStyleKeys(style: Record<string, unknown>) {
  if ('fontDialog' in style && style.fontDialog !== true) throw new Error('草稿字体模式无效')
  if (style.fontDialog === true) docxFontProperties(style)
  if ('styleId' in style && style.styleId !== null && (typeof style.styleId !== 'string' || !style.styleId || style.styleId.length > 255 || /[\x00-\x1f\x7f]/.test(style.styleId))) throw new Error('字符样式标识无效')
  return ['bold','italic','underline','strike','fontSize','fontFamily','color','highlight','vertAlign','styleId', ...(style.fontDialog === true ? ['fontDialog', ...DOCX_FONT_PROPERTIES] : [])]
}
function replayFontDialog(run: DocxPmNode, style: Record<string, unknown>) {
  if (style.fontDialog !== true) return
  let mark = run.marks!.find(item => ['docTextStyle','textStyle'].includes(item.type))
  if (!mark) { mark = { type: 'docTextStyle', attrs: {} }; run.marks!.push(mark) }
  mark.attrs = fontDialogMarkAttrs(mark.attrs ?? {}, style, run.text ?? '')
}
/** 文字不变时的局部字符格式差分：按 UTF-16 偏移给出最小变化区间（每段变化键与新值相同）。 */
export function formatRangeChanges(node: DocxPmNode, edited: DocxPmNode): { from: number; to: number; style: Record<string, unknown> }[] {
  if ((edited.content ?? []).some(run => run.marks?.some(mark => mark.attrs?.nativeFontDialog === true))) return fontDialogRangeChanges(node, edited)
  const expand = (paragraph: DocxPmNode) => (paragraph.content ?? []).flatMap(run => run.type === 'text'
    ? Array.from({ length: (run.text ?? '').length }, () => runStyle(run)) : [])
  const before = expand(node), after = expand(edited)
  if (before.length !== after.length) throw new Error('局部格式修改要求段落文字不变')
  const segments: { from: number; to: number; style: Record<string, unknown> }[] = []
  after.forEach((style, at) => {
    const old = before[at]!
    const changedSlots = ['eastAsiaFont', 'fontAscii'].filter(key => !same(old[`font-slot:${key}`], style[`font-slot:${key}`]))
    if (changedSlots.length > 1 && changedSlots.some(key => style[`font-slot:${key}`] != null)) throw new Error('同一区间同时修改中西文字体请分别保存')
    if (changedSlots.length) style.fontFamily = style[`font-slot:${changedSlots[0]}`] ?? style.fontFamily ?? null
    for (const key of ['fontCs', 'csFont', 'themeRFonts']) if (!same(old[`font-slot:${key}`], style[`font-slot:${key}`])
      && !(style[`font-slot:${key}`] == null && style.fontFamily == null && style['font-slot:fontAscii'] == null && style['font-slot:eastAsiaFont'] == null)) throw new Error('此文字样式暂不支持保存')
    for (const key of new Set([...Object.keys(old), ...Object.keys(style)])) if (key.startsWith('unsupported') && !same(old[key], style[key])) throw new Error('此文字样式暂不支持保存')
    if ('highlight' in old && !('highlight' in style)) style.highlight = 'none'
    for (const key of ['color', 'fontFamily', 'fontSize', 'styleId']) if (key in old && !(key in style)) style[key] = null
    const delta = Object.fromEntries(Object.entries(style).filter(([key, value]) => !key.startsWith('unsupported') && !key.startsWith('font-slot:') && (!same(value, old[key]) || key === 'fontFamily' && changedSlots.length > 0)))
    const last = segments[segments.length - 1]
    if (!Object.keys(delta).length) return
    if (last && last.to === at && same(last.style, delta)) last.to = at + 1
    else segments.push({ from: at, to: at + 1, style: delta })
  })
  return segments
}
function styleOf(node: DocxPmNode): Record<string, unknown> {
  const runs = (node.content ?? []).filter(child => child.type === 'text')
  if (!runs.length) throw new Error('空段落暂不支持样式修改')
  const styles = runs.map(run => {
    const style: Record<string, unknown> = { bold: false, italic: false, underline: false, strike: false }
    for (const mark of run.marks ?? []) {
      if (['bold', 'italic', 'underline', 'strike'].includes(mark.type)) style[mark.type] = true
      else if (mark.type === 'textStyle' || mark.type === 'docTextStyle') for (const [key, value] of Object.entries(mark.attrs ?? {})) {
        if (value == null || value === false) continue
        if (key === 'color') style.color = String(value).replace(/^#/, '')
        else if (key === 'sizeHalfPoints' || key === 'fontSize') style.fontSize = key === 'sizeHalfPoints' ? Number(value) / 2 : Number(value)
        else if (key === 'font' || key === 'fontFamily') style.fontFamily = value
        else throw new Error('此文字样式暂不支持保存')
      }
      else throw new Error('此文字样式暂不支持保存')
    }
    return style
  })
  if (!styles.every(style => same(style, styles[0]))) throw new Error('暂不支持同段落内局部样式修改，请选择整个段落')
  return styles[0]
}
/** 原始XML和资源路径从不进入保存协议；变化仅映射为后端允许操作。 */
export function docxOperations(original: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[], sectionOperation?: NativeOperation | NativeOperation[], schema?: Schema, styles?: Map<string, DocxStyleInfo>, headerFooterOperations?: NativeOperation[]): NativeOperation[] {
  const dropCaps = normalizeDocxDropCaps(original, current, anchors)
  current = dropCaps.current
  const revisions = normalizeDocxTextRevisions(original, current, anchors, schema)
  current = revisions.current
  const nested = normalizeDocxNestedTables(original, current, anchors)
  current = nested.current
  // 表格样式为整表独占写回：先校验并还原为来源，后续差异比对不再看到该表的样式/预设变化。
  const tableStyle = normalizeDocxTableStyle(original, current, anchors)
  current = tableStyle.current
  // 先从原始身份投影边框，再剥离与边框可交换的fill；最终边框投影仍完整核验。
  const borderBaseline = projectedDocxCellBordersBaseline(original, current, anchors)
  const shading = normalizeDocxCellShading(borderBaseline, current, anchors)
  const cellBorders = normalizeDocxCellBorders(original, shading.current, anchors)
  current = cellBorders.current
  const before = original.content ?? [], after = current.content ?? []
  const byIndex = new Map(anchors.map(anchor => [anchor.docxIndex, anchor]))
  const retained = after.filter(node => idOf(node) != null)
  const positions = retained.map(node => before.findIndex(item => idOf(item) === idOf(node)))
  if (positions.some(index => index < 0) || new Set(retained.map(idOf)).size !== retained.length) throw new Error('文档锚点无效')
  if (positions.some((value, index) => index > 0 && value <= positions[index - 1])) throw new Error('暂不支持改变原对象顺序')
  const ops: NativeOperation[] = [...dropCaps.operations]
  for (let index = 0; index < after.length; index++) {
    const node = after[index]
    if (idOf(node) != null) continue
    const pastedImage = pastedDocxImage(node)
    if (pastedImage) {
      // 粘贴图片与 insertParagraph 同锚点语义：贴在最近的可编辑正文段前/后。
      const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const target = next ?? previous ?? fallback
      if (!target) throw new Error('新增图片没有可编辑的锚点段落')
      ops.push({ kind: 'insertParagraphImage', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', image: pastedImage })
      continue
    }
    if (node.attrs?.nativeCoverPage != null) {
      // 新增封面（docx-cover-page.ts）：必须位于文档开头，首段至分页结束段为一组，
      // 按首段携带的预设规格 + 当前各段文字重算投影并完全一致。
      if (!schema) throw new Error('新增封面需要编辑器结构信息')
      const end = after.findIndex((item, at) => at >= index && isCoverEndNode(item))
      if (index !== 0 || end < 0 || after.slice(index, end + 1).some(item => idOf(item) != null)) throw new Error('封面结构已改变，请删除后重新插入')
      const group = after.slice(index, end + 1)
      let paras: ReturnType<typeof coverGroupParas>
      try { paras = coverGroupParas(group) } catch { throw new Error('封面结构已改变，请删除后重新插入') }
      if (!coverGroupMatchesProjection(group, projectCoverNodes(paras, schema))) throw new Error('封面保存前只能修改占位文字；格式或段落修改请先保存')
      const target = after.slice(end + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      if (!target) throw new Error('封面后没有可编辑的锚点段落')
      ops.push({ kind: 'insertCoverPage', ...baseOp(byIndex.get(Number(idOf(target)))!), position: 'before', paras })
      index = end
      continue
    }
    if (node.attrs?.nativeSectionBreak != null) {
      // 新增分节符：紧跟其前的原有块为锚点（分节段插在锚点之后，终止此前内容所在的新节）。
      const type = node.attrs.nativeSectionBreak as SectionBreakType
      const previous = after[index - 1]
      if (node.type !== 'docProtected' || !SECTION_BREAK_TYPES.includes(type)) throw new Error('分节符意图无效，请删除后重新插入')
      if (!previous || idOf(previous) == null || !byIndex.get(Number(idOf(previous)))) throw new Error('分节符须紧跟在原有段落或表格之后，请先保存再继续插入')
      ops.push({ kind: 'insertSectionBreak', ...baseOp(byIndex.get(Number(idOf(previous)))!), type })
      continue
    }
    if (node.type === 'docTable') {
      // 新增表格（docx-new-table.ts）：必须仍是按行列意图确定性投影出的空表。
      if (!schema) throw new Error('新增表格需要编辑器结构信息')
      let size: { rows: number; cols: number }
      try { size = newTableSize(node.attrs?.nativeTableInsert) } catch { throw new Error('只支持通过“插入表格”新建的表格；粘贴或复制的表格暂不支持保存') }
      const cells = newTableNodeCells(node)
      const typed = cells.some(row => row.some(text => text !== ''))
      let expected: DocxPmNode | undefined
      try { expected = projectNewDocxTable(size, schema, cells) } catch { expected = undefined }
      if (!expected || !newTableMatchesProjection(node, expected)) throw new Error('新增表格保存前只能输入纯文字；格式或布局修改请先保存')
      const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const target = next ?? previous ?? fallback
      if (!target) throw new Error('新增表格没有可编辑的锚点段落')
      ops.push({ kind: 'insertTable', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', rows: size.rows, cols: size.cols, ...(typed ? { cells } : {}) })
      continue
    }
    if (node.attrs?.styleId != null) throw new Error('新增段落请保存后再修改段落样式')
    if (node.attrs?.align != null) throw new Error('新增段落请保存后再修改对齐方式')
    if (node.attrs?.indentLeft != null) throw new Error('新增段落请保存后再修改缩进')
    if (node.type !== 'docParagraph' || (node.content ?? []).some(child => child.type !== 'text' || (child.marks ?? []).some(mark => mark.type !== 'textStyle' || Object.values(mark.attrs ?? {}).some(value => value != null && value !== false)))) throw new Error('新增段落暂只支持普通文字，请保存后再修改样式')
    const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const target = next ?? previous ?? fallback
    if (!target) throw new Error('新增段落没有可编辑的锚点')
    ops.push({ kind: 'insertParagraph', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', text: textOf(node), ...(node.attrs?.pageBreakBefore === true ? { pageBreakBefore: true } : {}), ...(node.attrs?.dropCap != null ? { dropCap: docxDropCapAttribute(node.attrs.dropCap) } : {}) })
  }
  for (const node of before) {
    const anchor = byIndex.get(Number(idOf(node)))
    if (!anchor) throw new Error('文档锚点无效')
    const edited = after.find(item => idOf(item) === idOf(node))
    if (edited && same(node, edited) && ['spaceBefore', 'spaceAfter'].every(key => Object.is(node.attrs?.[key], edited.attrs?.[key]))) continue
    if (!edited) {
      // deletable：可编辑段落，或仅含图库封面隐藏书签的封面段（整段删除/替换已保存封面）。
      if (!(anchor.deletable ?? anchor.editable) || !paragraph(node)) throw new Error('只读对象不能删除')
      ops.push({ kind: 'deleteParagraph', ...baseOp(anchor) }); continue
    }
    if (node.type === 'docTable' && edited.type === 'docTable') {
      if (edited.attrs?.nativeTableProperties) {
        const patch=edited.attrs.nativeTableProperties
        if(!same(edited,projectDocxTableProperties(node,anchor,patch,schema)))throw new Error('表格属性含未授权的正文或格式修改')
        ops.push({kind:'formatTableProperties',...baseOp(anchor),patch});continue
      }
      if (edited.attrs?.nativeTableCellParagraphProperties) {
        ops.push(docxTableCellParagraphPropertiesOperation(node, edited, anchor, schema)); continue
      }
      if (edited.attrs?.nativeTableAltText) {
        const value = edited.attrs.nativeTableAltText as { title: string; description: string }
        if (!same(edited, projectDocxTableAltText(node, anchor, value, schema))) throw new Error('表格标题/说明不能与同表文字、格式或其他修改混用，请先保存')
        ops.push({ kind: 'setTableAltText', ...baseOp(anchor), title: value.title, description: value.description }); continue
      }
      if (edited.attrs?.nativeTableCellWrap) {
        const intent = edited.attrs.nativeTableCellWrap as { steps: TableCellWrapStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxCellWrap(node, anchor, intent.steps, schema))) throw new Error('单元格自动换行不能与同表文字、格式或其他修改混用，请先保存')
        ops.push({ kind: 'setTableCellWrap', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableAlignment) {
        const intent = edited.attrs.nativeTableAlignment as { alignment: TableAlignment }
        if (Object.keys(intent).some(key => key !== 'alignment') || !same(edited, projectDocxTableAlignment(node, anchor, intent.alignment, schema))) throw new Error('整表对齐不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableAlignment', ...baseOp(anchor), alignment: intent.alignment }); continue
      }
      if (edited.attrs?.nativeTableRowBreaks) {
        const intent = edited.attrs.nativeTableRowBreaks as { steps: TableRowBreakStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxRowBreaks(node, anchor, intent.steps, schema))) throw new Error('行跨页设置不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableRowBreaks', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableCellMarginOverrides) {
        const intent = edited.attrs.nativeTableCellMarginOverrides as { steps: TableCellMarginOverrideStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxCellMarginOverrides(node, anchor, intent.steps, schema))) throw new Error('单格边距不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableCellMarginOverrides', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableCellMargins) {
        const intent = edited.attrs.nativeTableCellMargins as { margins: Parameters<typeof projectDocxCellMargins>[2] }
        if (Object.keys(intent).some(key => key !== 'margins') || !same(edited, projectDocxCellMargins(node, anchor, intent.margins, schema))) throw new Error('单元格默认边距不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableCellMargins', ...baseOp(anchor), margins: intent.margins }); continue
      }
      if (edited.attrs?.nativeTableCellAlignment) {
        const intent = edited.attrs.nativeTableCellAlignment as { steps: TableCellAlignmentStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxCellAlignment(node, anchor, intent.steps, schema))) throw new Error('单元格对齐不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableCellAlignment', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableCellTextDirection) {
        const intent = edited.attrs.nativeTableCellTextDirection as { steps: TableCellTextDirectionStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxCellTextDirection(node, anchor, intent.steps, schema))) throw new Error('文字方向不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableCellTextDirection', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableAutoFit) {
        const intent = edited.attrs.nativeTableAutoFit as { steps: TableAutoFitStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxAutoFit(node, anchor, intent.steps, schema))) throw new Error('自动调整不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableAutoFit', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableRowHeights) {
        const intent = edited.attrs.nativeTableRowHeights as { steps: TableRowHeightStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxRowHeights(node, anchor, intent.steps, schema))) throw new Error('行高不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'setTableRowHeights', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableColumnWidths) {
        const intent = edited.attrs.nativeTableColumnWidths as { steps: TableColumnWidthStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxColumnWidths(node, anchor, intent.steps, schema))) throw new Error('列宽不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'resizeTableColumns', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if (edited.attrs?.nativeTableCellShape) {
        const intent = edited.attrs.nativeTableCellShape as { steps: TableCellShapeStep[] }
        if (Object.keys(intent).some(key => key !== 'steps') || !same(edited, projectDocxCellShape(node, anchor, intent.steps, schema))) throw new Error('合并拆分不能与同表文字、格式或其他结构修改混用，请先保存')
        ops.push({ kind: 'reshapeTableCells', ...baseOp(anchor), steps: intent.steps }); continue
      }
      if ((edited.content??[]).some((row,index)=>row.attrs?.repeatHeaderEdited && (!!row.attrs?.repeatHeader!==!!node.content?.[index]?.attrs?.repeatHeader || row.attrs?.repeatHeaderEdited!==node.content?.[index]?.attrs?.repeatHeaderEdited))) {
        const op=tableHeaderOperation(node,edited,anchor);if(op)ops.push(op);continue
      }
      const structureIntent = edited.attrs?.nativeTableStructure
      if (structureIntent && typeof structureIntent === 'object' && 'steps' in structureIntent) {
        // 多步行列增删 + 文字：一次 restructureTable（步骤坐标逐步推进，文字按最终坐标）。
        const steps = tableSteps(structureIntent)
        const texts = restructuredTableTexts(projectDocxTableSteps(node, anchor, steps, schema), edited)
        ops.push({ kind: 'restructureTable', ...baseOp(anchor), steps, ...(texts.length ? { texts } : {}) }); continue
      }
      if (edited.attrs?.nativeTableStructure) {
        const intent = tableIntent(edited.attrs.nativeTableStructure)
        if (!same(edited, projectDocxTable(node, anchor, intent, schema))) throw new Error('表格结构修改后请先保存；同表文字、格式或第二次结构修改不能混用')
        ops.push({ ...baseOp(anchor), ...intent }); continue
      }
      if (!same(node.attrs, edited.attrs) || node.content?.length !== edited.content?.length) throw new Error('暂不支持修改表格布局')
      for (let row = 0; row < (node.content?.length ?? 0); row++) {
        const left = node.content![row], right = edited.content![row]
        if (!same(left.attrs, right.attrs) || left.content?.length !== right.content?.length) throw new Error('暂不支持修改表格布局')
        for (let col = 0; col < (left.content?.length ?? 0); col++) {
          const cell = left.content![col], changed = right.content![col]
          if (same(cell, changed)) continue
          const cellAnchor = anchor.cells?.[row]?.[col]
          if (!cellAnchor?.editable) throw new Error('只读单元格不能修改')
          if (!cellTextEditOnly(cell, changed)) throw new Error('暂不支持修改单元格结构或样式')
          ops.push({ kind: 'replaceCellText', blockId: anchor.blockId, cellId: cellAnchor.cellId, expectedObjectSha256: cellAnchor.expectedObjectSha256, text: (changed.content ?? []).map(textOf).join('\n') })
        }
      }
      continue
    }
    if (edited.attrs?.nativeParagraphProperties != null) {
      ops.push(docxParagraphPropertiesOperation(node, edited, anchor, schema)); continue
    }
    if (edited.attrs?.nativeTabStops != null) {
      const operation = docxTabStopsOperation(node, edited, anchor)
      if (operation) ops.push(operation)
      continue
    }
    if (edited.attrs?.nativeRulerIndent != null) {
      const operation = docxRulerIndentOperation(node, edited, anchor)
      if (operation) ops.push(operation)
      continue
    }
    if (edited.attrs?.nativeClearFormatting) {
      const intent = edited.attrs.nativeClearFormatting as { ranges?: unknown }
      if (!anchor.editable || !schema || !paragraph(node) || Object.keys(intent).some(key => key !== 'ranges')) throw new Error('清除格式来源或意图无效')
      const ranges = docxClearRanges(intent.ranges, textOf(node))
      const styleId = [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId ?? null
      const projected = projectClearedDocxParagraph(node, ranges, styleId, schema)
      projected.attrs = { ...projected.attrs, nativeClearFormatting: { ranges } }
      if (!same(edited, projected)) throw new Error('清除格式与同段其他修改不能混用，请先保存')
      ops.push({ kind: 'clearParagraphFormatting', ...baseOp(anchor), ranges }); continue
    }
    if (edited.attrs?.nativeRibbonStyle != null && edited.attrs.nativeRibbonStyle !== true) throw new Error('Ribbon样式意图无效')
    if (edited.attrs?.nativeRibbonStyle === true) {
      if (!schema || !anchor.editable || !(anchor.paragraphStyleEditable ?? anchor.editable) || node.type !== 'docParagraph') throw new Error('此来源段落暂不支持Ribbon样式')
      safeParagraphStyle(styles, edited.attrs.styleId)
      const sourceStyle = node.attrs?.styleId ?? [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceStyle != null) safeParagraphStyle(styles, sourceStyle)
      if (!same(edited, projectRibbonStyle(node, String(edited.attrs.styleId), schema))) throw new Error('Ribbon样式与同段其他修改不能混用')
      ops.push({ kind: 'setParagraphStyle', ...baseOp(anchor), styleId: edited.attrs.styleId, ribbon: true }); continue
    }
    if (!same(node.attrs?.styleId ?? null, edited.attrs?.styleId ?? null)) {
      if (!(anchor.paragraphStyleEditable ?? anchor.editable) || node.type !== 'docParagraph' || edited.type !== 'docParagraph' || anchor.paragraphStyleEditable === false) throw new Error('此来源段落暂不支持切换样式')
      safeParagraphStyle(styles, edited.attrs?.styleId)
      const sourceStyle = node.attrs?.styleId ?? [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceStyle != null) safeParagraphStyle(styles, sourceStyle)
      if (!same(node, { ...edited, attrs: { ...edited.attrs, styleId: node.attrs?.styleId } })) throw new Error('段落样式修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphStyle', ...baseOp(anchor), styleId: edited.attrs!.styleId })
      continue
    }
    if (!anchor.editable) throw new Error('只读对象不能修改')
    const beforeList = listOf(node), afterList = listOf(edited)
    const customDefinition = edited.attrs?.nativeListDefinition == null ? null : normalizeDocxCustomList(edited.attrs.nativeListDefinition)
    const numberingBinding = edited.attrs?.nativeNumberingBinding == null ? null : normalizeDocxNumberingBinding(edited.attrs.nativeNumberingBinding)
    if (numberingBinding) {
      if (customDefinition || !paragraph(node) || edited.type !== 'docListItem' || edited.attrs?.numId !== docxNumberingBindingId(numberingBinding)
        || !Number.isInteger(edited.attrs?.ilvl) || Number(edited.attrs?.ilvl) < 0 || Number(edited.attrs?.ilvl) > 8) throw new Error('编号值段落绑定无效')
      const previous = ops.find(op => op.kind === 'setParagraphNumberingValue' && (op.binding as { id: string }).id === numberingBinding.id)
      if (previous && !same(previous.binding, numberingBinding)) throw new Error('同一编号值定义存在冲突')
      ops.push({ kind: 'setParagraphNumberingValue', ...baseOp(anchor), binding: numberingBinding, ilvl: edited.attrs!.ilvl, listKind: edited.attrs!.kind })
    }
    if (customDefinition) {
      if (!paragraph(node) || edited.type !== 'docListItem' || !same(afterList, customListLevel(customDefinition, edited.attrs?.ilvl))) throw new Error('多级列表段落绑定无效')
      const previous = ops.find(op => op.kind === 'setParagraphCustomList' && op.definitionId === customDefinition.id)
      if (previous && !same(previous.levels, customDefinition.levels)) throw new Error('同一多级列表定义存在冲突')
      ops.push({ kind: 'setParagraphCustomList', ...baseOp(anchor), definitionId: customDefinition.id, levels: customDefinition.levels, ilvl: edited.attrs!.ilvl })
    }
    const listLevelChanged = node.type === 'docListItem' && edited.type === 'docListItem'
      && beforeList?.numId === afterList?.numId && beforeList?.ilvl !== afterList?.ilvl
    const listChanged = !same(beforeList, afterList) && !listLevelChanged
    if (listChanged && !customDefinition && !numberingBinding) {
      if (!['docParagraph', 'docListItem'].includes(node.type) || !['docParagraph', 'docListItem'].includes(edited.type)) throw new Error('暂不支持标题转换列表')
      const list = edited.type === 'docListItem' ? edited.attrs?.kind : 'none'
      if (!['none', 'bullet', 'ordered'].includes(String(list)) || (list !== 'none' && (edited.attrs?.numId !== `native-${list}` || edited.attrs?.ilvl !== 0))) throw new Error('此列表定义或级别暂不支持保存')
      ops.push({ kind: 'setParagraphList', ...baseOp(anchor), list })
    }
    if (listLevelChanged && !customDefinition && !numberingBinding) {
      const ilvl = edited.attrs?.ilvl
      if (typeof ilvl !== 'number' || !Number.isInteger(ilvl) || ilvl < 0 || ilvl > 8) throw new Error('此列表级别暂不支持保存')
      if (!['bullet', 'ordered'].includes(String(afterList?.kind))) throw new Error('此列表类型暂不支持保存')
      ops.push({ kind: 'setParagraphListLevel', ...baseOp(anchor), ilvl, ...(beforeList?.kind !== afterList?.kind ? { listKind: afterList?.kind } : {}) })
    }
    // 这些本地标记并非所有段落类型都有声明；转换列表时 ProseMirror 会丢弃目标类型未声明的键。
    // 只归一空值，非空操作意图仍由上方对应校验处理。
    const withoutLocalMarkers = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key, value]) =>
      value != null || !['nativeCoverPage', 'nativeRibbonStyle', 'nativeRulerIndent', 'nativeTabStops', 'nativeListDefinition', 'nativeNumberingBinding'].includes(key)))
    const originalAttrs = withoutLocalMarkers(node.type === 'docListItem' ? withoutList(node.attrs) : node.attrs)
    if ((customDefinition || numberingBinding) && node.type === 'docHeading') { delete originalAttrs.level; delete originalAttrs.outlineOnly }
    const editedAttrs = withoutLocalMarkers(edited.type === 'docListItem' ? withoutList(edited.attrs) : edited.attrs)
    if ((!listChanged && !customDefinition && node.type !== edited.type) || !same(withoutPageBreakBefore(withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(originalAttrs)))))), withoutPageBreakBefore(withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(editedAttrs)))))))) throw new Error('暂不支持改变段落布局')
    const pageBreakChanged = !!node.attrs?.pageBreakBefore !== !!edited.attrs?.pageBreakBefore
    if (pageBreakChanged) {
      // 固定源 page-break.ts：分页符 = 段落 pageBreakBefore；与底纹同规走原 XML 最小修改，
      // 不能与同段其他改动混存（段中插入分页的拆分段由 insertParagraph 携带分页）。
      if (!same(node, { ...edited, attrs: { ...edited.attrs, pageBreakBefore: node.attrs?.pageBreakBefore ?? false } })) throw new Error('分页符修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphPageBreakBefore', ...baseOp(anchor), value: !!edited.attrs?.pageBreakBefore })
    }
    const shadingChanged = !same(node.attrs?.shadingFill ?? null, edited.attrs?.shadingFill ?? null) || !same(node.attrs?.shadingClear ?? null, edited.attrs?.shadingClear ?? null)
    if (shadingChanged) {
      if (anchor.paragraphShadingEditable === false) throw new Error('此来源段落底纹只读')
      // 布局与装饰均为独立pPr属性；正文仍须由可信final-run路径单独归一。
      if (!same({ ...node, attrs: withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(node.attrs))))) }, { ...edited, attrs: withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(edited.attrs))))) })) throw new Error('段落底纹修改请先保存；同段文字和格式不能混用')
      const shading = safeDocxShading(edited.attrs?.shadingClear === true ? 'auto' : edited.attrs?.shadingFill ?? 'none')
      ops.push({ kind: 'setParagraphShading', ...baseOp(anchor), fill: shading.fill, clear: shading.clear })
    }
    const bordersChanged = !same(node.attrs?.borders ?? null, edited.attrs?.borders ?? null) || !same(node.attrs?.borderLines ?? null, edited.attrs?.borderLines ?? null)
    if (bordersChanged) {
      if (anchor.paragraphBordersEditable === false) throw new Error('此来源段落边框只读')
      if (!same({ ...node, attrs: withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(node.attrs))))) }, { ...edited, attrs: withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(edited.attrs))))) })) throw new Error('段落边框修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphBorders', ...baseOp(anchor), borders: safeDocxBorderSpec(paragraphBorders(edited)) })
    }
    const changedSpacing: Record<string, unknown> = {}
    for (const key of ['spaceBefore', 'spaceAfter'] as const) if (!Object.is(node.attrs?.[key], edited.attrs?.[key])
      || !same(node.attrs?.[`${key}Auto`] ?? null, edited.attrs?.[`${key}Auto`] ?? null)) {
      const value = edited.attrs?.[key]
      if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isInteger(value) || value < 0 || value > 14400) throw new Error('此段前/段后间距暂不支持保存')
      changedSpacing[key] = value
    }
    if (!same(node.attrs?.lineSpacing, edited.attrs?.lineSpacing) || !same(node.attrs?.lineRule, edited.attrs?.lineRule) || !same(node.attrs?.lineRawTwips, edited.attrs?.lineRawTwips)) {
      const attrs = edited.attrs ?? {}
      const values = attrs.lineRule === 'exact' || attrs.lineRule === 'atLeast'
        ? { lineRule: attrs.lineRule, lineRawTwips: attrs.lineRawTwips, ...(attrs.lineSpacing != null ? { lineSpacing: attrs.lineSpacing } : {}) }
        : { lineSpacing: attrs.lineSpacing, ...(attrs.lineRule != null ? { lineRule: attrs.lineRule } : {}), ...(attrs.lineRawTwips != null ? { lineRawTwips: attrs.lineRawTwips } : {}) }
      if (!docxLineSpacingPatch(values)) throw new Error('此行距暂不支持保存')
      Object.assign(changedSpacing, values)
    }
    for (const [autoKey, valueKey] of [['spaceBeforeAuto', 'spaceBefore'], ['spaceAfterAuto', 'spaceAfter']] as const) {
      if ((valueKey in changedSpacing && edited.attrs?.[autoKey] != null) || (!same(node.attrs?.[autoKey], edited.attrs?.[autoKey]) && !(valueKey in changedSpacing))) throw new Error('自动段前/段后间距暂不支持保存')
    }
    if (Object.keys(changedSpacing).length) ops.push({ kind: 'setParagraphSpacing', ...baseOp(anchor), ...changedSpacing })
    if (!same(node.attrs?.indentLeft, edited.attrs?.indentLeft)) {
      const twips = edited.attrs?.indentLeft ?? 0
      if (!Number.isInteger(twips) || Number(twips) < 0 || Number(twips) > 14400 || Number(twips) % 720 !== 0 || edited.type === 'docListItem') throw new Error('此段落缩进暂不支持保存')
      ops.push({ kind: 'setParagraphIndent', ...baseOp(anchor), twips })
    }
    if (!same(node.attrs?.indentRight, edited.attrs?.indentRight)) {
      const twips = edited.attrs?.indentRight ?? 0
      if (!Number.isInteger(twips) || Number(twips) < -14400 || Number(twips) > 14400) throw new Error('此段落右缩进值无效')
      ops.push({ kind: 'setParagraphRightIndent', ...baseOp(anchor), twips })
    }
    if (!same(node.attrs?.indentFirstLine, edited.attrs?.indentFirstLine) || !same(node.attrs?.indentFirstLineChars, edited.attrs?.indentFirstLineChars)) {
      const twips = edited.attrs?.indentFirstLine, firstLineChars = edited.attrs?.indentFirstLineChars ?? undefined
      if (!validDocxSpecialIndent(twips, firstLineChars) || edited.type === 'docListItem'
        || !anchor.editable || anchor.paragraphLayoutEditable === false) throw new Error('此段落特殊缩进暂不支持保存')
      ops.push({ kind: 'setParagraphSpecialIndent', ...baseOp(anchor), twips, ...(firstLineChars !== undefined ? { firstLineChars } : {}) })
    }
    if (!same(node.attrs?.align, edited.attrs?.align)) {
      const alignment = edited.attrs?.align ?? (edited.attrs?.bidi === true || edited.attrs?.bidiInferred === true ? 'right' : 'left')
      if (!['left', 'center', 'right', 'justify'].includes(String(alignment))) throw new Error('此段落对齐方式暂不支持保存')
      ops.push({ kind: 'setParagraphAlignment', ...baseOp(anchor), alignment })
    }
    if (!same(structure(node, false), structure({ ...edited, type: node.type, attrs: node.attrs }, false))) throw new Error('暂不支持改变段落结构')
    const oldLinks = linkMap(node), newLinks = linkMap(edited), textChanged = textOf(node) !== textOf(edited)
    const fontSlots = (paragraph: DocxPmNode) => [...new Set((paragraph.content ?? []).filter(run => run.type === 'text').map(run => JSON.stringify(
      Object.assign({}, ...(run.marks ?? []).filter(mark => ['docTextStyle', 'textStyle'].includes(mark.type)).map(mark => Object.fromEntries(
        ['fontAscii', 'eastAsiaFont', 'fontCs', 'csFont', 'themeRFonts'].filter(key => mark.attrs?.[key] != null).map(key => [key, mark.attrs![key]])))))))].filter(value => value !== '{}').sort()
    if (textChanged && textOf(edited) && !same(fontSlots(node), fontSlots(edited))) throw new Error('同一段落修改文字后，中西文字体请先保存再设置')
    if (textChanged && oldLinks.some(Boolean)) throw new Error('含已有链接的段落请先单独修改链接；文字编辑暂不支持保留原链接元数据')
    if (textChanged) ops.push({ kind: 'replaceParagraph', ...baseOp(anchor), text: textOf(edited) })
    const beforeMetadata = textChanged ? [] : linkMetadata(node), afterMetadata = linkMetadata(edited)
    if (afterMetadata.some((metadata, index) => metadata && !same(metadata, beforeMetadata[index] ?? { tooltip: null, plain: false }))) throw new Error('暂不支持修改链接提示或显示属性')
    const comparison = textChanged ? newLinks.map(() => null) : oldLinks
    const linkedPreview = textChanged ? withoutLinks(edited) : structuredClone(node)
    for (let from = 0; from < newLinks.length;) {
      if (newLinks[from] === comparison[from]) { from++; continue }
      const href = newLinks[from]
      let to = from + 1
      while (to < newLinks.length && newLinks[to] === href && newLinks[to] !== comparison[to]) to++
      if (!validDocxLinkRange(textOf(edited), from, to)) throw new Error('链接范围不能拆开 Unicode 字符')
      if ((edited.content ?? []).some(run => run.type !== 'text')) throw new Error('含复杂内联对象的段落暂不支持链接修改')
      applyLink(linkedPreview, from, to, href)
      ops.push({ kind: 'setParagraphLink', ...baseOp(anchor), from, to, href })
      from = to
    }
    // 同一来源段落文字不变时，用同一字符差分处理基础样式、高亮和上下标，保留混合run。
    const inlineRange = !textChanged && [node, edited].every(item => (item.content ?? []).every(run => run.type === 'text')) && textOf(edited)
    if (inlineRange) {
      const ranges = formatRangeChanges(withoutLinks(node), withoutLinks(edited)), length = textOf(edited).length
      const uniformHighlight = paragraphHighlight(edited)
      if (ranges.length && uniformHighlight != null && ranges.every(range => Object.keys(range.style).length === 1 && 'highlight' in range.style)) {
        ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: { highlight: safeDocxHighlight(uniformHighlight) } })
        continue
      }
      for (const range of ranges) {
        if (!validDocxLinkRange(textOf(edited), range.from, range.to)) throw new Error('局部格式范围不能拆开 Unicode 字符')
        if (range.from === 0 && range.to === length && Object.keys(range.style).length === 1 && 'vertAlign' in range.style) ops.push({ kind: 'setParagraphVerticalAlign', ...baseOp(anchor), value: range.style.vertAlign })
        else ops.push({ kind: range.from === 0 && range.to === length ? 'formatParagraph' : 'formatRange', ...baseOp(anchor), ...(range.from === 0 && range.to === length ? {} : { from: range.from, to: range.to }), style: range.style })
      }
      continue
    }
    const oldVertical = paragraphVerticalAlign(node), newVertical = paragraphVerticalAlign(edited)
    if (textOf(edited) && ((oldVertical !== newVertical && !(textOf(node) === '' && newVertical === 'baseline'))
      || (oldVertical === undefined && newVertical === undefined && !same(verticalAlignMap(node), verticalAlignMap(edited))))) {
      if (!newVertical) throw new Error('暂不支持局部上下标修改，请选择整个段落')
      ops.push({ kind: 'setParagraphVerticalAlign', ...baseOp(anchor), value: newVertical })
    }
    const oldHighlight = paragraphHighlight(node), newHighlight = paragraphHighlight(edited)
    if (textOf(edited) && ((oldHighlight ?? null) !== (newHighlight ?? null) || (!textChanged && !same(highlightMap(node), highlightMap(edited))))) {
      if (newHighlight == null) throw new Error('暂不支持局部高亮修改或移除覆盖；请选择整段并使用无颜色')
      ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: { highlight: safeDocxHighlight(newHighlight) } })
    }
    if ((edited.content ?? []).some(child => child.type === 'text') && !same(markSequence(withoutHighlight(withoutVerticalAlign(withoutLinks(node)))), markSequence(withoutHighlight(withoutVerticalAlign(withoutLinks(edited)))))) {
      const plainBefore = withoutHighlight(withoutVerticalAlign(withoutLinks(node))), plainAfter = withoutHighlight(withoutVerticalAlign(withoutLinks(edited)))
      const inline = (paragraph: DocxPmNode) => (paragraph.content ?? []).every(child => child.type === 'text')
      if (!textChanged && inline(node) && inline(edited) && (node.content ?? []).some(child => child.type === 'text')) {
        // 文字未变：局部格式按区间保存；整段一致的单一区间沿用 formatParagraph。
        const ranges = formatRangeChanges(plainBefore, plainAfter), length = textOf(edited).length
        if (ranges.length === 1 && ranges[0]!.from === 0 && ranges[0]!.to === length) ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: ranges[0]!.style })
        else for (const range of ranges) {
          if (!validDocxLinkRange(textOf(edited), range.from, range.to)) throw new Error('局部格式范围不能拆开 Unicode 字符')
          ops.push({ kind: 'formatRange', ...baseOp(anchor), ...range })
        }
        continue
      }
      let next: Record<string, unknown>
      try { next = styleOf(plainAfter) } catch (error) { throw new Error(textChanged && (error as Error).message.includes('局部样式') ? '同一段落修改文字后，局部格式请先保存再设置' : (error as Error).message) }
      const old = (node.content ?? []).some(child => child.type === 'text') ? styleOf(plainBefore) : { bold: false, italic: false, underline: false, strike: false }
      for (const key of ['color', 'fontFamily', 'fontSize', 'styleId']) if (key in old && !(key in next)) next[key] = null
      const changed = Object.fromEntries(Object.entries(next).filter(([key, value]) => !same(value, old[key])))
      if (Object.keys(changed).length) ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: changed })
    }
  }
  if (sectionOperation) ops.push(...(Array.isArray(sectionOperation) ? sectionOperation : [sectionOperation]))
  if (headerFooterOperations?.length) ops.push(...headerFooterOperations)
  const all = [...revisions.operations, ...nested.operations, ...ops, ...tableStyle.operations, ...cellBorders.operations, ...shading.operations]
  for (const operation of tableStyle.operations) if (all.some(other => other !== operation && other.blockId === operation.blockId)) throw new Error('表格样式修改不能与同表文字、格式或其他结构修改混用，请先保存')
  assertColumnWidthSections(all, anchors)
  if (all.length > 500) throw new Error('操作超过 500 条，请分批保存')
  assertDocxNestedOperationBatch(all)
  assertDocxTextRevisionBatch(all)
  return all
}

function assertColumnWidthSections(operations: NativeOperation[], anchors: DocxAnchor[]): void {
  for (const operation of operations) if (operation.kind === 'resizeTableColumns' || operation.kind === 'setTableRowHeights' || operation.kind === 'setTableAutoFit') {
    const anchor = anchors.find(anchor => anchor.blockId === operation.blockId)
    const sectionId = operation.kind === 'resizeTableColumns' ? anchor?.columnWidthSectionId : operation.kind === 'setTableAutoFit' ? anchor?.autoFitSectionId : anchor?.rowHeightSectionId
    const label = operation.kind === 'resizeTableColumns' ? '列宽' : operation.kind === 'setTableAutoFit' ? '自动调整' : '行高'
    if (operations.some(other => other.kind === 'setSectionLayout' && (!sectionId || other.sectionId === sectionId))) throw new Error(`${label}与同节页面设置不能混用，请先保存`)
    if (operations.some(other => {
      if (other.kind !== 'insertSectionBreak') return false
      const breakSectionId = anchors.find(item => item.blockId === other.blockId)?.sourceSectionId
      return operation.kind !== 'setTableAutoFit' || !sectionId || !breakSectionId || breakSectionId === sectionId
    })) throw new Error(`${label}与分节修改不能混用，请先保存`)
  }
}
/** 从原文件恢复草稿，保持原 docxIndex 和对象身份。 */
export function replayDocxOperations(original: DocxPmNode, operations: NativeOperation[], anchors: DocxAnchor[], section?: DocxSectionAnchor | readonly DocxSectionAnchor[], schema?: Schema, styles?: Map<string, DocxStyleInfo>, headerFooters?: { anchor?: { sectionId: string; expectedSectionSha256: string }; model?: import('./docx-hf').DocxHeadersFootersModel }): DocxPmNode {
  assertDocxTextRevisionBatch(operations)
  assertColumnWidthSections(operations, anchors)
  if (Array.isArray(section)) restoredDocxSectionOperations(operations, section); else restoredDocxSectionOperation(operations, section as DocxSectionAnchor | undefined)
  if (headerFooters) restoredDocxHeaderFooterOperations(operations, headerFooters.anchor, headerFooters.model)
  const result = structuredClone(original), originalNodes = new Map((result.content ?? []).map(node => [Number(idOf(node)), node]))
  replayDocxNestedTables(original, result, operations, anchors)
  const byId = new Map(anchors.map(anchor => [anchor.blockId, anchor])), afterCounts = new Map<string, number>()
  const numberingBindings = new Map<string, ReturnType<typeof normalizeDocxNumberingBinding>>()
  const replaceText = (node: DocxPmNode, value: string) => {
    let remaining = Array.from(value)
    const runs = (node.content ?? []).filter(child => child.type === 'text')
    if (!runs.length) { node.content = value ? [{ type: 'text', text: value }] : []; return }
    runs.forEach((run, index) => { run.text = remaining.splice(0, index === runs.length - 1 ? remaining.length : Array.from(run.text ?? '').length).join('') })
    node.content = node.content?.filter(child => child.type !== 'text' || child.text)
  }
  for (const operation of operations) if (operation.kind === 'setTableCellBorders' && operations.some(other => other !== operation && other.blockId === operation.blockId && other.kind !== 'setCellShading')) throw new Error('同表边框草稿不能与其他修改混合')
  const structural = new Set<string>()
  for (const operation of operations) if (operation.kind === 'setParagraphDropCap' && operations.filter(other => other.kind === operation.kind && other.blockId === operation.blockId).length > 1) throw new Error('草稿首字下沉重复操作')
  for (const operation of operations) if (operation.kind === 'setParagraphProperties' && operations.some(other => other !== operation && other.kind !== 'setParagraphDropCap' && other.blockId === operation.blockId)) throw new Error('段落设置不能与同段其它操作或重复操作混合')
  for (const operation of operations) if (['setParagraphRulerIndent','setParagraphTabStops'].includes(operation.kind) && operations.filter(other => other.blockId === operation.blockId && other.kind !== 'setParagraphDropCap').length > 1) throw new Error('标尺操作不能与同段其它操作或重复操作混合')
  for (const operation of operations) if (operation.kind === 'setCellShading' && operations.some(other => other !== operation && other.blockId === operation.blockId && other.cellId === operation.cellId)) throw new Error('同一单元格底纹不能与正文或重复底纹草稿混合')
  for (const operation of operations) if (operation.kind === 'setTableCellParagraphProperties' && operations.some(other => other !== operation && other.blockId === operation.blockId)) throw new Error('表格段落设置不能与同表文字、格式或重复操作混合')
  for (const operation of operations) if (operation.kind === 'formatTableProperties' || TABLE_KINDS.includes(operation.kind as any) || operation.kind === 'restructureTable' || operation.kind === 'reshapeTableCells' || operation.kind === 'resizeTableColumns' || operation.kind === 'setTableRowHeights' || operation.kind === 'setTableAutoFit' || operation.kind === 'setTableCellTextDirection' || operation.kind === 'setTableCellAlignment' || operation.kind === 'setTableCellMargins' || operation.kind === 'setTableCellMarginOverrides' || operation.kind === 'setTableRowBreaks' || operation.kind === 'setTableAlignment' || operation.kind === 'setTableCellWrap' || operation.kind === 'setTableAltText') {
    const id = String(operation.blockId)
    if (structural.has(id) || operations.some(other => other !== operation && other.blockId === id)) throw new Error('同表草稿不能混合文字或多次结构操作')
    structural.add(id)
  }
  for (const operation of operations) {
    if (operation.kind === 'resolveTextRevision' || operation.kind === 'replaceNestedCellText' || operation.kind === 'setSectionLayout' || operation.kind === 'setHeaderFooter' || operation.kind === 'setHeaderFooterLink' || operation.kind === 'setPageColor' || operation.kind === 'setWatermark' || operation.kind === 'setTrackRevisions' || operation.kind === 'upsertStyle' || operation.kind === 'setCellShading' || operation.kind === 'setTableCellBorders' || operation.kind === 'setTableStyle') continue
    const anchor = byId.get(String(operation.blockId)), node = anchor && originalNodes.get(anchor.docxIndex)
    if (!anchor || !node) throw new Error('草稿对象不属于当前 Word 文件')
    if (operation.kind === 'replaceImage') {
      if (operations.some(other => other !== operation && other.blockId === operation.blockId)) throw new Error('图片草稿包含重复或冲突操作')
      Object.assign(node, projectDocxPicture(node, anchor, operation)); continue
    }
    if (operation.kind === 'applyDocumentStyle') {
      if (!schema || !styles || !anchor.editable || anchor.fontDialogEditable === false || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || Object.keys(operation).some(key => !['kind','blockId','expectedObjectSha256','actions'].includes(key)) || operations.some(other => other !== operation && other.blockId === operation.blockId)) throw new Error('样式窗格草稿来源无效')
      Object.assign(node, projectStylesPaneActions(node, operation.actions as StylesPaneAction[], styles as any, schema)); continue
    }
    if (operation.kind === 'setParagraphDropCap') { replayDocxDropCap(structuredClone(node), anchor, operation); continue }
    if (operation.kind === 'setParagraphProperties') { if (!schema) throw new Error('草稿段落属性缺少当前文档模型'); Object.assign(node, replayDocxParagraphProperties(node, anchor, operation, schema)); continue }
    if (operation.kind === 'setTableCellParagraphProperties') {
      const position = anchor.cells?.flatMap((cells, r) => cells.map((cell, c) => ({ ...cell, r, c }))).find(cell => cell.cellId === operation.cellId)
      if (!position || !schema || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || operation.expectedCellSha256 !== position.expectedObjectSha256
        || operation.expectedParagraphSha256 !== position.paragraphs?.find(item => item.index === operation.paragraphIndex)?.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind','blockId','expectedObjectSha256','cellId','expectedCellSha256','paragraphIndex','expectedParagraphSha256','values'].includes(key))) throw new Error('草稿表格段落设置的来源身份或字段无效')
      Object.assign(node, projectDocxTableCellParagraphProperties(node, anchor, position.r, position.c, Number(operation.paragraphIndex), operation.values, schema)); continue
    }
    if (operation.kind === 'setParagraphRulerIndent') { Object.assign(node, replayDocxRulerIndent(node, anchor, operation)); continue }
    if (operation.kind === 'setParagraphTabStops') { Object.assign(node, replayDocxTabStops(node, anchor, operation)); continue }
    const layoutFields: Record<string, string[]> = { setParagraphAlignment: ['alignment'], setParagraphIndent: ['twips'], setParagraphRightIndent: ['twips'], setParagraphSpecialIndent: ['twips', 'firstLineChars'], setParagraphSpacing: ['spaceBefore', 'spaceAfter', ...DOCX_LINE_SPACING_FIELDS] }
    if (layoutFields[operation.kind] && (!(anchor.paragraphLayoutEditable ?? anchor.editable) || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
      || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', ...layoutFields[operation.kind]!].includes(key))
      || ['setParagraphIndent', 'setParagraphSpecialIndent'].includes(operation.kind) && node.type === 'docListItem')) throw new Error('草稿段落布局字段或来源身份无效')
    if (operation.kind === 'formatTableProperties') {
      if(Object.keys(operation).some(key=>!['kind','blockId','expectedObjectSha256','patch'].includes(key))||operation.expectedObjectSha256!==anchor.expectedObjectSha256)throw new Error('表格属性草稿来源身份或字段无效')
      Object.assign(node,projectDocxTableProperties(node,anchor,operation.patch,schema))
    }
    else if (operation.kind === 'setTableAltText') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'title', 'description'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('表格标题/说明草稿的来源身份或字段无效')
      Object.assign(node, projectDocxTableAltText(node, anchor, { title: operation.title as string, description: operation.description as string }, schema))
    }
    else if (operation.kind === 'setTableCellWrap') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('单元格自动换行草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellWrap(node, anchor, operation.steps as TableCellWrapStep[], schema))
    }
    else if (operation.kind === 'setTableAlignment') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'alignment'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('整表对齐草稿的来源身份或字段无效')
      Object.assign(node, projectDocxTableAlignment(node, anchor, operation.alignment as TableAlignment, schema))
    }
    else if (operation.kind === 'setTableRowBreaks') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('行跨页草稿的来源身份或字段无效')
      Object.assign(node, projectDocxRowBreaks(node, anchor, operation.steps as TableRowBreakStep[], schema))
    }
    else if (operation.kind === 'setTableCellMarginOverrides') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('单格边距草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellMarginOverrides(node, anchor, operation.steps as TableCellMarginOverrideStep[], schema))
    }
    else if (operation.kind === 'setTableCellMargins') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'margins'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('单元格默认边距草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellMargins(node, anchor, operation.margins as Parameters<typeof projectDocxCellMargins>[2], schema))
    }
    else if (operation.kind === 'setTableCellAlignment') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('单元格对齐草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellAlignment(node, anchor, operation.steps as TableCellAlignmentStep[], schema))
    }
    else if (operation.kind === 'setTableCellTextDirection') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('文字方向草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellTextDirection(node, anchor, operation.steps as TableCellTextDirectionStep[], schema))
    }
    else if (operation.kind === 'setTableAutoFit') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('自动调整草稿的来源身份或字段无效')
      Object.assign(node, projectDocxAutoFit(node, anchor, operation.steps as TableAutoFitStep[], schema))
    }
    else if (operation.kind === 'setTableRowHeights') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('行高草稿的来源身份或字段无效')
      Object.assign(node, projectDocxRowHeights(node, anchor, operation.steps as TableRowHeightStep[], schema))
    }
    else if (operation.kind === 'resizeTableColumns') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('列宽草稿的来源身份或字段无效')
      Object.assign(node, projectDocxColumnWidths(node, anchor, operation.steps as TableColumnWidthStep[], schema))
    }
    else if (operation.kind === 'reshapeTableCells') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('合并拆分草稿的来源身份或字段无效')
      Object.assign(node, projectDocxCellShape(node, anchor, operation.steps as TableCellShapeStep[], schema))
    }
    else if (operation.kind === 'setTableRepeatHeaders') {
      if(operations.some(other=>other!==operation&&other.blockId===operation.blockId))throw new Error('重复标题行不能与同表其他草稿混合')
      Object.assign(node,projectTableHeaders(node,anchor,operation))
    }
    else if (operation.kind === 'clearParagraphFormatting') {
      if (!anchor.editable || !schema || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'ranges'].includes(key))
        || operations.some(other => other !== operation && other.kind !== 'setParagraphDropCap' && other.blockId === operation.blockId)) throw new Error('草稿清除格式字段或来源身份无效')
      const ranges = docxClearRanges(operation.ranges, textOf(node))
      const styleId = [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId ?? null
      const projected = projectClearedDocxParagraph(node, ranges, styleId, schema)
      projected.attrs = { ...projected.attrs, nativeClearFormatting: { ranges } }
      Object.assign(node, projected)
    }
    else if (operation.kind === 'setParagraphStyle') {
      if (!(anchor.paragraphStyleEditable ?? anchor.editable) || node.type !== 'docParagraph' || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'styleId', 'ribbon'].includes(key))
        || operations.some(other => other.blockId === operation.blockId && (other.kind !== 'setParagraphStyle' || operation.ribbon === true && other !== operation))) throw new Error('草稿段落样式字段或来源身份无效')
      if ('ribbon' in operation && operation.ribbon !== true) throw new Error('Ribbon样式字段无效')
      safeParagraphStyle(styles, operation.styleId)
      const sourceStyle = node.attrs?.styleId ?? [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceStyle != null) safeParagraphStyle(styles, sourceStyle)
      if (operation.ribbon === true) {
        if (!schema || !anchor.editable) throw new Error('Ribbon样式来源无效')
        Object.assign(node, projectRibbonStyle(node, String(operation.styleId), schema))
      } else node.attrs = { ...node.attrs, styleId: operation.styleId }
    }
    else if (operation.kind === 'setParagraphShading') {
      if (!(anchor.paragraphShadingEditable ?? anchor.editable) || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'fill', 'clear'].includes(key))
        || (typeof operation.fill !== 'string' && operation.fill !== null)
        || (typeof operation.fill === 'string' && !/^[0-9a-f]{6}$/.test(operation.fill))
        || typeof operation.clear !== 'boolean'
        || operations.some(other => other.blockId === operation.blockId && other !== operation && other.kind !== 'setParagraphDropCap' && other.kind !== 'setParagraphBorders' && !layoutFields[other.kind])) throw new Error('草稿段落底纹字段或来源身份无效')
      node.attrs = { ...node.attrs, shadingFill: operation.fill, shadingClear: operation.clear ? true : null }
    }
    else if (operation.kind === 'setParagraphPageBreakBefore') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key))
        || typeof operation.value !== 'boolean'
        || operations.some(other => other.blockId === operation.blockId && other !== operation && other.kind !== 'setParagraphDropCap' && other.kind !== 'insertParagraph' && other.kind !== 'insertParagraphImage')) throw new Error('草稿分页符字段或来源身份无效')
      node.attrs = { ...node.attrs, pageBreakBefore: operation.value }
    }
    else if (operation.kind === 'setParagraphBorders') {
      let borders: ReturnType<typeof safeDocxBorderSpec>
      try { borders = safeDocxBorderSpec(operation.borders) } catch { throw new Error('草稿段落边框字段或来源身份无效') }
      if (!(anchor.paragraphBordersEditable ?? anchor.editable) || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'borders'].includes(key))
        || node.attrs?.borderReset || node.attrs?.borderPad
        || operations.some(other => other.blockId === operation.blockId && other !== operation && other.kind !== 'setParagraphDropCap' && other.kind !== 'setParagraphShading' && !layoutFields[other.kind])) throw new Error('草稿段落边框字段或来源身份无效')
      node.attrs = { ...node.attrs, ...docxBorderAttrs(borders) }
    }
    else if (TABLE_KINDS.includes(operation.kind as any)) {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'index'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿表格身份或字段无效')
      const projected = projectDocxTable(node, anchor, { kind: operation.kind, index: operation.index }, schema)
      Object.assign(node, projected)
    }
    else if (operation.kind === 'restructureTable') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'steps', 'texts'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿表格身份或字段无效')
      const projected = projectDocxTableSteps(node, anchor, tableSteps({ steps: operation.steps }), schema)
      const texts = operation.texts === undefined ? [] : operation.texts
      if (!Array.isArray(texts)) throw new Error('草稿表格文字无效')
      for (const entry of texts as { row: unknown; column: unknown; text: unknown }[]) {
        const cell = projected.content?.[Number(entry?.row)]?.content?.[Number(entry?.column)]
        if (!cell?.content?.length || typeof entry.text !== 'string' || !Number.isInteger(entry.row) || !Number.isInteger(entry.column)) throw new Error('草稿表格文字坐标无效')
        replaceText(cell.content[0]!, entry.text)
        for (const paragraph of cell.content.slice(1)) replaceText(paragraph, '')
      }
      Object.assign(node, projected)
    }
    else if (operation.kind === 'setParagraphLink') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'from', 'to', 'href'].includes(key))) throw new Error('草稿链接包含不支持的字段')
      if (!anchor.editable || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !paragraph(node)
        || !validDocxLinkRange(textOf(node), operation.from, operation.to)) throw new Error('草稿链接范围或对象身份无效')
      const href = operation.href === null ? null : safeDocxLink(operation.href)
      applyLink(node, Number(operation.from), Number(operation.to), href)
    }
    else if (operation.kind === 'setParagraphVerticalAlign') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key))
        || !['baseline', 'superscript', 'subscript'].includes(String(operation.value)) || !(node.content ?? []).some(run => run.type === 'text' && !!run.text)) throw new Error('草稿上下标字段或来源身份无效')
      for (const run of node.content ?? []) {
        if (run.type !== 'text') continue
        const marks = run.marks ?? []
        const old = marks.find(mark => ['docTextStyle', 'textStyle'].includes(mark.type))
        const changed = { type: old?.type ?? 'docTextStyle', attrs: { ...old?.attrs, vertAlign: operation.value === 'baseline' ? null : operation.value } }
        run.marks = old ? marks.map(mark => mark === old ? changed : mark) : [...marks, changed]
      }
    }
    else if (operation.kind === 'replaceParagraph') replaceText(node, String(operation.text))
    else if (operation.kind === 'setParagraphIndent') {
      const twips = operation.twips
      if (!Number.isInteger(twips) || Number(twips) < 0 || Number(twips) > 14400 || Number(twips) % 720 !== 0) throw new Error('草稿段落缩进无效')
      node.attrs = { ...node.attrs, indentLeft: twips || null }
    }
    else if (operation.kind === 'setParagraphSpecialIndent') {
      if (!anchor.editable || !validDocxSpecialIndent(operation.twips, operation.firstLineChars)) throw new Error('草稿特殊缩进无效')
      node.attrs = { ...node.attrs, indentFirstLine: operation.twips, indentFirstLineChars: operation.firstLineChars ?? null }
    }
    else if (operation.kind === 'setParagraphRightIndent') {
      const twips = operation.twips
      if (!Number.isInteger(twips) || Number(twips) < -14400 || Number(twips) > 14400) throw new Error('草稿右缩进值无效')
      node.attrs = { ...node.attrs, indentRight: twips || null }
    }
    else if (operation.kind === 'setParagraphNumberingValue') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'binding', 'ilvl', 'listKind'].includes(key))
        || !Number.isInteger(operation.ilvl) || Number(operation.ilvl) < 0 || Number(operation.ilvl) > 8
        || operation.listKind !== undefined && !['bullet', 'ordered'].includes(String(operation.listKind))) throw new Error('草稿编号值来源或字段无效')
      const binding = normalizeDocxNumberingBinding(operation.binding)
      const previous = numberingBindings.get(binding.id)
      if (previous && !same(previous, binding)) throw new Error('同一编号值定义存在冲突')
      numberingBindings.set(binding.id, binding)
      const source = binding.sourceNumId ? original.content?.find(n => n.type === 'docListItem' && n.attrs?.numId === binding.sourceNumId) : undefined
      node.type = 'docListItem'
      node.attrs = { ...withoutList(node.attrs), kind: operation.listKind ?? (binding.custom ? customListLevel(binding.custom, operation.ilvl).kind : binding.defaultNumbering?.kind ?? source?.attrs?.kind ?? 'ordered'), numId: docxNumberingBindingId(binding), ilvl: operation.ilvl, nativeListDefinition: null, nativeNumberingBinding: binding }
      delete node.attrs.level; delete node.attrs.outlineOnly
    }
    else if (operation.kind === 'setParagraphCustomList') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'definitionId', 'levels', 'ilvl'].includes(key))) throw new Error('草稿多级列表来源或字段无效')
      const definition = normalizeDocxCustomList({ id: operation.definitionId, levels: operation.levels })
      node.type = 'docListItem'
      node.attrs = { ...withoutList(node.attrs), ...customListLevel(definition, operation.ilvl), nativeListDefinition: definition }
      delete node.attrs.level
      delete node.attrs.outlineOnly
    }
    else if (operation.kind === 'setParagraphList') {
      const list = operation.list
      if (!['none', 'bullet', 'ordered'].includes(String(list))) throw new Error('草稿列表类型无效')
      node.type = list === 'none' ? 'docParagraph' : 'docListItem'
      node.attrs = { ...withoutList(node.attrs), ...(list === 'none' ? {} : { kind: list, numId: `native-${list}`, ilvl: 0 }) }
    }
    else if (operation.kind === 'setParagraphListLevel') {
      const ilvl = operation.ilvl
      if (!Number.isInteger(ilvl) || Number(ilvl) < 0 || Number(ilvl) > 8 || node.type !== 'docListItem') throw new Error('草稿列表级别无效')
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'ilvl', 'listKind'].includes(key)) || operation.listKind !== undefined && !['bullet', 'ordered'].includes(String(operation.listKind))) throw new Error('草稿列表类型无效')
      node.attrs = { ...node.attrs, ilvl: Number(ilvl), ...(operation.listKind ? { kind: operation.listKind } : {}) }
    }
    else if (operation.kind === 'setParagraphAlignment') {
      if (!['left', 'center', 'right', 'justify'].includes(String(operation.alignment))) throw new Error('草稿段落对齐方式无效')
      node.attrs = { ...node.attrs, align: operation.alignment }
    }
    else if (operation.kind === 'setParagraphSpacing') {
      const values = operation as Record<string, unknown>
      if (!(anchor.paragraphLayoutEditable ?? anchor.editable) || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(values).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'spaceBefore', 'spaceAfter', ...DOCX_LINE_SPACING_FIELDS].includes(key))) throw new Error('草稿段落间距字段或来源身份无效')
      if (!['spaceBefore', 'spaceAfter', ...DOCX_LINE_SPACING_FIELDS].some(key => values[key] !== undefined)) throw new Error('草稿段落间距无效')
      for (const key of ['spaceBefore', 'spaceAfter']) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isFinite(values[key]) || !Number.isInteger(values[key]) || (values[key] as number) < 0 || (values[key] as number) > 14400)) throw new Error('草稿段落间距无效')
      const line = docxLineSpacingPatch(values)
      if (!line) throw new Error('草稿行距无效')
      node.attrs = { ...node.attrs,
        ...(values.spaceBefore !== undefined ? { spaceBefore: values.spaceBefore, spaceBeforeAuto: null } : {}),
        ...(values.spaceAfter !== undefined ? { spaceAfter: values.spaceAfter, spaceAfterAuto: null } : {}),
        ...line,
      }
    }
    else if (operation.kind === 'deleteParagraph') result.content = result.content?.filter(item => item !== node)
    else if (operation.kind === 'insertParagraph') {
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      if (operation.pageBreakBefore !== undefined && operation.pageBreakBefore !== true) throw new Error('草稿新增段落分页字段无效')
      const dropCap = operation.dropCap === undefined ? null : normalizeDocxDropCap(operation.dropCap)
      result.content!.splice(index + offset, 0, { type: 'docParagraph', attrs: { ...node.attrs, docxIndex: null, pageBreakBefore: operation.pageBreakBefore === true, dropCap: dropCap ? JSON.stringify(dropCap) : null }, ...(operation.text ? { content: [{ type: 'text', text: String(operation.text) }] } : {}) })
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    }
    else if (operation.kind === 'insertCoverPage') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'paras'].includes(key)) || operation.position !== 'before'
        || !anchor.editable || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !schema) throw new Error('草稿封面字段或来源身份无效')
      let cover: DocxPmNode[]
      try { cover = projectCoverNodes(operation.paras as never, schema) } catch { throw new Error('草稿封面字段或来源身份无效') }
      if (result.content!.indexOf(node) < 0) throw new Error('草稿插入锚点已删除')
      result.content!.splice(0, 0, ...cover)
    }
    else if (operation.kind === 'insertSectionBreak') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'type'].includes(key))
        || !SECTION_BREAK_TYPES.includes(operation.type as SectionBreakType) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿分节符字段或来源身份无效')
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      // diff 要求分节符紧邻其锚点，因此它总是该锚点的第一个 after 插入；其后的 after 插入排在分节符之后。
      if (afterCounts.get(anchor.blockId)) throw new Error('草稿分节符须紧跟锚点')
      result.content!.splice(index + 1, 0, sectionBreakNode(operation.type as SectionBreakType))
      afterCounts.set(anchor.blockId, 1)
    }
    else if (operation.kind === 'insertTable') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'rows', 'cols', 'cells'].includes(key))
        || (operation.position !== 'before' && operation.position !== 'after')
        || !anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !schema) throw new Error('草稿新增表格字段或来源身份无效')
      let table: DocxPmNode
      try { table = projectNewDocxTable({ rows: operation.rows, cols: operation.cols }, schema, operation.cells === undefined ? undefined : operation.cells as string[][]) } catch { throw new Error('草稿新增表格字段或来源身份无效') }
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      result.content!.splice(index + offset, 0, table)
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    }
    else if (operation.kind === 'insertParagraphImage') {
      // 与 insertParagraph 同回放语义；图片以 docProtected/genImage 形态回到草稿，
      // 与前端粘贴时创建的节点完全一致（filterTransaction/replay 一致性）。
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'image'].includes(key))
        || (operation.position !== 'before' && operation.position !== 'after')
        || !anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿图片粘贴字段或来源身份无效')
      const image = draftImagePayload(operation.image)
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      result.content!.splice(index + offset, 0, {
        type: 'docProtected',
        attrs: { docxIndex: null, blockType: 'image', label: '图片（粘贴）',
          imageDataUrl: `data:${image.mime};base64,${image.base64}`,
          imageWidthPx: image.widthPx, imageHeightPx: image.heightPx,
          genImage: { base64: image.base64, mime: image.mime, widthPx: image.widthPx, heightPx: image.heightPx } },
      })
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    } else if (operation.kind === 'formatParagraph') {
      const style = operation.style as Record<string, unknown>
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'style'].includes(key))
        || !style || typeof style !== 'object' || Array.isArray(style) || !Object.keys(style).length
        || Object.keys(style).some(key => !fontDialogStyleKeys(style).includes(key))) throw new Error('草稿文字格式字段或来源身份无效')
      for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style && typeof style[key] !== 'boolean') throw new Error('草稿文字格式无效')
      if ('fontSize' in style && style.fontSize !== null && (typeof style.fontSize !== 'number' || !Number.isFinite(style.fontSize) || style.fontSize < 1 || style.fontSize > (style.fontDialog === true ? 1638 : 200) || !Number.isInteger(style.fontSize * 2))) throw new Error('草稿字号无效')
      if ('fontFamily' in style && style.fontFamily !== null && (typeof style.fontFamily !== 'string' || !style.fontFamily.trim() || style.fontFamily.length > 128 || /[\x00-\x1f]/.test(style.fontFamily))) throw new Error('草稿字体无效')
      if ('highlight' in style) safeDocxHighlight(style.highlight)
      if ('vertAlign' in style && !['baseline', 'superscript', 'subscript'].includes(String(style.vertAlign))) throw new Error('草稿上下标无效')
      if ('color' in style && style.color !== null && (typeof style.color !== 'string' || !/^[a-f\d]{6}$/i.test(style.color))) throw new Error('草稿字体颜色无效')
      if ('highlight' in style) {
        safeDocxHighlight(style.highlight)
        if (!(node.content ?? []).some(run => run.type === 'text' && !!run.text) || (node.content ?? []).some(run => run.type !== 'text')) throw new Error('草稿高亮要求非空正文段落')
      }
      for (const run of node.content ?? []) {
        if (run.type !== 'text') continue
        run.marks = [...(run.marks ?? [])]
        for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style) {
          run.marks = run.marks.filter(mark => mark.type !== key)
          if (style[key]) run.marks.push({ type: key })
        }
        for (const [key, attr] of Object.entries({ color: 'color', fontSize: 'sizeHalfPoints', fontFamily: 'font', highlight: 'highlight', vertAlign: 'vertAlign', styleId: 'styleId' })) if (key in style) {
          let mark = run.marks.find(item => item.type === 'docTextStyle' || item.type === 'textStyle')
          if (!mark) { mark = { type: 'docTextStyle', attrs: {} }; run.marks.push(mark) }
          mark.attrs = { ...mark.attrs, ...(key === 'fontFamily' ? docxFontPickAttrs(style[key] as string | null) : { [attr]: style[key] === null ? null : key === 'fontSize' ? Number(style[key]) * 2 : style[key] }) }
        }
        replayFontDialog(run, style)
        run.marks = run.marks.filter(mark => !['docTextStyle', 'textStyle'].includes(mark.type) || Object.values(mark.attrs ?? {}).some(value => value != null && value !== false))
      }
    } else if (operation.kind === 'formatRange') {
      const style = operation.style as Record<string, unknown>
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'from', 'to', 'style'].includes(key))
        || !style || typeof style !== 'object' || Array.isArray(style) || !Object.keys(style).length
        || Object.keys(style).some(key => !fontDialogStyleKeys(style).includes(key))
        || (node.content ?? []).some(run => run.type !== 'text') || !validDocxLinkRange(textOf(node), operation.from, operation.to)) throw new Error('草稿局部格式字段或来源身份无效')
      for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style && typeof style[key] !== 'boolean') throw new Error('草稿文字格式无效')
      if ('fontSize' in style && style.fontSize !== null && (typeof style.fontSize !== 'number' || !Number.isFinite(style.fontSize) || style.fontSize < 1 || style.fontSize > (style.fontDialog === true ? 1638 : 200) || !Number.isInteger(style.fontSize * 2))) throw new Error('草稿字号无效')
      if ('fontFamily' in style && style.fontFamily !== null && (typeof style.fontFamily !== 'string' || !style.fontFamily.trim() || style.fontFamily.length > 128 || /[\x00-\x1f]/.test(style.fontFamily))) throw new Error('草稿字体无效')
      if ('highlight' in style) safeDocxHighlight(style.highlight)
      if ('vertAlign' in style && !['baseline', 'superscript', 'subscript'].includes(String(style.vertAlign))) throw new Error('草稿上下标无效')
      if ('color' in style && style.color !== null && (typeof style.color !== 'string' || !/^[a-f\d]{6}$/i.test(style.color))) throw new Error('草稿字体颜色无效')
      const from = Number(operation.from), to = Number(operation.to)
      let offset = 0
      node.content = (node.content ?? []).flatMap(run => {
        const start = offset, end = offset += (run.text ?? '').length
        const cuts = [start, ...[from, to].filter(at => at > start && at < end), end].sort((a, b) => a - b)
        return cuts.slice(0, -1).map((at, index) => {
          const part: DocxPmNode = { ...run, text: run.text!.slice(at - start, cuts[index + 1] - start), marks: [...(run.marks ?? []).map(mark => ({ ...mark, attrs: mark.attrs && { ...mark.attrs } }))] }
          if (at < from || at >= to) return part
          for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style) {
            part.marks = part.marks!.filter(mark => mark.type !== key)
            if (style[key]) part.marks.push({ type: key })
          }
          for (const [key, attr] of Object.entries({ color: 'color', fontSize: 'sizeHalfPoints', fontFamily: 'font', highlight: 'highlight', vertAlign: 'vertAlign', styleId: 'styleId' })) if (key in style) {
            let mark = part.marks!.find(item => item.type === 'docTextStyle' || item.type === 'textStyle')
            if (!mark) { mark = { type: 'docTextStyle', attrs: {} }; part.marks!.push(mark) }
            mark.attrs = { ...mark.attrs, ...(key === 'fontFamily' ? docxFontPickAttrs(style[key] as string | null) : { [attr]: style[key] === null ? null : key === 'fontSize' ? Number(style[key]) * 2 : style[key] }) }
          }
          replayFontDialog(part, style)
          part.marks = part.marks!.filter(mark => !['docTextStyle', 'textStyle'].includes(mark.type) || Object.values(mark.attrs ?? {}).some(value => value != null && value !== false))
          return part
        })
      })
    } else if (operation.kind === 'replaceCellText') {
      const position = anchor.cells?.flatMap((row, r) => row.map((cell, c) => ({ ...cell, r, c }))).find(cell => cell.cellId === operation.cellId)
      const cell = position && node.content?.[position.r].content?.[position.c]
      if (!cell?.content?.length) throw new Error('草稿单元格身份无效')
      replaceText(cell.content[0], String(operation.text))
      for (const paragraph of cell.content.slice(1)) replaceText(paragraph, '')
    } else throw new Error('Word 草稿包含不支持的操作')
  }
  for (const operation of operations) if (operation.kind === 'setParagraphDropCap') {
    const anchor = byId.get(String(operation.blockId))!, node = originalNodes.get(anchor.docxIndex)!
    if (!result.content?.includes(node)) throw new Error('首字下沉目标已删除')
    replayDocxDropCap(node, anchor, operation)
  }
  return replayDocxTextRevisions(replayDocxCellShading(replayDocxCellBorders(replayDocxTableStyle(result, operations, anchors), operations, anchors), operations, anchors), operations, anchors, schema)
}
