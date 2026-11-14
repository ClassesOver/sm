import {inspectDocxBookmarks,patchDocxBookmarks,type DocxBookmarkOperation} from './docx-bookmarks.ts'
import {inspectDocxCrossReferences,patchDocxCrossReference,type DocxCrossReferenceOperation} from './docx-cross-reference.ts'
import {patchDocxCaption} from './docx-caption.ts'
import {inspectDocxCommentReplies,patchDocxCommentReplies,type CommentReplyOperation} from './docx-comment-reply.ts'
import {inspectDocxCommentThreads,patchDocxCommentThreads,type CommentThreadOperation} from './docx-comment-thread.ts'
import {isDocxTocOperation, patchDocxToc} from './docx-toc.ts'
import { inspectTextRevisions, resolveTextRevisions, type TextRevisionOperation } from './docx-revisions.ts'
import { XMLValidator } from 'fast-xml-parser'
import { validatePageBorderValues, normalizedPageBorder } from './docx-page-borders.ts'
import { tableAltTextAvailability, editTableAltText, verifyTableAltTextResult } from './docx-table-alt-text.ts'
import { tableCellWrapAvailability, editTableCellWrap, verifyTableCellWrapResult } from './docx-table-cell-wrap.ts'
import { tableAlignmentAvailability, editTableAlignment, verifyTableAlignmentResult } from './docx-table-alignment.ts'
import { tableRowBreakAvailability, editTableRowBreaks, verifyTableRowBreakResult } from './docx-table-row-breaks.ts'
import { editTableCellMarginOverrides, tableCellMarginOverridesAvailability, verifyTableCellMarginOverridesResult } from './docx-table-cell-margin-overrides.ts'
import { inspectNestedTables, validateNestedCellOperation, patchNestedCellText, verifyNestedCellModel } from './docx-nested-tables.ts'
import { patchTableRepeatHeaders } from './docx-table-headers.ts'
import { docxCellBordersCapability, patchDocxTableCellBorders } from './docx-cell-borders.ts'
import { docxFontPickAttrs } from './docx-font-slots.ts'
import { DOCX_LINE_SPACING_FIELDS, docxLineSpacingPatch } from './docx-line-spacing.ts'
import { validDocxSpecialIndent } from './docx-special-indent.ts'
import { normalizeDocxRulerIndent } from './docx-ruler-indent.ts'
import { normalizeDocxTabStops } from './docx-tab-stops.ts'
import { compileNoteParagraphRuns } from './docx-note-paragraph-runs.ts'
import { docxCellShadingCapability, patchDocxCellShading } from './docx-cell-shading.ts'
import { createDocxNotesPlanner } from './docx-notes.ts'
import { parseRels, resolveRelationshipTargetPath } from '../packages/docx-engine/src/parse-package.ts'
import { createHfRelationshipInspector, hfRelsPath } from './docx-hf-relationships.ts'
import { inspectDocxCommentSource, patchDocxCommentSource } from './docx-comment-source.ts'
import { inspectDocxCommentCreation, patchDocxCommentCreation, type CommentCreationOperation } from './docx-comment-create.ts'
// GenOffice Apache-2.0: 仅从原文件解析锚点，不接受客户端 OOXML 或资源路径。
import { MAX_TABLE_STEPS, TABLE_STRUCTURE_KINDS, editTableStructure, editTableStructureSteps, tableStructureAvailability, type TableStructureKind } from './docx-table-structure.ts'
import { editTableCellShape, tableCellShapeAvailability, verifyTableCellShapeResult } from './docx-table-cell-shape.ts'
import { editTableColumnWidths, tableColumnWidthAvailability, verifyTableColumnWidthResult } from './docx-table-column-width.ts'
import { editTableRowHeights, tableRowHeightAvailability, verifyTableRowHeightResult } from './docx-table-row-height.ts'
import { editTableAutoFit, tableAutoFitAvailability, verifyTableAutoFitResult } from './docx-table-autofit.ts'
import { editTableCellTextDirection, tableCellTextDirectionAvailability, verifyTableCellTextDirectionResult } from './docx-table-cell-text-direction.ts'
import { editTableCellAlignment, tableCellAlignmentAvailability, verifyTableCellAlignmentResult } from './docx-table-cell-alignment.ts'
import { editTableCellMargins, tableCellMarginsAvailability, verifyTableCellMarginsResult } from './docx-table-cell-margins.ts'
import { createHash } from 'node:crypto'
import { removeHfReference } from '../packages/docx-engine/src/patch.ts'
import { assertDocxPageColorWritten, inspectDocxPageColor, validateDocxPageColorOperations } from './docx-page-color.ts'
import { assertDocxWatermarkWritten, inspectDocxWatermark, readDocxHeaderParts, validateDocxWatermarkOperations } from './docx-watermark.ts'
import { loadDocxZip } from '../packages/docx-engine/src/zip-load.ts'
import { attrsOf, findChild, childrenOf, nameOf, textOf, xmlParser, escapeXmlAttr } from '../packages/docx-engine/src/xml-utils.ts'
import { posix, resolve } from 'node:path'
import { readFile, writeFile, realpath, stat } from 'node:fs/promises'
import { PAGE_MARK, parseDocx, saveDocx, patchTableCellTexts, mergePPrFormat, readSections, readSectionSettings, applySectionSettings, applySectionStartType, applyTitlePg, applyPageNumType, type Block, type GeneratedBlock, type HfParagraph, type HeaderFooter, type HfPartInfo, type Run, type TableModel, type SaveBlock, type ParaFormat, type SectionSettings } from '@genoffice/docx-engine'
import { generateTableModelXml, mergeCellParaFormat, pPrWithIndLeft, pPrWithNumPr, PPR_CHILD_ORDER, RPR_CHILD_ORDER, splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate.ts'

type ObjectValue = Record<string, unknown>
const NOTE_LAYOUT_KINDS = new Set(['setParagraphAlignment', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphSpacing'])
function fail(code: string): never { throw new Error(`docx_${code}`) }
const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex')
const object = (value: unknown): ObjectValue => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail('operation_invalid')
  return value as ObjectValue
}
function keys(value: ObjectValue, allowed: string[]) {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail('operation_invalid')
}
function text(value: unknown): string {
  if (typeof value !== 'string' || value.length > 20000 || /[\x00-\x08\x0b-\x1f]/.test(value)) fail('text_invalid')
  return value as string
}
function safeLinkHref(value: unknown): value is string {
  if (typeof value !== 'string' || !value || value.length > 4096 || /[\s\x00-\x1f\x7f]/u.test(value)) return false
  try {
    const url = new URL(value)
    if (url.protocol === 'http:' || url.protocol === 'https:') return /^https?:\/\//i.test(value) && !!url.hostname && !url.username && !url.password
    return url.protocol === 'mailto:' && !!url.pathname && !value.slice('mailto:'.length).startsWith('//')
  } catch { return false }
}
function linkRange(value: ObjectValue, content: string) {
  const from = value.from, to = value.to
  if (typeof from !== 'number' || typeof to !== 'number' || !Number.isInteger(from) || !Number.isInteger(to)
      || from < 0 || from >= to || to > content.length) fail('link_range_invalid')
  for (const offset of [from, to]) {
    if (offset > 0 && offset < content.length && content.charCodeAt(offset - 1) >= 0xd800
      && content.charCodeAt(offset - 1) <= 0xdbff && content.charCodeAt(offset) >= 0xdc00
      && content.charCodeAt(offset) <= 0xdfff) fail('link_range_invalid')
  }
  return { from, to }
}
function linkedRuns(runs: Run[], from: number, to: number, href: string | null): Run[] {
  const result: Run[] = []
  let offset = 0
  for (const run of runs) {
    const end = offset + run.text.length
    const points = [...new Set([offset, end, Math.max(offset, Math.min(end, from)), Math.max(offset, Math.min(end, to))])].sort((a, b) => a - b)
    if (!run.text.length) { result.push({ ...run }); continue }
    for (let index = 0; index < points.length - 1; index++) {
      const start = points[index]!, stop = points[index + 1]!
      const part: Run = { ...run, text: run.text.slice(start - offset, stop - offset) }
      if (start >= from && stop <= to) {
        if (href === null) {
          delete part.link
          // Remove only the implied Hyperlink style; preserve other raw rPr.
          if (run.link && !run.styleId && part.rawRPr) part.rawRPr = part.rawRPr.replace(/<w:rStyle\b[^>]*w:val=["']Hyperlink["'][^>]*\/>/g, '')
        } else if (run.link?.href !== href) part.link = { ...run.link, href, rId: undefined, ...(run.link && !run.styleId && run.link.plain === undefined ? { plain: true } : {}) }
        else part.link = { ...run.link }
      }
      result.push(part)
    }
    offset = end
  }
  if (!compatibleLinkGroups(result)) fail('link_metadata_merge_unsupported')
  return result
}
/** formatRange：按 UTF-16 偏移拆分 run，区间内 run 合并字符格式（区间外 run 原样保留）。 */
function formattedRuns(runs: Run[], from: number, to: number, formatting: Partial<Run>, spec: ObjectValue): Run[] {
  const result: Run[] = []
  let offset = 0
  for (const run of runs) {
    const end = offset + run.text.length
    if (!run.text.length) { result.push({ ...run }); continue }
    const points = [...new Set([offset, end, Math.max(offset, Math.min(end, from)), Math.max(offset, Math.min(end, to))])].sort((a, b) => a - b)
    for (let index = 0; index < points.length - 1; index++) {
      const start = points[index]!, stop = points[index + 1]!
      const part: Run = { ...run, text: run.text.slice(start - offset, stop - offset) }
      result.push(start >= from && stop <= to ? applyRunFormatting(part, formatting, spec) : part)
    }
    offset = end
  }
  return result
}
function compatibleLinkGroups(runs: Run[]): boolean {
  let previous: Run['link']
  for (const run of runs) {
    const link = run.link
    if (link && previous && link.href === previous.href && !(link.rId && previous.rId && link.rId !== previous.rId)) {
      if ((link.tooltip ?? '') !== (previous.tooltip ?? '')) return false
      previous = { ...previous, rId: previous.rId ?? link.rId }
    } else previous = link
  }
  return true
}
function linksOf(block: Block) {
  const links: { from: number; to: number; href: string }[] = []
  let offset = 0
  for (const run of block.runs ?? []) {
    const end = offset + run.text.length
    if (run.link && safeLinkHref(run.link.href) && end > offset) {
      const last = links.at(-1)
      if (last && last.to === offset && last.href === run.link.href) last.to = end
      else links.push({ from: offset, to: end, href: run.link.href })
    }
    offset = end
  }
  return links
}
/** Ribbon专用：统计口径与runsToInline及固定源8项多数规则相同；原XML只删目标direct属性。 */
function ribbonStyleXml(block: Block, styleId: string): string {
  const runs = block.runs!, total = runs.reduce((sum, run) => sum + run.text.length, 0)
  const properties = ['bold', 'italic', 'underline', 'strike', 'color', 'sizeHalfPoints', 'font', 'fontAscii'] as const
  const shed = new Set(properties.filter(key => total > 0 && runs.reduce((sum, run) => sum + (run[key] ? run.text.length : 0), 0) * 2 > total))
  const tags = new Set<string>()
  for (const [key, names] of Object.entries({ bold: ['w:b', 'w:bCs'], italic: ['w:i', 'w:iCs'], underline: ['w:u'], strike: ['w:strike'], color: ['w:color'], sizeHalfPoints: ['w:sz', 'w:szCs'] })) if (shed.has(key as typeof properties[number])) names.forEach(name => tags.add(name))
  const xml = block.originalXml!.replace(/<w:r\b[^>]*>[\s\S]*?<\/w:r>/g, runXml => runXml.replace(/<w:rPr\b[^>]*(?:\/>|>[\s\S]*?<\/w:rPr>)/g, raw => {
    if (raw.endsWith('/>')) return raw
    const open = /^<w:rPr\b[^>]*>/.exec(raw)![0]
    let result = raw
    for (const child of splitXmlChildren(raw.slice(open.length, -'</w:rPr>'.length))) {
      const val = (/\bw:val=["']([^"']*)["']/.exec(child.xml)?.[1])
      const explicitOff = ['w:b', 'w:bCs', 'w:i', 'w:iCs', 'w:strike'].includes(child.name) && ['0', 'false', 'off'].includes(val ?? '')
      const absentMark = explicitOff || child.name === 'w:u' && ['none', undefined].includes(val) || child.name === 'w:color' && ['auto', undefined].includes(val)
      if (tags.has(child.name) && !absentMark) result = result.replace(child.xml, '')
      else if (child.name === 'w:rFonts' && shed.has('fontAscii')) {
        // ascii/hAnsi是fontAscii槽；eastAsia/cs及主题引用原样保留。
        result = result.replace(child.xml, child.xml.replace(/\s+w:(?:ascii|hAnsi)=(?:"[^"]*"|'[^']*')/g, ''))
      }
    }
    return result
  }))
  return paragraphStyleXml(xml, styleId)
}

function paragraphStyleXml(xml: string, styleId: string): string {
  const tag = `<w:pStyle w:val="${escapeXmlAttr(styleId)}"/>`
  const pPr = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
  if (!pPr) {
    if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return xml.replace(/\/>$/, `><w:pPr>${tag}</w:pPr></w:p>`)
    const opening = /^<w:p(?:\s[^>]*)?>/.exec(xml)?.[0]
    if (!opening) fail('paragraph_style_xml_invalid')
    return xml.slice(0, opening.length) + `<w:pPr>${tag}</w:pPr>` + xml.slice(opening.length)
  }
  const original = xml.slice(pPr.start, pPr.end)
  const styles = xmlSegments(original, 'w:pStyle', 0, original.length)
  if (styles.length > 1) fail('paragraph_style_xml_invalid')
  let patched: string
  if (styles.length) {
    const old = styles[0]!
    patched = original.slice(0, old.start) + tag + original.slice(old.end)
  } else if (/\/>$/.test(original)) patched = original.replace(/\/>$/, `>${tag}</w:pPr>`)
  else {
    const opening = /^<w:pPr\b[^>]*>/.exec(original)?.[0] ?? fail('paragraph_style_xml_invalid')
    patched = original.slice(0, opening.length) + tag + original.slice(opening.length)
  }
  return xml.slice(0, pPr.start) + patched + xml.slice(pPr.end)
}

/** Direct paragraph shading patch: simple `val="clear"` w:shd only. Pattern or
 *  theme shading in the source fails closed instead of being silently dropped. */
function paragraphShadingXml(xml: string, shading: { fill: string | null; clear: boolean }): string {
  const tag = shading.clear ? '<w:shd w:val="clear" w:color="auto" w:fill="auto"/>'
    : shading.fill ? `<w:shd w:val="clear" w:color="auto" w:fill="${shading.fill}"/>` : null
  const patch = (original: string): string => {
    const existing = xmlSegments(original, 'w:shd', 0, original.length)
    if (existing.length > 1) fail('paragraph_shading_xml_invalid')
    let base = original
    if (existing.length) {
      const old = existing[0]!
      const oldXml = original.slice(old.start, old.end)
      if (oldXml.includes('</w:shd>') || !oldXml.endsWith('/>')) fail('paragraph_shading_xml_invalid')
      const attrs = Object.fromEntries((oldXml.match(/[\w:]+="[^"]*"/g) ?? []).map(pair => { const at = pair.indexOf('='); return [pair.slice(0, at), pair.slice(at + 2, -1)] as [string, string] }))
      const keys = Object.keys(attrs)
      if (keys.some(key => !['w:val', 'w:color', 'w:fill'].includes(key)) || attrs['w:val'] !== 'clear') fail('paragraph_shading_unsupported')
      base = original.slice(0, old.start) + original.slice(old.end)
    }
    if (!tag) return base
    base = base.replace(/<w:pPr\b([^>]*)\/>/, '<w:pPr$1></w:pPr>')
    const opening = /^<w:pPr\b[^>]*>/.exec(base)?.[0]
    if (!opening) fail('paragraph_shading_xml_invalid')
    const children = base.endsWith('</w:pPr>') ? splitXmlChildren(base.slice(opening.length, -'</w:pPr>'.length)) : []
    const rank = PPR_CHILD_ORDER.indexOf('w:shd')
    const at = children.findIndex(child => PPR_CHILD_ORDER.indexOf(child.name) > rank)
    children.splice(at < 0 ? children.length : at, 0, { name: 'w:shd', xml: tag })
    return `${opening}${children.map(child => child.xml).join('')}</w:pPr>`
  }
  const pPr = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
  if (!pPr) {
    if (!tag) return xml
    if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return xml.replace(/\/>$/, `><w:pPr>${tag}</w:pPr></w:p>`)
    const opening = /^<w:p(?:\s[^>]*)?>/.exec(xml)?.[0]
    if (!opening) fail('paragraph_shading_xml_invalid')
    return xml.slice(0, opening.length) + `<w:pPr>${tag}</w:pPr>` + xml.slice(opening.length)
  }
  return xml.slice(0, pPr.start) + patch(xml.slice(pPr.start, pPr.end)) + xml.slice(pPr.end)
}

/** 新表格 OOXML：模型与固定源 apps/docs/src/renderer/editor/new-table.ts（wordTableModel/
 *  wordTableCell/wordCellParagraph/WORD_TABLE_BORDERS）一致——渲染层文件不能被 Node 桥接
 *  导入，这里按同一数据构造并交给引擎 generateTableModelXml。 */
function newWordTableXml(rows: number, cols: number, cells?: string[][]): string {
  const line = { style: 'single', szEighths: 4, color: 'auto' }
  const cell = (value: string) => {
    const paras = value.split('\n')
    return { vAlign: 'center' as const, paras, richParas: paras.map(text => ({ spaceAfter: 0, lineSpacing: 1, lineRule: 'auto' as const, runs: text === '' ? [] : [{ text }] })) }
  }
  return generateTableModelXml({
    rows: Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => cell(cells?.[r]?.[c] ?? ''))),
    colWidthsPct: Array.from({ length: cols }, () => 100 / cols),
    widthPct: 100,
    autoFit: 'window',
    borders: { top: line, bottom: line, left: line, right: line, insideH: line, insideV: line },
  } as TableModel)
}

const COVER_PARA_KEYS = ['text', 'bold', 'italic', 'color', 'sizeHalfPoints', 'align', 'spaceBefore', 'spaceAfter', 'shadingFill', 'borders', 'indentLeft', 'indentRight']
/** 封面段落规格（与前端 docx-cover-page.ts coverParaSpecs 同一受限 schema）→ 引擎生成块。 */
function coverPageBlocks(value: unknown): GeneratedBlock[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 20) fail('cover_page_invalid')
  const hex = (v: unknown) => typeof v === 'string' && /^[0-9A-Fa-f]{6}$/.test(v)
  const int = (v: unknown, min: number, max: number) => Number.isInteger(v) && (v as number) >= min && (v as number) <= max
  const blocks: GeneratedBlock[] = (value as unknown[]).map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(key => !COVER_PARA_KEYS.includes(key))) fail('cover_page_invalid')
    const p = item as ObjectValue
    const valid = (p.bold === undefined || typeof p.bold === 'boolean') && (p.italic === undefined || typeof p.italic === 'boolean')
      && (p.color === undefined || hex(p.color)) && (p.shadingFill === undefined || hex(p.shadingFill))
      && (p.sizeHalfPoints === undefined || int(p.sizeHalfPoints, 2, 400))
      && (p.align === undefined || ['left', 'center', 'right'].includes(p.align as string))
      && (p.spaceBefore === undefined || int(p.spaceBefore, 0, 14400)) && (p.spaceAfter === undefined || int(p.spaceAfter, 0, 14400))
      && (p.indentLeft === undefined || int(p.indentLeft, -31680, 31680)) && (p.indentRight === undefined || int(p.indentRight, -31680, 31680))
      && (p.borders === undefined || (typeof p.borders === 'string' && /^(?!.*(.).*\1)[tblr]{1,4}$/.test(p.borders)))
    if (!valid) fail('cover_page_invalid')
    const value = p.text === undefined ? '' : text(p.text)
    if (value.length > 2000) fail('cover_page_invalid')
    const format: ParaFormat = {
      ...(p.align ? { align: p.align as ParaFormat['align'] } : {}),
      ...(p.spaceBefore !== undefined ? { spaceBefore: p.spaceBefore as number } : {}),
      ...(p.spaceAfter !== undefined ? { spaceAfter: p.spaceAfter as number } : {}),
      ...(p.shadingFill ? { shadingFill: (p.shadingFill as string).toUpperCase() } : {}),
      ...(p.borders ? { borders: p.borders as string } : {}),
      ...(p.indentLeft !== undefined ? { indentLeft: p.indentLeft as number } : {}),
      ...(p.indentRight !== undefined ? { indentRight: p.indentRight as number } : {}),
    }
    const run: Run = { text: value, ...(p.bold ? { bold: true } : {}), ...(p.italic ? { italic: true } : {}),
      ...(p.color ? { color: (p.color as string).toUpperCase() } : {}), ...(p.sizeHalfPoints !== undefined ? { sizeHalfPoints: p.sizeHalfPoints as number } : {}) }
    return { type: 'paragraph', runs: value ? [run] : [], ...(Object.keys(format).length ? { format } : {}), ...(index === 0 ? { hiddenBookmarks: ['_GenOfficeCoverPage'] } : {}) }
  })
  blocks.push({ type: 'paragraph', runs: [], format: { pageBreakBefore: true }, hiddenBookmarks: ['_GenOfficeCoverPageEnd'] })
  return blocks
}

/** Direct paragraph page-break-before patch（固定源 page-break.ts：分页符 = 段落
 *  pageBreakBefore）。开启写入 `<w:pageBreakBefore/>`（按 pPr schema 顺序），关闭移除
 *  直接设置；来源中带非 on/off 属性或非自闭合的元素拒绝而不是静默改写。 */
function paragraphPageBreakBeforeXml(xml: string, value: boolean): string {
  const tag = value ? '<w:pageBreakBefore/>' : null
  const patch = (original: string): string => {
    let base = original
    for (const old of xmlSegments(original, 'w:pageBreakBefore', 0, original.length).reverse()) {
      const oldXml = original.slice(old.start, old.end)
      if (!/^<w:pageBreakBefore(?:\s+w:val="(?:0|1|true|false|on|off)")?\s*\/>$/.test(oldXml)) fail('paragraph_page_break_unsupported')
      base = base.slice(0, old.start) + base.slice(old.end)
    }
    if (!tag) return base
    base = base.replace(/<w:pPr\b([^>]*)\/>/, '<w:pPr$1></w:pPr>')
    const opening = /^<w:pPr\b[^>]*>/.exec(base)?.[0]
    if (!opening) fail('paragraph_page_break_xml_invalid')
    const children = base.endsWith('</w:pPr>') ? splitXmlChildren(base.slice(opening.length, -'</w:pPr>'.length)) : []
    const rank = PPR_CHILD_ORDER.indexOf('w:pageBreakBefore')
    const at = children.findIndex(child => PPR_CHILD_ORDER.indexOf(child.name) > rank)
    children.splice(at < 0 ? children.length : at, 0, { name: 'w:pageBreakBefore', xml: tag })
    return `${opening}${children.map(child => child.xml).join('')}</w:pPr>`
  }
  const pPr = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
  if (!pPr) {
    if (!tag) return xml
    if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return xml.replace(/\/>$/, `><w:pPr>${tag}</w:pPr></w:p>`)
    const opening = /^<w:p(?:\s[^>]*)?>/.exec(xml)?.[0]
    if (!opening) fail('paragraph_page_break_xml_invalid')
    return xml.slice(0, opening.length) + `<w:pPr>${tag}</w:pPr>` + xml.slice(opening.length)
  }
  return xml.slice(0, pPr.start) + patch(xml.slice(pPr.start, pPr.end)) + xml.slice(pPr.end)
}

/** Direct paragraph border patch: `w:val="single"` sides only, written in the
 *  source engine's pBdr schema order (top, left, bottom, right). A source pBdr
 *  with other line styles (none/nil/double/…), w:between/w:bar children or
 *  theme attributes fails closed instead of being silently rewritten. */
function paragraphBordersXml(xml: string, borders: { sides: string; lines: Record<string, { color?: string; szPt?: number; spacePt?: number }> } | null): string {
  const PBDR_SIDES: [string, string][] = [['top', 't'], ['left', 'l'], ['bottom', 'b'], ['right', 'r']]
  const tag = borders ? `<w:pBdr>${PBDR_SIDES.filter(([, ch]) => borders.sides.includes(ch)).map(([side, ch]) => {
    const declared = borders.lines[ch]
    // 源 generate.ts 默认笔画：sz 4 (0.5pt)、color auto、space 0（Word 上限 31）。
    const sz = Math.max(1, Math.round((declared?.szPt ?? 0.5) * 8))
    const color = declared?.color ? escapeXmlAttr(declared.color) : 'auto'
    const space = Math.min(31, Math.max(0, Math.round(declared?.spacePt ?? 0)))
    return `<w:${side} w:val="single" w:sz="${sz}" w:space="${space}" w:color="${color}"/>`
  }).join('')}</w:pBdr>` : null
  const patch = (original: string): string => {
    const existing = xmlSegments(original, 'w:pBdr', 0, original.length)
    if (existing.length > 1) fail('paragraph_borders_xml_invalid')
    let base = original
    if (existing.length) {
      const old = existing[0]!
      const oldXml = original.slice(old.start, old.end)
      if (!oldXml.endsWith('/>')) {
        if (!oldXml.endsWith('</w:pBdr>')) fail('paragraph_borders_xml_invalid')
        const opening = /^<w:pBdr\b[^>]*>/.exec(oldXml)?.[0] ?? fail('paragraph_borders_xml_invalid')
        for (const child of splitXmlChildren(oldXml.slice(opening.length, -'</w:pBdr>'.length))) {
          if (!PBDR_SIDES.some(([side]) => `w:${side}` === child.name)) fail('paragraph_borders_unsupported')
          // 源引擎的 pBdr 边永远是空元素；带内容的边（嵌套子元素）整体拒绝。
          if (!child.xml.endsWith('/>')) fail('paragraph_borders_unsupported')
          const attrs = Object.fromEntries((child.xml.match(/[\w:]+="[^"]*"/g) ?? []).map(pair => { const at = pair.indexOf('='); return [pair.slice(0, at), pair.slice(at + 2, -1)] as [string, string] }))
          if (Object.keys(attrs).some(key => !['w:val', 'w:sz', 'w:space', 'w:color'].includes(key)) || attrs['w:val'] !== 'single') fail('paragraph_borders_unsupported')
        }
      }
      base = original.slice(0, old.start) + original.slice(old.end)
    }
    if (!tag) return base
    base = base.replace(/<w:pPr\b([^>]*)\/>/, '<w:pPr$1></w:pPr>')
    const opening = /^<w:pPr\b[^>]*>/.exec(base)?.[0]
    if (!opening) fail('paragraph_borders_xml_invalid')
    const children = base.endsWith('</w:pPr>') ? splitXmlChildren(base.slice(opening.length, -'</w:pPr>'.length)) : []
    const rank = PPR_CHILD_ORDER.indexOf('w:pBdr')
    const at = children.findIndex(child => PPR_CHILD_ORDER.indexOf(child.name) > rank)
    children.splice(at < 0 ? children.length : at, 0, { name: 'w:pBdr', xml: tag })
    return `${opening}${children.map(child => child.xml).join('')}</w:pPr>`
  }
  const pPr = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
  if (!pPr) {
    if (!tag) return xml
    if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return xml.replace(/\/>$/, `><w:pPr>${tag}</w:pPr></w:p>`)
    const opening = /^<w:p(?:\s[^>]*)?>/.exec(xml)?.[0]
    if (!opening) fail('paragraph_borders_xml_invalid')
    return xml.slice(0, opening.length) + `<w:pPr>${tag}</w:pPr>` + xml.slice(opening.length)
  }
  return xml.slice(0, pPr.start) + patch(xml.slice(pPr.start, pPr.end)) + xml.slice(pPr.end)
}
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
/** 粘贴图片的严格校验（replace-picture.ts 同规）：白名单格式 + 魔数 + 规范 base64 +
 *  解码上限；显示尺寸为整数像素。gif 虽在引擎 NewImage 联合类型内，粘贴协议仅开放
 *  png/jpeg（剪贴板位图实际只产生这两类），避免把引擎的兼容面当成协议承诺。 */
function pastedPicture(value: unknown): { base64: string; mime: 'image/png' | 'image/jpeg'; widthPx: number; heightPx: number } {
  const image = object(value)
  keys(image, ['mime', 'base64', 'widthPx', 'heightPx'])
  if (image.mime !== 'image/png' && image.mime !== 'image/jpeg') fail('image_unsupported')
  const base64 = image.base64
  if (typeof base64 !== 'string' || !base64.length || base64.length > 11 * 1024 * 1024 || /[^A-Za-z0-9+/=]/.test(base64)) fail('image_invalid')
  const bytes = Buffer.from(base64, 'base64')
  if (!bytes.length || bytes.length > 8 * 1024 * 1024 || bytes.toString('base64') !== base64) fail('image_invalid')
  if (image.mime === 'image/png' ? !bytes.subarray(0, 8).equals(PNG_SIGNATURE) : !(bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff)) fail('image_invalid')
  for (const key of ['widthPx', 'heightPx'] as const) {
    if (typeof image[key] !== 'number' || !Number.isInteger(image[key]) || (image[key] as number) < 1 || (image[key] as number) > 10000) fail('image_dimensions_invalid')
  }
  return { base64, mime: image.mime, widthPx: image.widthPx as number, heightPx: image.heightPx as number }
}
function safeParagraphStyle(styles: Map<string, import('../packages/docx-engine/src/types.ts').StyleInfo>, id: unknown) {
  if (typeof id !== 'string' || !id || id.length > 255 || /[\x00-\x1f\x7f]/.test(id)) fail('paragraph_style_invalid')
  const root = styles.get(id)
  if (!root || root.styleId !== id || root.type !== 'paragraph') fail('paragraph_style_invalid')
  const seen = new Set<string>()
  let current: typeof root | undefined = root
  while (current) {
    if (seen.has(current.styleId)) fail('paragraph_style_inheritance_invalid')
    seen.add(current.styleId)
    if (current.type !== 'paragraph' || current.numPr != null || current.headingLevel != null || current.headingLevelInherited || current.headingOutlineOff) fail('paragraph_style_unsupported')
    if (current.basedOn === undefined) break
    if (!current.basedOn || seen.has(current.basedOn) || !styles.has(current.basedOn)) fail('paragraph_style_inheritance_invalid')
    current = styles.get(current.basedOn)
  }
  return root
}
function simpleParagraphXml(xml: string): boolean {
  if (/^<w:p(?:\s[^>]*)?\/>$/.test(xml)) return true
  if (!/^<w:p(?:\s|>)/.test(xml) || !xml.endsWith('</w:p>')) return false
  if (/<w:(?:sectPr|pPrChange|rPrChange|numPrChange)\b/.test(xml)) return false
  // Unmodeled link attributes stay read-only rather than being flattened.
  if (/<w:hyperlink\b[^>]*\/>/.test(xml)) return false
  const linkTooltips = new Map<string, string>()
  for (const match of xml.matchAll(/<w:hyperlink\b([^>]*)>/g)) {
    const attributes = match[1]!
    const relationship = /\br:id=["']([^"']+)["']/.exec(attributes)?.[1] ?? ''
    const tooltip = /\bw:tooltip=(["'])([\s\S]*?)\1/.exec(attributes)?.[2] ?? ''
    // Upstream mergeRuns may merge equal-rId runs before exposing tooltip differences.
    if (linkTooltips.has(relationship) && linkTooltips.get(relationship) !== tooltip) return false
    linkTooltips.set(relationship, tooltip)
    if (!/\br:id=/.test(attributes) || attributes.replace(/(?:r:id|w:tooltip)\s*=\s*(?:"[^"]*"|'[^']*')/g, '').trim()) return false
  }
  const body = xml.replace(/<w:pPr\b[^>]*(?:\/>|>[\s\S]*?<\/w:pPr>)/g, '')
    .replace(/<w:rPr\b[^>]*(?:\/>|>[\s\S]*?<\/w:rPr>)/g, '')
  return [...body.matchAll(/<\/?([\w:.-]+)/g)].every(match => ['w:p', 'w:r', 'w:t', 'w:tab', 'w:br', 'w:cr', 'w:hyperlink'].includes(match[1]!))
}
/** A paragraph whose only non-simple content is the gallery cover's hidden
 *  _GenOfficeCoverPage / _GenOfficeCoverPageEnd bookmarks (editor/cover-pages.ts).
 *  It stays read-only for editing (a rewrite could drop the markers "Remove
 *  Current Cover Page" relies on) but may be deleted as a whole, so a saved
 *  cover can be removed or replaced. */
function coverMarkerParagraph(block: Block): boolean {
  if (block.type !== 'paragraph' || !block.originalXml) return false
  const xml = block.originalXml
  const ids = [...xml.matchAll(/<w:bookmarkStart\b[^>]*\/>/g)].map(match => match[0])
  if (!ids.length) return false
  const coverIds: string[] = []
  for (const start of ids) {
    const name = /\bw:name="([^"]*)"/.exec(start)?.[1]
    if (name !== '_GenOfficeCoverPage' && name !== '_GenOfficeCoverPageEnd') return false
    coverIds.push(/\bw:id="([^"]*)"/.exec(start)?.[1] ?? '')
  }
  const stripped = xml.replace(/<w:bookmarkStart\b[^>]*\/>/g, '')
    .replace(/<w:bookmarkEnd\b[^>]*\/>/g, end => coverIds.includes(/\bw:id="([^"]*)"/.exec(end)?.[1] ?? '\u0000') ? '' : end)
  return simpleParagraphXml(stripped)
}
function editableParagraph(block: Block): boolean {
  return ['paragraph', 'heading', 'listItem'].includes(block.type) && Array.isArray(block.runs) &&
    !!block.originalXml && simpleParagraphXml(block.originalXml) && compatibleLinkGroups(block.runs) && block.runs.every(run => !run.link || safeLinkHref(run.link.href))
}
/** 注释引用是独立编辑能力，不放宽普通正文的 editableParagraph。 */
function editableNoteReferenceBlock(block: Block): boolean {
  if (parsed.protection?.enforced || !block.originalXml || !block.runs || block.runs.some(run => run.noteRef && (run.link || run.ref || run.ins || run.del))) return false
  let supported = true
  const originalXml = block.originalXml.replace(/<w:(?:footnote|endnote)Reference\b([^>]*)\/>/g, (xml, attrs: string) => {
    if (!/^\s*w:id=["']\d+["']\s*$/.test(attrs)) supported = false
    return ''
  })
  return supported && editableParagraph({ ...block, originalXml, runs: block.runs.filter(run => !run.noteRef) })
}
function cellXmls(block: Block): string[][] {
  if (block.type !== 'table' || !block.originalXml) return []
  const xml = block.originalXml
  return xmlSegments(xml, 'w:tr', 0, xml.length).map(row =>
    xmlSegments(xml, 'w:tc', row.start, row.end).map(cell => xml.slice(cell.start, cell.end)))
}
function editableTable(block: Block): boolean {
  return !!block.originalXml && !/<w:(?:ins|del|moveFrom|moveTo|sdt|vMerge|hMerge|gridSpan|trPrChange|tblPrChange|cellIns|cellDel)\b/.test(block.originalXml)
}
function editableCell(xml: string): boolean {
  // 合并/嵌套/域/图片/修订只读，避免上游复杂单元格 patch 静默无操作或展平。
  if (/<w:(?:tbl|hyperlink|vMerge|hMerge|gridSpan|ins|del|tcPrChange|cellIns|cellDel)\b/.test(xml)) return false
  const paragraphs = xmlSegments(xml, 'w:p', 0, xml.length)
  if (!paragraphs.length || !paragraphs.every(p => simpleParagraphXml(xml.slice(p.start, p.end)))) return false
  const shell = xml.replace(/<w:tcPr\b[^>]*(?:\/>|>[\s\S]*?<\/w:tcPr>)/g, '')
    .replace(/<w:p(?:\s[^>]*)?\/>|<w:p(?:\s[^>]*)?>[\s\S]*?<\/w:p>/g, '')
  return /^<w:tc(?:\s[^>]*)?>\s*<\/w:tc>$/.test(shell)
}
/** null removes direct properties and their theme/complex-script companions. */
function applyRunFormatting(run: Run, formatting: Partial<Run>, spec: ObjectValue): Run {
  const next = { ...run, ...formatting }
  if (spec.vertAlign === 'baseline') { next.vertAlign = undefined; next.rawRPr = baselineRunProperties(next.rawRPr) }
  const tags = new Set<string>()
  if (spec.fontFamily === null) {
    for (const key of ['font', 'fontAscii', 'fontCs', 'eastAsiaFont', 'themeRFonts']) delete (next as unknown as ObjectValue)[key]
    tags.add('w:rFonts')
  }
  if (spec.fontSize === null) { delete next.sizeHalfPoints; tags.add('w:sz'); tags.add('w:szCs') }
  if (spec.color === null) { delete next.color; delete next.themeColor; tags.add('w:color') }
  if (tags.size && next.rawRPr) {
    const open = /^<w:rPr\b[^>]*>/.exec(next.rawRPr)?.[0]
    if (open && next.rawRPr.endsWith('</w:rPr>')) next.rawRPr = open + splitXmlChildren(next.rawRPr.slice(open.length, -'</w:rPr>'.length)).filter(child => !tags.has(child.name)).map(child => child.xml).join('') + '</w:rPr>'
  }
  return next
}
function style(value: unknown): Partial<Run> {
  const spec = object(value)
  keys(spec, ['bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color', 'highlight', 'vertAlign'])
  if (!Object.keys(spec).length) fail('style_invalid')
  const result: Partial<Run> = {}
  for (const name of ['bold', 'italic', 'underline', 'strike'] as const) {
    if (spec[name] !== undefined) {
      if (typeof spec[name] !== 'boolean') fail('style_invalid')
      result[name] = spec[name] as boolean
    }
  }
  if (spec.fontSize !== undefined && spec.fontSize !== null) {
    if (typeof spec.fontSize !== 'number' || !Number.isFinite(spec.fontSize) || spec.fontSize < 1 || spec.fontSize > 200 || !Number.isInteger(spec.fontSize * 2)) fail('style_invalid')
    result.sizeHalfPoints = (spec.fontSize as number) * 2
  }
  if (spec.fontFamily !== undefined && spec.fontFamily !== null) {
    if (typeof spec.fontFamily !== 'string' || !spec.fontFamily.trim() || spec.fontFamily.length > 128 || /[\x00-\x1f]/.test(spec.fontFamily)) fail('style_invalid')
    Object.assign(result, docxFontPickAttrs(spec.fontFamily as string))
  }
  if (spec.color !== undefined && spec.color !== null) {
    if (typeof spec.color !== 'string' || !/^[a-f\d]{6}$/i.test(spec.color)) fail('style_invalid')
    result.color = (spec.color as string).toUpperCase()
  }
  if ('vertAlign' in spec) {
    if (!['baseline', 'superscript', 'subscript'].includes(String(spec.vertAlign))) fail('vertical_align_invalid')
    if (spec.vertAlign !== 'baseline') result.vertAlign = spec.vertAlign as 'superscript' | 'subscript'
  }
  if ('highlight' in spec) {
    if (typeof spec.highlight !== 'string' || !['yellow', 'green', 'cyan', 'magenta', 'blue', 'red', 'darkBlue', 'darkCyan', 'darkGreen', 'darkMagenta', 'darkRed', 'darkYellow', 'darkGray', 'lightGray', 'black', 'white', 'none'].includes(spec.highlight)) fail('highlight_invalid')
    // none explicitly overrides inheritance, unlike deleting w:highlight.
    result.highlight = spec.highlight
  }
  return result
}
// Removing direct alignment can reveal inherited style alignment; baseline is explicit.
function baselineRunProperties(raw = ''): string {
  const originalOpen = /^<w:rPr\b(?:"[^"]*"|'[^']*'|[^'">])*?>/.exec(raw)?.[0]
  const open = (originalOpen ?? '<w:rPr>').replace(/\/>$/, '>')
  const children = raw.endsWith('</w:rPr>') ? splitXmlChildren(raw.slice(open.length, -'</w:rPr>'.length)).filter(child => child.name !== 'w:vertAlign') : []
  const rank = RPR_CHILD_ORDER.indexOf('w:vertAlign')
  const at = children.findIndex(child => RPR_CHILD_ORDER.indexOf(child.name) > rank)
  children.splice(at < 0 ? children.length : at, 0, { name: 'w:vertAlign', xml: '<w:vertAlign w:val="baseline"/>' })
  return `${open}${children.map(child => child.xml).join('')}</w:rPr>`
}
function generated(block: Block): GeneratedBlock {
  return { type: block.type as GeneratedBlock['type'], level: block.level, outlineOnly: block.outlineOnly,
    styleId: block.styleId, list: block.list, format: block.format, rawPPr: block.rawPPr,
    // Original unstyled links must stay unstyled even when this paragraph regenerates.
    runs: block.runs!.map(run => ({ ...run, ...(run.link ? { link: { ...run.link,
      ...(!run.styleId && run.link.plain === undefined ? { plain: true } : {}) } } : {}) })) }
}
/** 固定源 clearAllFormatting：选区去 marks，再按多数覆盖规则应用默认样式、清段落直接属性。 */
function withoutRawProperties(raw: string | undefined, root: string, tags: Set<string>): string {
  if (!raw) return ''
  const opening = new RegExp(`^<${root}\\b[^>]*>`).exec(raw)?.[0]
  const closing = `</${root}>`
  if (!opening || !raw.endsWith(closing)) return ''
  return opening + splitXmlChildren(raw.slice(opening.length, -closing.length)).filter(child => !tags.has(child.name)).map(child => child.xml).join('') + closing
}
function clearedParagraph(block: Block, ranges: { from: number; to: number }[], defaultStyleId: string | undefined): GeneratedBlock {
  const result = generated(block), length = result.runs.map(run => run.text).join('').length
  for (const range of ranges) {
    let offset = 0
    result.runs = result.runs.flatMap(run => {
      const start = offset, stop = offset += run.text.length
      const cuts = [...new Set([start, stop, Math.max(start, Math.min(stop, range.from)), Math.max(start, Math.min(stop, range.to))])].sort((a, b) => a - b)
      return cuts.slice(0, -1).map((at, index) => {
        const end = cuts[index + 1]!, text = run.text.slice(at - start, end - start)
        return at >= range.from && end <= range.to ? { text } : { ...run, text }
      })
    })
    const groups = [
      { field: 'bold', tags: ['w:b', 'w:bCs'] }, { field: 'italic', tags: ['w:i', 'w:iCs'] },
      { field: 'underline', tags: ['w:u'] }, { field: 'strike', tags: ['w:strike'] },
      { field: 'color', tags: ['w:color'], companions: ['themeColor'] },
      { field: 'sizeHalfPoints', tags: ['w:sz', 'w:szCs'] },
      { field: 'font', tags: ['w:rFonts'] },
      { field: 'fontAscii', tags: ['w:rFonts'] },
    ]
    // 覆盖统计必须基于同一快照，不能因前一属性清除改变后一属性计数。
    const shed = groups.filter(group => result.runs.reduce((sum, run) => sum + ((run as unknown as ObjectValue)[group.field] != null && (run as unknown as ObjectValue)[group.field] !== false ? run.text.length : 0), 0) * 2 > length)
    for (const run of result.runs) for (const group of shed) {
      for (const key of [group.field, ...(group.companions ?? [])]) delete (run as unknown as ObjectValue)[key]
      run.rawRPr = withoutRawProperties(run.rawRPr, 'w:rPr', new Set(group.tags))
    }
  }
  result.type = result.type === 'heading' ? 'paragraph' : result.type
  delete result.level; delete result.outlineOnly
  result.styleId = defaultStyleId
  const tags = new Set(['w:pStyle', 'w:jc', 'w:spacing', 'w:ind', 'w:contextualSpacing', 'w:keepNext', 'w:keepLines', 'w:widowControl', 'w:suppressLineNumbers', 'w:shd', 'w:pBdr', 'w:tabs', 'w:framePr', 'w:pageBreakBefore', 'w:outlineLvl'])
  result.rawPPr = withoutRawProperties(block.rawPPr, 'w:pPr', tags) || '<w:pPr></w:pPr>'
  if (defaultStyleId) result.rawPPr = result.rawPPr.replace(/^(<w:pPr\b[^>]*>)/, `$1<w:pStyle w:val="${escapeXmlAttr(defaultStyleId)}"/>`)
  // 列表原样式的隐式 numPr 必须具体化，切回 Normal 后仍保持原编号。
  if (block.type === 'listItem' && block.list && !/<w:numPr\b/.test(result.rawPPr)) result.rawPPr = pPrWithNumPr(result.rawPPr, block.list)
  // rawPPr 已精确保留未清除的属性（含 numPr/sectPr）；避免模型中的旧继承值复活。
  result.format = undefined
  return result
}
function pPrWithIndRight(pPr: string, right: number): string {
  let out = pPr.replace(/<w:pPr([^>]*)\/>/, '<w:pPr$1></w:pPr>')
  const value = ` w:right="${right}" w:rightChars="0"`
  const ind = /<w:ind\b([^>]*)\/>/.exec(out)
  const tag = `<w:ind${value}/>`
  if (ind) {
    const attrs = ind[1]!.replace(/\s+w:(right|end|rightChars|endChars)="[^"]*"/g, '')
    out = out.replace(ind[0], `<w:ind${`${attrs}${value}`}/>`)
  } else {
    if (!out) return `<w:pPr>${tag}</w:pPr>`
    const at = [out.indexOf('<w:jc '), out.indexOf('<w:rPr')].filter(index => index !== -1)
    const insertAt = at.length ? Math.min(...at) : out.lastIndexOf('</w:pPr>')
    out = out.slice(0, insertAt) + tag + out.slice(insertAt)
  }
  return out === '<w:pPr></w:pPr>' ? '' : out
}

function pPrWithZeroSpaceBefore(pPr: string): string {
  // 上游 serializer 省略 before=0；直接写零，阻止 Word 重新继承样式的段前间距。
  const spacing = /<w:spacing\b([^>]*)\/>/.exec(pPr)
  if (spacing) return pPr.replace(spacing[0], `<w:spacing${spacing[1]!.replace(/\s+w:before="[^"]*"/g, '')} w:before="0"/>`)
  const opening = /^<w:pPr(?:\s[^>]*)?>/.exec(pPr)?.[0] ?? '<w:pPr>'
  const children = pPr.endsWith('</w:pPr>') ? splitXmlChildren(pPr.slice(opening.length, -'</w:pPr>'.length)) : []
  const at = children.findIndex(child => PPR_CHILD_ORDER.indexOf(child.name) > PPR_CHILD_ORDER.indexOf('w:spacing'))
  children.splice(at < 0 ? children.length : at, 0, { name: 'w:spacing', xml: '<w:spacing w:before="0"/>' })
  return `${opening}${children.map(child => child.xml).join('')}</w:pPr>`
}

// ---- 页眉/页脚部件编辑（setHeaderFooter）----
// 语义对齐固定源 hf-editor/patch.ts：文本按段重写（字符按原 run 分布，保留原字符格式与
// PAGE/NUMPAGES 域标记），非文本段（布局表格/浮动框）不进重写集合，由引擎外科合并保留原
// 字节；引用与关系写回由引擎 planHeaderFooter 复用（改写被引用 part 或新建 part + 关系）。
const HF_VARIANTS = ['default', 'first', 'even'] as const
type HfVariant = (typeof HF_VARIANTS)[number]
const PAGE_NUMBER_FORMATS = new Set(['decimal', 'numberInDash', 'lowerLetter', 'upperLetter', 'lowerRoman', 'upperRoman', 'hebrew1', 'arabicAlpha', 'arabicAbjad', 'chicago', 'thousandSeparator', 'chineseCounting', 'chineseCountingThousand', 'chineseLegalSimplified', 'koreanDigital', 'koreanCounting', 'japaneseCounting', 'aiueo', 'iroha', 'decimalEnclosedCircle', 'decimalFullWidth'])
type HeaderFooterPart = 'header' | 'footer'
type HeaderFooterEdit = {
  afterLink?: boolean; sourceXml: string; align?: 'left' | 'center' | 'right'; section: typeof trailingSection; part: HeaderFooterPart; variant: HfVariant; value: HeaderFooter; pageNumber: boolean; lines: string[]
  titlePg?: boolean; evenAndOddHeaders?: boolean; pageNumberFmt?: string | null; pageNumberStart?: number | null
}

/** 引擎 parse 与保存共用：页码字段以 PAGE_MARK 文本承载，落盘时由 headerFooterPartXml 写回 fldChar 域。 */
function simpleHfPara(para: HfParagraph): boolean {
  return !para.cells && !para.row && !para.box && !para.boxAnchored
}
/** 文本按原 run 的字符数分布（replaceParagraph 同规），保留每个 run 的字符格式/域标记。 */
function redistributeHfRuns(runs: Run[], value: string): Run[] {
  if (!runs.length) return value ? [{ text: value }] : []
  const remaining = Array.from(value)
  return runs.map((run, index) => {
    const length = index === runs.length - 1 ? remaining.length : Array.from(run.text).length
    return { ...run, text: remaining.splice(0, length).join('') }
  })
}
/** 编辑文本 → 引擎 HeaderFooter：新行按序配对到原可编辑文本段（多余行以末段为模板追加），
 *  非文本段不进重写集合（外科合并保留原字节，避免浮动框/表格双写）。 */
function hfValueFromText(info: HfPartInfo | null, value: string, pageNumber: boolean, align: 'left' | 'center' | 'right' | undefined): HeaderFooter {
  const lines = value.split('\n')
  const source = info?.paras ?? []
  const simple = source.filter(simpleHfPara)
  const paras: HfParagraph[] = []
  let line = 0
  for (const para of source) {
    if (!simpleHfPara(para)) continue
    if (line >= lines.length) break
    const next = lines[line++]!
    const runs = redistributeHfRuns(para.runs ?? [], next)
    paras.push({ ...para, ...(align ? { align } : {}), runs })
  }
  for (; line < lines.length; line++) {
    const template = simple.at(-1)
    paras.push({ ...(template ?? { align: align ?? 'center' }), runs: [{ text: lines[line]! }], ...(align ? { align } : {}) })
  }
  const text = lines.join('')
  return { text, paras, pageNumber }
}
/** 保存后独立回读的期望文本（引擎落盘规则：无 PAGE_MARK 且要求页码时首个 '#' 转域，否则追加居中页码段）。 */
function expectedHfText(edit: HeaderFooterEdit): string {
  const joined = edit.lines.join('')
  if (joined.includes(PAGE_MARK) || !edit.pageNumber) return joined
  if (joined.includes('#')) return joined.replace('#', PAGE_MARK)
  return `${joined}${PAGE_MARK}`
}
/** 回读部件的可编辑文本投影：与 hfValueFromText 同口径，只取简单文本段（布局表格/浮动框
 *  不进重写集合、由引擎原字节保留），避免把保留内容的文字计入期望比较。 */
function editableHfText(info: HfPartInfo): string {
  if (!info.paras) return info.text
  return info.paras.filter(simpleHfPara).map(para => (para.runs ?? []).map(run => run.text).join('')).join('')
}
/** document.xml.rels 的 rId → 包内 part 路径（相对 word/ 解析）。 */
function resolvePartPath(base: string, target: string): string {
  return resolveRelationshipTargetPath(`${base}/document.xml`, target) ?? ''
}

const requestBytes = await readFile(process.argv[2] ?? fail('request_missing'))
if (requestBytes.length > 12 * 1024 * 1024) fail('operations_too_large')
const request = object(JSON.parse(requestBytes.toString('utf8')))
keys(request, ['kind', 'input', 'output', 'operations'])
if (!['inspect', 'patch'].includes(request.kind as string) || typeof request.input !== 'string') fail('request_invalid')
const bytes = new Uint8Array(await readFile(request.input as string))
if (!bytes.length || bytes.length > 24 * 1024 * 1024) fail('content_invalid_or_too_large')
const sourceSha256 = hash(bytes)
const needsCommentSource = request.kind === 'inspect' || Array.isArray(request.operations)
  && request.operations.some(raw => raw && typeof raw === 'object' && !Array.isArray(raw) && (raw as ObjectValue).kind === 'editCommentText')
const commentSource = needsCommentSource ? await inspectDocxCommentSource(bytes) : null
const commentCreation = request.kind === 'inspect' ? await inspectDocxCommentCreation(bytes) : null
const commentReplies = request.kind === 'inspect' ? await inspectDocxCommentReplies(bytes) : null
const commentThreads = request.kind === 'inspect' ? await inspectDocxCommentThreads(bytes) : null
const bookmarks = request.kind === 'inspect' ? await inspectDocxBookmarks(bytes) : null
const crossReferences = request.kind === 'inspect' ? await inspectDocxCrossReferences(bytes) : null
const parsed = await parseDocx(bytes)
const blocks = parsed.blocks.filter(block => !block.hidden)
const sourceZip = await loadDocxZip(bytes)
// core 只持有段 XML；授权宿主另外证明 document/body 命名空间及真实顶层归属。
const revisionWordNamespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
// 厂商 protection parser 只识别字面 w: 前缀/值；宿主按实际命名空间解码，防止别名或实体绕过。
const revisionSettingsXml = await sourceZip.file('word/settings.xml')?.async('string')
function hasRevisionProtection(xml: string | undefined): boolean {
  if (!xml) return false
  if (XMLValidator.validate(xml) !== true || /<!/.test(xml)) return true
  const visit = (node: Record<string, unknown>, inherited: Record<string, string>): boolean => {
    const attrs = attrsOf(node), namespaces = { ...inherited }
    for (const [key, value] of Object.entries(attrs)) if (key.startsWith('xmlns:')) namespaces[key.slice(6)] = value
    const [prefix, local] = (nameOf(node) ?? '').split(':')
    if (local === 'documentProtection' && namespaces[prefix!] === revisionWordNamespace) {
      const enforcement = Object.entries(attrs).find(([key]) => {
        const [attributePrefix, attributeLocal] = key.split(':')
        return attributeLocal === 'enforcement' && namespaces[attributePrefix!] === revisionWordNamespace
      })?.[1]
      if (!enforcement || !['0', 'false', 'off'].includes(enforcement)) return true
    }
    return childrenOf(node).some(child => visit(child, namespaces))
  }
  return xmlParser.parse(xml).some((node: Record<string, unknown>) => visit(node, {}))
}
const revisionProtected = !!parsed.protection?.enforced || hasRevisionProtection(revisionSettingsXml)
// 固定源 Design ▸ Page Color：整篇 w:background；只读原因与来源摘要随 inspect 下发。
const pageColorModel = inspectDocxPageColor(await sourceZip.file('word/document.xml')?.async('string') ?? '', !!parsed.protection?.enforced)
// 固定源 Design ▸ Watermark：全部页眉部件摘要绑定来源；受保护文档只读。
const watermarkModel = await inspectDocxWatermark(sourceZip, !!parsed.protection?.enforced)
const revisionDocumentXml = await sourceZip.file('word/document.xml')!.async('string')
const revisionDocument = xmlParser.parse(revisionDocumentXml).find((node: any) => nameOf(node) === 'w:document')
const revisionBodyNodes = revisionDocument ? childrenOf(revisionDocument).filter(node => nameOf(node) === 'w:body') : []
const revisionNamespaceValid = XMLValidator.validate(revisionDocumentXml) === true
  && !/<!|<\?(?!xml\s)/.test(revisionDocumentXml)
  && !!revisionDocument && attrsOf(revisionDocument)['xmlns:w'] === revisionWordNamespace
  && revisionBodyNodes.length === 1
  && (!('xmlns:w' in attrsOf(revisionBodyNodes[0]!)) || attrsOf(revisionBodyNodes[0]!)['xmlns:w'] === revisionWordNamespace)
const revisionBodyElements = splitXmlChildren(revisionDocumentXml.slice(parsed.internal.bodyInnerStart, parsed.internal.bodyInnerEnd))
function revisionScopeReason(block: Block): string | null {
  if (!revisionNamespaceValid) return 'docx_revision_namespace_unsupported'
  const source = revisionBodyElements[block.docxIndex ?? -1]
  if (!source || source.name !== 'w:p' || source.xml !== block.originalXml || block.sdtShell) return 'docx_revision_block_unsupported'
  return null
}
function revisionAvailability(block: Block) {
  const scopeReason = revisionScopeReason(block)
  if (scopeReason) return { reviewTargets: [], revisionReadOnlyReason: scopeReason }
  const info = inspectTextRevisions(block, blockId(block), revisionProtected)
  if (info.revisionReadOnlyReason || !info.reviewTargets.length) return info
  // 按原段所有 inline 的真实贡献累积 UTF-16 位置；不能从 w:id 或 PM mark 序号猜目标。
  try {
    const paragraph = xmlParser.parse(block.originalXml!)[0]
    let offset = 0, ordinal = 0, sourceText = ''
    const ranges: { from: number; to: number; text: string }[] = []
    const zeroWidth = new Set(['w:pPr', 'w:bookmarkStart', 'w:bookmarkEnd', 'w:commentRangeStart', 'w:commentRangeEnd', 'w:commentReference', 'w:proofErr'])
    const inlineText = (node: Record<string, unknown>): string => {
      const name = nameOf(node)
      if (name === 'w:rPr' || zeroWidth.has(name!)) return ''
      if (name === 'w:t' || name === 'w:delText') return textOf(node)
      if (name === 'w:tab') return '\t'
      if (name === 'w:cr') return '\n'
      if (name === 'w:br') {
        const type = attrsOf(node)['w:type'], clear = attrsOf(node)['w:clear']
        if (type && !['textWrapping', 'page', 'column'].includes(type) || clear && !['none', 'left', 'right', 'all'].includes(clear)) throw new Error('break')
        return clear ? '\u001e' : type === 'page' ? '\f' : type === 'column' ? '\v' : '\n'
      }
      if (name === 'w:r' || name === 'w:hyperlink' || name === 'w:ins' || name === 'w:del') return childrenOf(node).map(inlineText).join('')
      throw new Error('inline')
    }
    for (const node of childrenOf(paragraph)) {
      const name = nameOf(node), text = inlineText(node), from = offset
      offset += text.length
      sourceText += text
      if (name === 'w:ins' || name === 'w:del') {
        const target = info.reviewTargets[ordinal++]
        if (!target || target.type !== (name === 'w:ins' ? 'insertion' : 'deletion')) throw new Error('target')
        ranges.push({ from, to: offset, text })
      }
    }
    if (ordinal !== info.reviewTargets.length || sourceText !== (block.runs ?? []).map(run => run.text).join('')) throw new Error('projection')
    return { ...info, reviewTargets: info.reviewTargets.map((target, index) => ({ ...target, sourceRange: ranges[index]! })) }
  } catch { return { reviewTargets: [], revisionReadOnlyReason: 'docx_revision_projection_unsupported' } }
}
// document.xml.rels 的内部关系表：页眉/页脚引用 rId → part 路径（外部链接关系不参与）。
const relTargets = new Map<string, string>()
{
  const relsXml = await sourceZip.file('word/_rels/document.xml.rels')?.async('string')
  for (const match of relsXml?.matchAll(/<Relationship\b[^>]*>/g) ?? []) {
    const tag = match[0]
    const id = /\bId="([^"]+)"/.exec(tag)?.[1]
    const target = /\bTarget="([^"]+)"/.exec(tag)?.[1]
    if (id && target && /\bTargetMode="External"/.test(tag) === false) relTargets.set(id, resolvePartPath('word', target))
  }
}
const sourceStylesXml = await sourceZip.file('word/styles.xml')?.async('string')
const sourceStyleNodes = sourceStylesXml ? childrenOf(xmlParser.parse(sourceStylesXml).find((node: any) => node['w:styles']) ?? {}) : []
const rawStyles = new Map(sourceStyleNodes.filter(node => node['w:style']).map(node => [attrsOf(node)['w:styleId'], node]))
function sourceParagraphStyle(id: unknown) {
  const style = safeParagraphStyle(parsed.styles, id)
  let current: string | undefined = style.styleId
  const seen = new Set<string>()
  while (current) {
    if (seen.has(current)) fail('paragraph_style_inheritance_invalid')
    seen.add(current)
    const raw = rawStyles.get(current)
    if (!raw || attrsOf(raw)['w:type'] !== 'paragraph') fail('paragraph_style_invalid')
    const properties = findChild(raw, 'w:pPr')
    if (properties && ['w:numPr', 'w:outlineLvl', 'w:bidi', 'w:tabs', 'w:framePr', 'w:textDirection', 'w:wordWrap', 'w:overflowPunct', 'w:autoSpaceDE', 'w:autoSpaceDN'].some(name => findChild(properties, name))) fail('paragraph_style_unsupported')
    const display = parsed.styles.get(current)?.display as Record<string, unknown> | undefined
    if (display && ['bidi', 'rtl', 'tabStops', 'indentChars', 'autoSpaceDE', 'autoSpaceDN', 'wordWrap', 'overflowPunct', 'eastAsiaLang', 'frame', 'dropCap'].some(key => display[key] != null)) fail('paragraph_style_unsupported')
    current = attrsOf(findChild(raw, 'w:basedOn') ?? {})['w:val']
  }
  return style
}
function paragraphStyleEditable(block: Block) {
  if (parsed.protection?.enforced || block.type !== 'paragraph' || !block.originalXml || !simpleParagraphXml(block.originalXml.replace(/<w:bookmark(?:Start|End)\b[^>]*\/>/g, ''))) return false
  try {
    const id = block.styleId ?? [...parsed.styles.values()].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
    if (id) sourceParagraphStyle(id)
    return true
  } catch { return false }
}
function paragraphDecorationEditable(block: Block, kind: 'shading' | 'borders'): boolean {
  if (parsed.protection?.enforced || !(editableParagraph(block) || notesPlanner && editableNoteReferenceBlock(block))) return false
  try {
    // 纯字符串探测，丢弃返回值；复用实际 writer 的来源限制，不改 block/ZIP 或源文件。
    if (kind === 'shading') paragraphShadingXml(block.originalXml!, { fill: null, clear: false })
    else paragraphBordersXml(block.originalXml!, null)
    return true
  } catch { return false }
}
const blockId = (block: Block) => hash(`${sourceSha256}:block:${block.docxIndex}`)
const cellId = (block: Block, row: number, column: number) => hash(`${sourceSha256}:cell:${block.docxIndex}:${row}:${column}`)
const allSections = readSections(parsed)
const trailingSection = allSections.at(-1)!
const sectionIdOf = (section: { lastBlockIndex: number }) => hash(`${sourceSha256}:section:${section.lastBlockIndex}`)
/** 非尾节的设置以其分节段 sectPr 为准；尾节沿用 readSectionSettings（含文档级 gutterAtTop）。 */
const sectionSettingsOf = (section: typeof trailingSection) => section === trailingSection ? readSectionSettings(parsed) : section.settings
const tableColumnWidthSection = (block: Block) => allSections.find(item => item.firstBlockIndex <= block.docxIndex! && block.docxIndex! <= item.lastBlockIndex)
const tableColumnWidthSectionId = (block: Block) => { const section = tableColumnWidthSection(block); return section ? sectionIdOf(section) : null }
function rulerIndentEditable(block: Block): boolean {
  const section = tableColumnWidthSection(block)
  // 与源方向识别使用同一RTL脚本族；混合RTL文本也保守只读，不猜测逻辑左右坐标。
  return !parsed.protection?.enforced && !parsed.mirrorMargins && !!section && (sectionSettingsOf(section).columns ?? 1) === 1
    && editableParagraph(block) && ['paragraph', 'heading'].includes(block.type) && !block.format?.bidi && !block.format?.bidiInherited
    && !Object.values(block.format?.charIndents ?? {}).some(value => value !== 0)
    && !block.runs?.some(run => run.rtl || /[\p{Script=Hebrew}\p{Script=Arabic}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}\p{Script=Samaritan}\p{Script=Mandaic}]/u.test(run.text))
}
function tabStopsEditable(block: Block): boolean {
  if (!rulerIndentEditable(block) || /<w:ptab\b/.test(block.originalXml ?? '')) return false
  try {
    // 未建模的tabs属性/子节点不能随整组重写丢失；样式链的未知值也不直接化。
    const check = (properties: Record<string, unknown> | undefined) => {
      if (!properties) return
      const tabs = childrenOf(properties).filter(node => nameOf(node) === 'w:tabs')
      if (tabs.length > 1) fail('tabs_source_unsupported')
      for (const node of tabs) {
        if (Object.keys(attrsOf(node)).length) fail('tabs_source_unsupported')
        const values = []
        for (const child of childrenOf(node)) {
          if ('#text' in child && String(child['#text']).trim() === '') continue
          if (nameOf(child) !== 'w:tab' || childrenOf(child).length) fail('tabs_source_unsupported')
          const attrs = attrsOf(child)
          if (Object.keys(attrs).some(key => !['w:pos','w:val','w:leader'].includes(key)) || !/^-?\d+$/.test(attrs['w:pos'] ?? '')) fail('tabs_source_unsupported')
          values.push({ pos: Number(attrs['w:pos']), val: attrs['w:val'] ?? 'left', ...(attrs['w:leader'] !== undefined ? { leader: attrs['w:leader'] } : {}) })
        }
        normalizeDocxTabStops(values)
      }
    }
    const raw = xmlParser.parse(block.rawPPr || '<w:pPr/>').find((node: any) => node['w:pPr'])
    check(raw)
    let id = block.styleId ?? [...rawStyles].find(([, node]) => attrsOf(node)['w:type'] === 'paragraph' && ['1','true','on'].includes(attrsOf(node)['w:default']))?.[0]
    const seen = new Set<string>()
    while (id) {
      if (seen.has(id)) fail('tabs_source_unsupported')
      seen.add(id)
      const style = rawStyles.get(id)
      if (!style) fail('tabs_source_unsupported')
      check(findChild(style, 'w:pPr'))
      id = attrsOf(findChild(style, 'w:basedOn') ?? {})['w:val']
    }
    normalizeDocxTabStops((block.format?.tabStops ?? []).map(({ inherited: _inherited, ...stop }) => stop))
    return true
  } catch { return false }
}
const tableRowHeightLimit = (block: Block) => {
  const section = tableColumnWidthSection(block)
  if (!section) return 0
  const settings = sectionSettingsOf(section)
  return settings.pageHeight - settings.marginTop - settings.marginBottom
}
const tableColumnWidthLimit = (block: Block) => {
  const section = tableColumnWidthSection(block)
  if (!section) return 0
  const settings = sectionSettingsOf(section)
  // 多栏需要证明表格归属的实际文本栏；不能把整页正文宽当作单栏上限。
  if (settings.columns !== 1 || settings.colWidths?.length) return 0
  return settings.pageWidth - settings.marginLeft - settings.marginRight
}
/** 不把未知/重复 on-off 元素静默规范化成关；切换只接受可完整解释的来源。 */
function sectionTitlePage(section: typeof trailingSection) {
  const tags = section.sectPrXml.match(/<w:titlePg\b[^>]*(?:\/>|>[\s\S]*?<\/w:titlePg>)/g) ?? []
  const match = tags[0]?.match(/^<w:titlePg\s*(?:w:val="(true|false|on|off|1|0)"\s*)?(?:\/>|>\s*<\/w:titlePg>)$/)
  const supported = tags.length === 0 || tags.length === 1 && !!match
  return { titlePg: supported ? tags.length > 0 && !['false', 'off', '0'].includes(match?.[1] ?? '') : null,
    ...(supported ? {} : { titlePgReadOnlyReason: '首页不同的来源标记无法完整解释，保留原文件设置' }) }
}
const SECTION_PAGE_NUMBER_FORMATS = new Set(['decimal', 'numberInDash', 'lowerLetter', 'upperLetter', 'lowerRoman', 'upperRoman', 'chineseCounting'])
function sectionPageNumber(section: typeof trailingSection) {
  const tags = section.sectPrXml.match(/<(?:[\w.-]+:)?pgNumType\b[^>]*(?:\/>|>[\s\S]*?<\/(?:[\w.-]+:)?pgNumType>)/g) ?? []
  const tag = tags[0] ?? '', fmt = /\bw:fmt="([^"]*)"/.exec(tag)?.[1], start = /\bw:start="([^"]*)"/.exec(tag)?.[1]
  const rest = tag.replace(/^<w:pgNumType\b/, '').replace(/\s+w:(?:fmt|start)="[^"]*"/g, '').replace(/(?:\/>|>\s*<\/w:pgNumType>)$/, '').trim()
  const supported = !tags.length || tags.length === 1 && !rest && (fmt === undefined || SECTION_PAGE_NUMBER_FORMATS.has(fmt))
    && (start === undefined || /^\d+$/.test(start) && Number.isSafeInteger(Number(start)))
    && (tag.match(/\bw:fmt=/g) ?? []).length <= 1 && (tag.match(/\bw:start=/g) ?? []).length <= 1
  return { pageNumberFmt: section.pageNumberFmt ?? null, pageNumberStart: section.pageNumberStart ?? null,
    ...(supported ? {} : { pageNumberReadOnlyReason: '此节页码格式标记无法完整解释，保留原文件设置' }) }
}
type SectionEditValues = Partial<SectionSettings> & { titlePg?: boolean; evenAndOddHeaders?: boolean; pageNumberFmt?: string | null; pageNumberStart?: number | null }
const settingsSourceXml = await sourceZip.file('word/settings.xml')?.async('string') ?? ''
const evenOddTags = settingsSourceXml.match(/<w:evenAndOddHeaders\b[^>]*(?:\/>|>[\s\S]*?<\/w:evenAndOddHeaders>)/g) ?? []
const evenOddMatch = evenOddTags[0]?.match(/^<w:evenAndOddHeaders\s*(?:w:val="(true|false|on|off|1|0)"\s*)?(?:\/>|>\s*<\/w:evenAndOddHeaders>)$/)
const evenOddTagCount = (settingsSourceXml.match(/<(?:[\w.-]+:)?evenAndOddHeaders\b/g) ?? []).length
const evenOddSupported = (!settingsSourceXml || /<w:settings\b[^>]*\bxmlns:w="http:\/\/schemas.openxmlformats.org\/wordprocessingml\/2006\/main"/.test(settingsSourceXml))
  && evenOddTagCount === evenOddTags.length && (evenOddTags.length === 0 || evenOddTags.length === 1 && !!evenOddMatch)
const evenOddValue = evenOddTags.length > 0 && !['false', 'off', '0'].includes(evenOddMatch?.[1] ?? '')
const SECTION_BREAK_TYPES = ['nextPage', 'continuous', 'evenPage', 'oddPage'] as const
type SectionBreakType = typeof SECTION_BREAK_TYPES[number]
/** 尾节某部件变体的当前引用：rId、part XML 与解析信息（未引用 = null/''，锚为空串哈希）。 */
async function trailingHfPart(part: HeaderFooterPart, variant: HfVariant): Promise<{ rId: string | null; path: string | null; xml: string; info: HfPartInfo | null }> {
  const rId = (part === 'header' ? trailingSection.headerRefs : trailingSection.footerRefs)[variant] ?? null
  const path = rId ? relTargets.get(rId) ?? null : null
  if (rId && !path) fail('hf_reference_invalid')
  const xml = path ? await sourceZip.file(path)?.async('string') ?? '' : ''
  return { rId, path, xml, info: rId ? parsed.hfParts?.[rId] ?? null : null }
}
const HF_PART_KEYS = ['header.default', 'header.first', 'header.even', 'footer.default', 'footer.first', 'footer.even'] as const
const hfPartAnchors = await Promise.all(HF_PART_KEYS.map(async key => {
  const [part, variant] = key.split('.') as [HeaderFooterPart, HfVariant]
  const found = await trailingHfPart(part, variant)
  const text = found.info?.text ?? ''
  return [key, {
    rId: found.rId,
    expectedPartSha256: hash(found.xml),
    text,
    hasPageNumber: found.info?.hasPageNumber ?? false,
    editable: true,
  }] as const
}))
// 每节的 own 引用与沿前节链解析的有效部件身份；不接受客户端路径/XML。
const inspectHfRelationships = createHfRelationshipInspector(sourceZip)
const sectionHfModels = await Promise.all(allSections.map(async (section, index) => {
  const parts = await Promise.all(HF_PART_KEYS.map(async key => {
    const [part, variant] = key.split('.') as [HeaderFooterPart, HfVariant]
    const refsOf = (item: typeof section) => (part === 'header' ? item.headerRefs : item.footerRefs)[variant] ?? null
    const ownRId = refsOf(section)
    let owner = index
    while (owner > 0 && !refsOf(allSections[owner]!)) owner--
    const ownerSection = allSections[owner]!, rId = refsOf(ownerSection)
    const path = rId ? relTargets.get(rId) ?? null : null
    const xml = path ? await sourceZip.file(path)?.async('string') ?? '' : ''
    const ownPath = ownRId ? relTargets.get(ownRId) ?? null : null
    const ownXml = ownPath ? await sourceZip.file(ownPath)?.async('string') ?? '' : ''
    const info = rId ? parsed.hfParts?.[rId] : null
    const effectiveGraph = await inspectHfRelationships(path), ownGraph = await inspectHfRelationships(ownPath)
    let reason: string | undefined
    for (const current of allSections.slice(0, index + 1)) {
      const tags = current.sectPrXml.match(new RegExp(`<(?:[\\w.-]+:)?${part}Reference\\b[^>]*>`, 'g')) ?? []
      if (tags.some(tag => !new RegExp(`^<w:${part}Reference\\s+(?:(?:w:type="(?:default|first|even)"|r:id="[^"]+")\\s*){2}/>$`).test(tag))
        || HF_VARIANTS.some(type => tags.filter(tag => tag.includes(`w:type="${type}"`)).length > 1)) reason = '页眉页脚引用包含未知或重复标记，保留原文件设置'
    }
    for (const [ref, target, content] of [[rId, path, xml], [ownRId, ownPath, ownXml]] as const) {
      if (ref && (!target || !content || !parsed.hfParts?.[ref])) reason = '页眉页脚关系或部件身份无法核验'

    }
    reason ??= effectiveGraph.reason ?? ownGraph.reason
    return [key, { relationshipsSha256: effectiveGraph.sha256, ownRelationshipsSha256: ownGraph.sha256, ownRId, ownPath, ownPartSha256: hash(ownXml), ownerSectionId: sectionIdOf(ownerSection),
      rId, path, expectedPartSha256: hash(xml), linked: index ? !ownRId : null,
      text: info?.text ?? '', hasPageNumber: info?.hasPageNumber ?? false, editable: !reason,
      ...(reason ? { readOnlyReason: reason } : {}) }] as const
  }))
  return { parts: Object.fromEntries(parts) }
}))
const indexed = new Map(blocks.map(block => [blockId(block), block]))
const cellMarginOverrides = new Map(await Promise.all((request.kind === 'inspect' ? blocks.filter(block => block.type === 'table') : []).map(async block => [blockId(block), parsed.protection?.enforced ? { tableCellMarginOverridesEditable: false, tableCellMarginOverridesReadOnlyReason: 'docx_table_cell_margin_overrides_protected' } : await tableCellMarginOverridesAvailability(block, parsed)] as const)))
const nestedTables = new Map(blocks.filter(block => block.type === 'table').map(block => [blockId(block), inspectNestedTables(block, sourceSha256, blockId(block), editableCell, !!parsed.protection?.enforced)]))
// saveDocx 的注释部件协议固定为标准路径；未知关系布局保持只读。
const noteRelationships = [...(await parseRels(sourceZip, 'word/_rels/document.xml.rels')).values()].filter(rel => /\/(?:footnotes|endnotes)$/.test(rel.type))
// 全局引用清点包含表格/隐藏块；未进入安全段落模型的引用不允许被漏删。
const documentNotesXml = await sourceZip.file('word/document.xml')!.async('string')
const documentNoteReferences = [...documentNotesXml.matchAll(/<w:(footnote|endnote)Reference\b[^>]*>/g)].map(match => `${match[1]}:${/\bw:id=["']([^"']+)["']/.exec(match[0])?.[1] ?? '?'}`).sort()
const modeledNoteReferences = blocks.flatMap(block => (block.runs ?? []).flatMap(run => run.noteRef ? [`${run.noteRef.kind}:${run.noteRef.id}`] : [])).sort()
const notesAvailable = JSON.stringify(documentNoteReferences) === JSON.stringify(modeledNoteReferences) && ['footnote', 'endnote'].every(kind => {
  const relations = noteRelationships.filter(rel => rel.type.endsWith(`/${kind}s`))
  return relations.length <= 1 && relations.every(rel => !rel.external && resolvePartPath('word', rel.target) === `word/${kind}s.xml` && !!sourceZip.file(`word/${kind}s.xml`))
    && (!sourceZip.file(`word/${kind}s.xml`) || relations.length === 1)
})
let notesPlanner: ReturnType<typeof createDocxNotesPlanner> | undefined
try { if (notesAvailable) notesPlanner = createDocxNotesPlanner({ sourceSha256,
  footnotesXml: await sourceZip.file('word/footnotes.xml')?.async('string') ?? null,
  endnotesXml: await sourceZip.file('word/endnotes.xml')?.async('string') ?? null,
  blocks: blocks.map(block => ({ blockId: blockId(block), expectedObjectSha256: hash(block.originalXml ?? ''), editable: editableNoteReferenceBlock(block), runs: block.runs ?? [] })),
}) } catch { /* 未支持的注释部件只关闭注释编辑，普通正文能力不受影响。 */ }
const model = () => ({ sourceSha256, modelSource: 'genoffice-docx-engine:f8c17004fb730df11f0f743164ffd8b4281bb38c', desktopVerified: false,
  ...(commentSource ? { comments: commentSource } : {}),
  ...(commentCreation ? { commentCreation } : {}),
  ...(commentReplies ? { commentReplies } : {}),
  ...(commentThreads ? { commentThreads } : {}),
  ...(bookmarks ? { bookmarks } : {}),
  ...(crossReferences ? { crossReferences } : {}),
  ...(notesPlanner ? { notes: notesPlanner.model } : {}),
  capabilities: { paragraphs: true, basicStyles: true, simpleTableText: true, simpleTableStructure: true, replaceImage: false, headerFooter: true, pageColor: true, watermark: true },
  pageColor: pageColorModel,
  watermark: watermarkModel,
  // 全部节（文档顺序，尾节在最后）：编辑器按光标所在块定位当前节。
  sections: allSections.map((section, index) => ({ headersFooters: sectionHfModels[index], sectionId: sectionIdOf(section), expectedSectionSha256: hash(section.sectPrXml), settings: sectionSettingsOf(section),
    firstBlockIndex: section.firstBlockIndex, lastBlockIndex: section.lastBlockIndex, startType: section.startType, ...sectionTitlePage(section), ...sectionPageNumber(section) })),
  headersFooters: {
    titlePg: trailingSection.titlePg,
    titlePgReadOnlyReason: sectionTitlePage(trailingSection).titlePgReadOnlyReason ?? null,
    evenAndOddHeaders: evenOddSupported ? evenOddValue : parsed.evenAndOddHeaders ?? false,
    evenAndOddHeadersReadOnlyReason: evenOddSupported ? null : '奇偶页不同的来源标记无法完整解释，保留原文件设置',
    pageNumberFmt: trailingSection.pageNumberFmt ?? null,
    pageNumberStart: trailingSection.pageNumberStart ?? null,
    pageNumberReadOnlyReason: sectionPageNumber(trailingSection).pageNumberReadOnlyReason ?? null,
    parts: Object.fromEntries(hfPartAnchors),
  },
  blocks: blocks.map(block => ({ blockId: blockId(block), expectedObjectSha256: hash(block.originalXml ?? ''), sourceSectionId: tableColumnWidthSectionId(block),
    ...revisionAvailability(block),
    type: block.type, text: block.runs?.map(run => run.text).join('') ?? block.previewText ?? '', links: linksOf(block),
    ...(block.list ? { list: block.list } : {}),
    paragraphStyleEditable: paragraphStyleEditable(block),
    paragraphShadingEditable: paragraphDecorationEditable(block, 'shading'),
    paragraphBordersEditable: paragraphDecorationEditable(block, 'borders'),
    paragraphLayoutEditable: editableParagraph(block) || (!!notesPlanner && editableNoteReferenceBlock(block)),
    rulerIndentEditable: rulerIndentEditable(block),
    rulerIndentReadOnlyReason: rulerIndentEditable(block) ? null : '标尺左／首行／悬挂缩进仅支持单栏非镜像、无字符缩进的可信从左到右正文或标题',
    tabStopsEditable: tabStopsEditable(block),
    tabStopsReadOnlyReason: tabStopsEditable(block) ? null : '制表位仅支持单栏非镜像、无字符缩进的可信LTR单段，来源不得含未知制表位属性或相对定位',
    editable: editableParagraph(block), readOnlyReason: editableParagraph(block) ? null : 'docx_object_unsupported',
    deletable: editableParagraph(block) || coverMarkerParagraph(block),
    ...(block.type === 'table' ? { nestedTables: nestedTables.get(blockId(block))!.anchors, ...tableStructureAvailability(block), ...(parsed.protection?.enforced ? { tableAltTextEditable: false, tableAltTextReadOnlyReason: 'docx_table_alt_text_protected' } : tableAltTextAvailability(block)), ...(parsed.protection?.enforced ? { tableCellWrapEditable: false, tableCellWrapReadOnlyReason: 'docx_table_cell_wrap_protected' } : tableCellWrapAvailability(block, parsed)), ...(parsed.protection?.enforced ? { tableAlignmentEditable: false, tableAlignmentReadOnlyReason: 'docx_table_alignment_protected' } : tableAlignmentAvailability(block)), ...(parsed.protection?.enforced ? { rowBreakEditable: false, rowBreakReadOnlyReason: 'docx_table_row_breaks_protected' } : tableRowBreakAvailability(block)), ...cellMarginOverrides.get(blockId(block)), ...(parsed.protection?.enforced ? { tableCellMarginsEditable: false, tableCellMarginsReadOnlyReason: 'docx_table_cell_margins_protected' } : tableCellMarginsAvailability(block)), ...(parsed.protection?.enforced ? { cellAlignmentEditable: false, cellAlignmentReadOnlyReason: 'docx_table_cell_alignment_protected' } : tableCellAlignmentAvailability(block)), ...(parsed.protection?.enforced ? { cellTextDirectionEditable: false, cellTextDirectionReadOnlyReason: 'docx_table_cell_text_direction_protected' } : tableCellTextDirectionAvailability(block)), autoFitSectionId: tableColumnWidthSectionId(block), ...(parsed.protection?.enforced ? { autoFitEditable: false, autoFitReadOnlyReason: 'docx_table_autofit_protected' } : tableAutoFitAvailability(block, tableColumnWidthLimit(block))), columnWidthSectionId: tableColumnWidthSectionId(block), rowHeightSectionId: tableColumnWidthSectionId(block), ...(parsed.protection?.enforced ? { rowHeightEditable: false, rowHeightReadOnlyReason: 'docx_table_row_height_protected' } : tableRowHeightAvailability(block, tableRowHeightLimit(block))), ...(parsed.protection?.enforced ? { columnWidthEditable: false, columnWidthReadOnlyReason: 'docx_table_column_width_protected' } : tableColumnWidthAvailability(block, tableColumnWidthLimit(block))), ...(parsed.protection?.enforced ? { cellShapeEditable: false, cellShapeReadOnlyReason: 'docx_table_cell_shape_protected' } : tableCellShapeAvailability(block)), ...docxCellBordersCapability(block.originalXml!), rowCount: block.table?.rows.length ?? 0, columnCount: block.table?.rows[0]?.length ?? 0, cells: cellXmls(block).map((row, r) => row.map((xml, c) => ({
      cellId: cellId(block, r, c), expectedObjectSha256: hash(xml), row: r, column: c,
      text: block.table?.rows[r]?.[c]?.paras.join('\n') ?? '', editable: editableTable(block) && editableCell(xml),
      ...docxCellShadingCapability(block.originalXml!, xml),
      readOnlyReason: editableTable(block) && editableCell(xml) ? null : 'docx_cell_unsupported',
    }))) } : {}),
  })) })

if (request.kind === 'inspect') {
  process.stdout.write(JSON.stringify(model()))
} else {
  if (typeof request.output !== 'string' || !Array.isArray(request.operations) || request.operations.length > 500) fail('operation_invalid')
  // 水印改写页眉部件：与页眉页脚、节设置同批时页眉回读语义不再唯一，要求分开保存（先于各操作的锚点校验）。
  if (request.operations.some(raw => object(raw).kind === 'setWatermark') && request.operations.some(raw => ['setHeaderFooter', 'setHeaderFooterLink', 'setSectionLayout', 'insertSectionBreak'].includes(object(raw).kind as string))) fail('watermark_header_batch_conflict')
  const sourcePath = await realpath(request.input as string)
  const outputPath = await realpath(request.output as string).catch(() => resolve(request.output as string))
  const sourceIdentity = await stat(sourcePath)
  const outputIdentity = await stat(outputPath).catch(() => undefined)
  if (sourcePath === outputPath || (outputIdentity && sourceIdentity.ino === outputIdentity.ino && sourceIdentity.dev === outputIdentity.dev)) fail('output_overwrites_source')
  const references = request.operations.filter(raw => object(raw).kind === 'insertCrossReference')
  if (references.length) {
    if (references.length !== request.operations.length || references.length !== 1) fail('cross_reference_batch_conflict')
    const output = await patchDocxCrossReference(bytes, references[0] as DocxCrossReferenceOperation)
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const captions = request.operations.filter(raw => object(raw).kind === 'insertCaption')
  if (captions.length) {
    if (captions.length !== request.operations.length || captions.length !== 1) fail('caption_batch_conflict')
    if (revisionProtected) fail('caption_source_unsupported')
    const output = await patchDocxCaption(bytes, captions[0], parsed)
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const bookmarkOperations = request.operations.filter(raw => ['createBookmark', 'deleteBookmark'].includes(String(object(raw).kind)))
  if (bookmarkOperations.length) {
    if (bookmarkOperations.length !== request.operations.length) fail('bookmark_batch_conflict')
    const output = await patchDocxBookmarks(bytes, bookmarkOperations as DocxBookmarkOperation[])
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const tocOperations = request.operations.filter(raw => isDocxTocOperation(object(raw)))
  if (tocOperations.length) {
    if (tocOperations.length !== request.operations.length || tocOperations.length !== 1) fail('toc_batch_conflict')
    if (revisionProtected) fail('toc_source_unsupported')
    const output = await patchDocxToc(bytes, tocOperations[0], parsed)
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const threadOperations = request.operations.filter(raw => ['deleteComment', 'resolveComment'].includes(String(object(raw).kind)))
  if (threadOperations.length) {
    if (threadOperations.length !== request.operations.length) fail('comment_thread_batch_conflict')
    const output = await patchDocxCommentThreads(bytes, threadOperations as CommentThreadOperation[])
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const replies = request.operations.filter(raw => object(raw).kind === 'replyComment')
  if (replies.length) {
    if (replies.length !== request.operations.length) fail('comment_reply_batch_conflict')
    const output = await patchDocxCommentReplies(bytes, replies as CommentReplyOperation[])
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const creations = request.operations.filter(raw => object(raw).kind === 'createComment')
  if (creations.length) {
    if (creations.length !== request.operations.length) fail('comment_creation_batch_conflict')
    const output = await patchDocxCommentCreation(bytes, creations as CommentCreationOperation[])
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({sourceSha256, sha256: hash(output), size: output.length}))
    process.exit(0)
  }
  const commentOperations = request.operations.filter(raw => object(raw).kind === 'editCommentText')
  if (commentOperations.length) {
    if (commentOperations.length !== request.operations.length || commentOperations.length > 200) fail('comment_batch_conflict')
    const operations = commentOperations.map(raw => {
      const op = object(raw)
      keys(op, ['kind', 'sourceId', 'targetId', 'expectedCommentsSha256', 'expectedObjectSha256', 'text'])
      if (op.kind !== 'editCommentText' || typeof op.sourceId !== 'string' || typeof op.targetId !== 'string'
        || typeof op.expectedCommentsSha256 !== 'string' || typeof op.expectedObjectSha256 !== 'string') fail('comment_operation_invalid')
      return op as unknown as import('./docx-comments.ts').CommentTextOperation
    })
    const output = await patchDocxCommentSource(bytes, operations)
    await writeFile(request.output as string, output, {flag: 'wx'})
    process.stdout.write(JSON.stringify({ sourceSha256, sha256: hash(output), size: output.length }))
    process.exit(0)
  }
  // 页眉/页脚部件编辑：节锚定、不落在正文 block 上，先于 block 操作单独校验收集；
  // 同一 (part, variant) 一批只允许一次编辑。
  const hfLinks = new Map<string, { section: typeof trailingSection; part: HeaderFooterPart; variant: HfVariant; linked: boolean }>()
  for (const raw of request.operations) {
    const op = object(raw)
    if (op.kind !== 'setHeaderFooterLink') continue
    keys(op, ['kind', 'sectionId', 'expectedSectionSha256', 'part', 'variant', 'linked', 'expectedOwnRId', 'expectedOwnPartSha256', 'expectedOwnerSectionId', 'expectedRId', 'expectedPartSha256', 'expectedRelationshipsSha256', 'expectedOwnRelationshipsSha256'])
    const index = allSections.findIndex(section => sectionIdOf(section) === op.sectionId), section = allSections[index]
    if (!section || op.expectedSectionSha256 !== hash(section.sectPrXml)) fail('section_anchor_invalid')
    if (index === 0) fail('hf_link_first_section')
    if ((op.part !== 'header' && op.part !== 'footer') || !HF_VARIANTS.includes(op.variant as HfVariant) || typeof op.linked !== 'boolean') fail('hf_part_invalid')
    const anchor = sectionHfModels[index]!.parts[`${op.part}.${op.variant}` as typeof HF_PART_KEYS[number]]!
    if (op.expectedRelationshipsSha256 !== anchor.relationshipsSha256 || op.expectedOwnRelationshipsSha256 !== anchor.ownRelationshipsSha256
      || op.expectedOwnRId !== anchor.ownRId || op.expectedOwnPartSha256 !== anchor.ownPartSha256
      || op.expectedOwnerSectionId !== anchor.ownerSectionId || op.expectedRId !== anchor.rId || op.expectedPartSha256 !== anchor.expectedPartSha256) fail('hf_anchor_invalid')
    if (!anchor.editable) fail('hf_link_unsupported')
    const key = `${index}:${op.part}:${op.variant}`
    if (hfLinks.has(key)) fail('hf_batch_conflict')
    hfLinks.set(key, { section, part: op.part as HeaderFooterPart, variant: op.variant as HfVariant, linked: op.linked as boolean })
  }
  if (hfLinks.size && request.operations.some(raw => object(raw).kind === 'insertSectionBreak')) fail('hf_link_pending_save')
  const plannedHfSources = new Map<string, typeof sectionHfModels[number]['parts'][typeof HF_PART_KEYS[number]]>()
  for (const slot of HF_PART_KEYS) {
    let prior: typeof sectionHfModels[number]['parts'][typeof slot] | undefined
    for (const [index] of allSections.entries()) {
      const source = sectionHfModels[index]!.parts[slot]!, [part, variant] = slot.split('.')
      const link = hfLinks.get(`${index}:${part}:${variant}`)
      if (link?.linked === true || !source.ownRId) prior ??= source
      else prior = source
      plannedHfSources.set(`${index}:${part}:${variant}`, prior!)
    }
  }
  const hfEdits = new Map<string, HeaderFooterEdit>()
  for (const raw of request.operations) {
    const op = object(raw)
    if (op.kind !== 'setHeaderFooter') continue
    keys(op, ['kind', 'sectionId', 'expectedSectionSha256', 'part', 'variant', 'afterLink', 'expectedPartSha256', 'text', 'pageNumber', 'align', 'titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'])
    const target = allSections.find(section => sectionIdOf(section) === op.sectionId)
    if (!target || op.expectedSectionSha256 !== hash(target.sectPrXml)) fail('section_anchor_invalid')
    if (target !== trailingSection && ['titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'].some(key => op[key] !== undefined)) fail('hf_settings_use_section_layout')
    if (op.part !== 'header' && op.part !== 'footer') fail('hf_part_invalid')
    if (!HF_VARIANTS.includes(op.variant as HfVariant)) fail('hf_part_invalid')
    if (typeof op.pageNumber !== 'boolean') fail('hf_part_invalid')
    if (op.align !== undefined && !['left', 'center', 'right'].includes(op.align as string)) fail('hf_part_invalid')
    for (const key of ['titlePg', 'evenAndOddHeaders'] as const) {
      if (op[key] !== undefined && typeof op[key] !== 'boolean') fail('hf_part_invalid')
    }
    if (op.titlePg !== undefined && sectionTitlePage(trailingSection).titlePg === null) fail('section_title_page_unsupported')
    if (op.evenAndOddHeaders !== undefined && !evenOddSupported) fail('document_even_odd_unsupported')
    if ((op.pageNumberFmt !== undefined || op.pageNumberStart !== undefined) && sectionPageNumber(trailingSection).pageNumberReadOnlyReason) fail('section_page_number_unsupported')
    const fmt = op.pageNumberFmt
    if (fmt !== undefined && fmt !== null && (typeof fmt !== 'string' || !PAGE_NUMBER_FORMATS.has(fmt))) fail('page_number_format_invalid')
    const start = op.pageNumberStart
    if (start !== undefined && start !== null && (typeof start !== 'number' || !Number.isSafeInteger(start) || start < 0)) fail('page_number_format_invalid')
    const targetIndex = allSections.indexOf(target)
    const targetAnchor = sectionHfModels[targetIndex]!.parts[`${op.part}.${op.variant}` as typeof HF_PART_KEYS[number]]!
    if (!targetAnchor.editable) fail('hf_part_unsupported')
    const link = hfLinks.get(`${targetIndex}:${op.part}:${op.variant}`)
    if (op.afterLink !== undefined && (op.afterLink !== true || link?.linked !== false || !targetAnchor.linked)) fail('hf_after_link_invalid')
    if (op.afterLink === undefined && link) fail('hf_after_link_invalid')
    if (!op.afterLink && !targetAnchor.ownRId && targetAnchor.rId) fail('hf_edit_requires_owner')
    const base = op.afterLink ? plannedHfSources.get(`${targetIndex}:${op.part}:${op.variant}`)! : targetAnchor
    if (!base.editable) fail('hf_part_unsupported')
    const found = { info: base.rId ? parsed.hfParts?.[base.rId] ?? null : null, xml: base.path ? await sourceZip.file(base.path)!.async('string') : '' }
    if (hash(found.xml) !== op.expectedPartSha256) fail('hf_anchor_invalid')
    const value = text(op.text)
    const key = `${targetIndex}:${op.part}:${op.variant}`
    if (hfEdits.has(key)) fail('hf_batch_conflict')
    hfEdits.set(key, {
      sourceXml: found.xml, ...(op.afterLink ? { afterLink: true } : {}), ...(op.align ? { align: op.align as 'left' | 'center' | 'right' } : {}), section: target, part: op.part as HeaderFooterPart, variant: op.variant as HfVariant,
      value: hfValueFromText(found.info, value, op.pageNumber as boolean, op.align as 'left' | 'center' | 'right' | undefined),
      pageNumber: op.pageNumber as boolean, lines: value.split('\n'),
      ...(op.titlePg !== undefined ? { titlePg: op.titlePg as boolean } : {}),
      ...(op.evenAndOddHeaders !== undefined ? { evenAndOddHeaders: op.evenAndOddHeaders as boolean } : {}),
      ...(fmt !== undefined ? { pageNumberFmt: fmt as string | null } : {}),
      ...(start !== undefined ? { pageNumberStart: start as number | null } : {}),
    })
  }
  // 单段多目标共用一个原快照，只调用 core 一次；先校验整批，再触及输出。
  const revisionGroups = new Map<string, { block: Block; operations: TextRevisionOperation[]; xml?: string }>()
  for (const raw of request.operations) {
    const op = object(raw)
    if (op.kind !== 'resolveTextRevision') continue
    keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'revisionId', 'action'])
    const block = indexed.get(op.blockId as string)
    if (!block) fail('revision_anchor_invalid')
    const reason = revisionScopeReason(block)
    if (reason) throw new Error(reason)
    const group = revisionGroups.get(op.blockId as string) ?? { block, operations: [] as TextRevisionOperation[] }
    const { kind, ...decision } = op
    group.operations.push(decision as unknown as TextRevisionOperation)
    revisionGroups.set(op.blockId as string, group)
  }
  for (const [identity, group] of revisionGroups) {
    // 包含提前剥离的 note / patchParagraphRuns；节操作会改写段的节属性，同批保守拒绝。
    if (request.operations.some(raw => {
      const other = object(raw)
      return other.kind !== 'resolveTextRevision' && (other.blockId === identity || ['setSectionLayout', 'insertSectionBreak'].includes(other.kind as string))
    })) fail('revision_batch_conflict')
    group.xml = resolveTextRevisions(group.block, identity, group.operations, revisionProtected).xml
  }
  const noteKinds = ['insertNote', 'updateNote', 'deleteNote']
  const noteOperations = request.operations.filter(raw => noteKinds.includes(object(raw).kind as string))
  if (noteOperations.length && !notesPlanner) fail('notes_unsupported')
  const finalParagraphOperations = request.operations.filter(raw => object(raw).kind === 'patchParagraphRuns').map(object)
  const finalParagraphs = new Map<string, Run[]>()
  for (const op of finalParagraphOperations) {
    keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'runs'])
    const block = indexed.get(op.blockId as string)
    if (!block || op.expectedObjectSha256 !== hash(block.originalXml ?? '') || !(notesPlanner ? editableNoteReferenceBlock(block) : !parsed.protection?.enforced && editableParagraph(block)) || finalParagraphs.has(op.blockId as string)) fail('note_paragraph_anchor_invalid')
    finalParagraphs.set(op.blockId as string, [])
  }
  const notesPlan = notesPlanner?.plan(noteOperations, new Set(finalParagraphs.keys()))
  for (const op of finalParagraphOperations) {
    const block = indexed.get(op.blockId as string)!
    finalParagraphs.set(op.blockId as string, compileNoteParagraphRuns(block.runs!, op.runs, noteOperations as Record<string, any>[], notesPlan?.allocated ?? new Map(), op.blockId as string,
      (run, spec) => { const value = object(spec); if (!Object.keys(value).length) fail('style_invalid'); return applyRunFormatting(run, style(value), value) }, block.emptyRun))
  }
  const pageColor = validateDocxPageColorOperations(request.operations.map(object).filter(op => op.kind === 'setPageColor'), pageColorModel)
  const watermark = validateDocxWatermarkOperations(request.operations.map(object).filter(op => op.kind === 'setWatermark'), watermarkModel)
  const blockOperations = request.operations.filter(raw => !['setHeaderFooter', 'setHeaderFooterLink', 'setPageColor', 'setWatermark', ...noteKinds, 'patchParagraphRuns', 'resolveTextRevision'].includes(object(raw).kind as string))
  // 先对同一来源快照整批校验；应用时按请求顺序组合，expectedObjectSha256 不随前序修改改变。
  const operations = await Promise.all(blockOperations.map(async raw => {
    const op = object(raw)
    if (op.kind === 'setSectionLayout') {
      keys(op, ['kind', 'sectionId', 'expectedSectionSha256', 'values'])
      const target = allSections.find(section => sectionIdOf(section) === op.sectionId)
      if (!target || op.expectedSectionSha256 !== hash(target.sectPrXml)) fail('section_anchor_invalid')
      const values = object(op.values)
      keys(values, ['orientation', 'pageWidth', 'pageHeight', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft', 'columns', 'headerDist', 'footerDist', 'titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart', 'pageBorder', 'pageBorderProps'])
      try { validatePageBorderValues(values) } catch { fail('page_border_invalid') }
      // 页面边框按现有节序回读核对；同批插入分节符会改变节序，须分开保存。
      if ('pageBorder' in values && request.operations.some(raw => object(raw).kind === 'insertSectionBreak')) fail('page_border_section_break_conflict')
      if (values.pageNumberFmt !== undefined || values.pageNumberStart !== undefined) {
        if (sectionPageNumber(target).pageNumberReadOnlyReason) fail('section_page_number_unsupported')
        if (values.pageNumberFmt !== undefined && values.pageNumberFmt !== null && !SECTION_PAGE_NUMBER_FORMATS.has(values.pageNumberFmt as string)) fail('section_layout_invalid')
        if (values.pageNumberStart !== undefined && values.pageNumberStart !== null && (typeof values.pageNumberStart !== 'number' || !Number.isSafeInteger(values.pageNumberStart) || values.pageNumberStart < 0)) fail('section_layout_invalid')
      }
      if (values.evenAndOddHeaders !== undefined) {
        if (target !== trailingSection) fail('document_header_footer_anchor_invalid')
        if (typeof values.evenAndOddHeaders !== 'boolean') fail('section_layout_invalid')
        if (!evenOddSupported) fail('document_even_odd_unsupported')
      }
      if (values.titlePg !== undefined) {
        if (typeof values.titlePg !== 'boolean') fail('section_layout_invalid')
        if (sectionTitlePage(target).titlePg === null) fail('section_title_page_unsupported')
      }
      if (!Object.keys(values).length) fail('section_layout_invalid')
      if (values.orientation !== undefined && !['portrait', 'landscape'].includes(values.orientation as string)) fail('section_layout_invalid')
      for (const key of ['pageWidth', 'pageHeight'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 1440 || values[key] > 31680)) fail('section_layout_invalid')
      for (const key of ['marginTop', 'marginRight', 'marginBottom', 'marginLeft'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 0 || values[key] > 14400)) fail('section_layout_invalid')
      if (values.columns !== undefined && (typeof values.columns !== 'number' || !Number.isInteger(values.columns) || values.columns < 1 || values.columns > 3)) fail('section_layout_invalid')
      for (const key of ['headerDist', 'footerDist'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 0 || values[key] > 31680)) fail('section_layout_invalid')
      const current = sectionSettingsOf(target)
      if (Number(values.marginLeft ?? current.marginLeft) + Number(values.marginRight ?? current.marginRight) >= Number(values.pageWidth ?? current.pageWidth)
        || Number(values.marginTop ?? current.marginTop) + Number(values.marginBottom ?? current.marginBottom) >= Number(values.pageHeight ?? current.pageHeight)) fail('section_layout_invalid')
      return { op, sectionValues: values as SectionEditValues, section: target }
    }
    const block = indexed.get(op.blockId as string)
    if (!block || block.docxIndex === null) fail('anchor_invalid')
    if (op.kind === 'replaceImage') fail('image_unsupported')
    if (TABLE_STRUCTURE_KINDS.includes(op.kind as TableStructureKind)) {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'index'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (typeof op.index !== 'number' || !Number.isInteger(op.index)) fail('table_structure_index_invalid')
      return { op, block, tableStructure: editTableStructure(block, op.kind as TableStructureKind, op.index) }
    }
    if (op.kind === 'insertSectionBreak') {
      // 固定源 App.tsx insertSectionBreak：锚块后插入携带当前节 sectPr 副本的分节段，
      // 原节终止 sectPr 的 w:type 改为所选起始方式（新节如何开始）。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'type'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (!SECTION_BREAK_TYPES.includes(op.type as SectionBreakType)) fail('section_break_invalid')
      if (block.hidden || /<w:sectPr\b/.test(block.originalXml ?? '')) fail('section_break_anchor_invalid')
      const target = allSections.find(section => section.firstBlockIndex <= block.docxIndex! && block.docxIndex! <= section.lastBlockIndex)
      if (!target) fail('section_break_anchor_invalid')
      return { op, block, sectionBreak: { section: target, type: op.type as SectionBreakType } }
    }
    if (op.kind === 'setTableAltText') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'title', 'description'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_alt_text_protected')
      return { op, block, tableAltText: editTableAltText(block, { title: op.title as string, description: op.description as string }) }
    }
    if (op.kind === 'setTableCellWrap') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_wrap_protected')
      return { op, block, tableCellWrap: editTableCellWrap(block, op.steps as Parameters<typeof editTableCellWrap>[1], parsed) }
    }
    if (op.kind === 'setTableAlignment') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'alignment'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_alignment_protected')
      return { op, block, tableAlignment: editTableAlignment(block, op.alignment as Parameters<typeof editTableAlignment>[1]) }
    }
    if (op.kind === 'setTableRowBreaks') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_row_breaks_protected')
      return { op, block, tableRowBreaks: editTableRowBreaks(block, op.steps as Parameters<typeof editTableRowBreaks>[1]) }
    }
    if (op.kind === 'setTableCellMarginOverrides') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_margin_overrides_protected')
      return { op, block, tableCellMarginOverrides: await editTableCellMarginOverrides(block, op.steps as Parameters<typeof editTableCellMarginOverrides>[1], parsed) }
    }
    if (op.kind === 'setTableCellMargins') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'margins'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_margins_protected')
      return { op, block, tableCellMargins: editTableCellMargins(block, op.margins as Parameters<typeof editTableCellMargins>[1]) }
    }
    if (op.kind === 'setTableCellAlignment') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_alignment_protected')
      return { op, block, tableCellAlignment: editTableCellAlignment(block, op.steps as Parameters<typeof editTableCellAlignment>[1]) }
    }
    if (op.kind === 'setTableCellTextDirection') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_text_direction_protected')
      return { op, block, tableCellTextDirection: editTableCellTextDirection(block, op.steps as Parameters<typeof editTableCellTextDirection>[1]) }
    }
    if (op.kind === 'setTableAutoFit') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_autofit_protected')
      return { op, block, tableAutoFit: editTableAutoFit(block, tableColumnWidthLimit(block), op.steps as Parameters<typeof editTableAutoFit>[2]) }
    }
    if (op.kind === 'setTableRowHeights') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_row_height_protected')
      return { op, block, tableRowHeights: editTableRowHeights(block, tableRowHeightLimit(block), op.steps as Parameters<typeof editTableRowHeights>[2]) }
    }
    if (op.kind === 'resizeTableColumns') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_column_width_protected')
      return { op, block, tableColumnWidths: editTableColumnWidths(block, tableColumnWidthLimit(block), op.steps as Parameters<typeof editTableColumnWidths>[2]) }
    }
    if (op.kind === 'reshapeTableCells') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      if (parsed.protection?.enforced) fail('table_cell_shape_protected')
      return { op, block, tableCellShape: editTableCellShape(block, op.steps as Parameters<typeof editTableCellShape>[1]) }
    }
    if (op.kind === 'restructureTable') {
      // 同一来源表格的多步行列增删（每步坐标基于上一步结果）+ 最终坐标的纯文字修改。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps', 'texts'])
      if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      const steps = op.steps, texts = op.texts ?? []
      if (!Array.isArray(steps) || !steps.length || steps.length > MAX_TABLE_STEPS || !Array.isArray(texts)) fail('table_structure_steps_invalid')
      for (const step of steps) {
        if (!step || typeof step !== 'object' || Object.keys(step).some(key => !['kind', 'index'].includes(key))
          || !TABLE_STRUCTURE_KINDS.includes(step.kind) || !Number.isInteger(step.index)) fail('table_structure_steps_invalid')
      }
      for (const text of texts) {
        if (!text || typeof text !== 'object' || Object.keys(text).some(key => !['row', 'column', 'text'].includes(key))) fail('table_structure_steps_invalid')
      }
      return { op, block, tableStructure: editTableStructureSteps(block, steps, texts) }
    }
    if (op.kind === 'setTableRepeatHeaders') {
      keys(op,['kind','blockId','expectedObjectSha256','expectedRowCount','prefixRowCount','headers'])
      if(block.type!=='table'||hash(block.originalXml??'')!==op.expectedObjectSha256)fail('anchor_invalid')
      patchTableRepeatHeaders(block.originalXml!,op.expectedRowCount,op.headers,op.prefixRowCount)
      return {op,block}
    }
    if (op.kind === 'setTableCellBorders') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'steps'])
      if (block.type !== 'table' || hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
      const cells = cellXmls(block).map((row, r) => row.map((_, c) => ({ cellId: cellId(block, r, c) })))
      patchDocxTableCellBorders(block.originalXml!, op.steps, cells)
      return { op, block }
    }
    if (op.kind === 'replaceNestedCellText') {
      if (block.type !== 'table') fail('nested_anchor_invalid')
      return { op, block, nested: validateNestedCellOperation(op, nestedTables.get(blockId(block))!.targets) }
    }
    if (op.kind === 'replaceCellText' || op.kind === 'setCellShading') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'cellId', op.kind === 'setCellShading' ? 'fill' : 'text'])
      const rows = cellXmls(block)
      let found: { row: number; column: number; xml: string } | undefined
      rows.forEach((row, r) => row.forEach((xml, c) => { if (cellId(block, r, c) === op.cellId) found = { row: r, column: c, xml } }))
      if (!found || hash(found.xml) !== op.expectedObjectSha256) fail('anchor_invalid')
      if (op.kind === 'setCellShading') {
        if (!docxCellShadingCapability(block.originalXml!, found.xml).shadingEditable) fail('cell_shading_unsupported')
        patchDocxCellShading(found.xml, op.fill)
        return { op, block, cell: found }
      }
      if (!editableTable(block) || !editableCell(found.xml)) fail('cell_unsupported')
      return { op, block, cell: found, value: text(op.text) }
    }
    if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
    if (op.kind === 'setParagraphStyle') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'styleId', 'ribbon'])
      if ('ribbon' in op && op.ribbon !== true) fail('paragraph_style_ribbon_invalid')
      if (op.ribbon === true && (!editableParagraph(block) || /<w:(?:br|cr|tab)\b/.test(block.originalXml!))) fail('paragraph_style_ribbon_unsupported')
      if (!paragraphStyleEditable(block)) fail('paragraph_style_unsupported')
      const target = sourceParagraphStyle(op.styleId)
      const sourceId = block.styleId ?? [...parsed.styles.values()].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceId) sourceParagraphStyle(sourceId)
      return { op, block, styleId: target.styleId, ribbonStyle: op.ribbon === true }
    }
    if (op.kind === 'deleteParagraph' && coverMarkerParagraph(block)) {
      // 封面书签段只读但可整段删除（移除/替换已保存图库封面）。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256'])
      return { op, block }
    }
    if (!editableParagraph(block) && !((NOTE_LAYOUT_KINDS.has(op.kind as string) || ['setParagraphShading', 'setParagraphBorders'].includes(op.kind as string)) && notesPlanner && editableNoteReferenceBlock(block))) fail('paragraph_unsupported')
    if (op.kind === 'clearParagraphFormatting') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'ranges'])
      const content = block.runs!.map(run => run.text).join('')
      if (!Array.isArray(op.ranges) || !op.ranges.length || op.ranges.length > 100) fail('clear_formatting_range_invalid')
      const clearRanges = (op.ranges as unknown[]).map(value => {
        const range = object(value); keys(range, ['from', 'to'])
        return !content.length && range.from === 0 && range.to === 0 ? { from: 0, to: 0 } : linkRange(range, content)
      })
      return { op, block, clearRanges }
    }
    if (op.kind === 'replaceParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'text'])
      const value = text(op.text)
      if (block.runs!.some(run => run.link) && value !== block.runs!.map(run => run.text).join('')) fail('link_text_replace_unsupported')
      return { op, block, value }
    }
    if (op.kind === 'insertParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'position', 'text', 'pageBreakBefore'])
      if (op.position !== 'before' && op.position !== 'after') fail('operation_invalid')
      if (op.pageBreakBefore !== undefined && op.pageBreakBefore !== true) fail('operation_invalid')
      return { op, block, value: text(op.text) }
    }
    if (op.kind === 'setParagraphPageBreakBefore') {
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key)) || typeof op.value !== 'boolean') fail('paragraph_page_break_invalid')
      if (!block.originalXml || !/^<w:p[\s>/]/.test(block.originalXml)) fail('paragraph_page_break_unsupported')
      return { op, block, pageBreakBefore: op.value as boolean }
    }
    if (op.kind === 'insertCoverPage') {
      // 固定源 editor/cover-pages.ts：封面段落只用段落/文字基本格式；首段带 _GenOfficeCoverPage、
      // 结尾分页空段带 _GenOfficeCoverPageEnd 隐藏书签（"删除当前封面"重开后可定位）。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'position', 'paras'])
      if (op.position !== 'before') fail('operation_invalid')
      return { op, block, coverBlocks: coverPageBlocks(op.paras) }
    }
    if (op.kind === 'insertTable') {
      // 固定源 insertTableAt + editor/new-table.ts wordTableModel：整宽、等分列、autofit window、
      // 单线 0.5pt 边框、单元格垂直居中且段落单倍行距无段后间距；与前端 docx-new-table.ts 同预算。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'position', 'rows', 'cols', 'cells'])
      if (op.position !== 'before' && op.position !== 'after') fail('operation_invalid')
      const rows = op.rows, cols = op.cols
      if (!Number.isInteger(rows) || !Number.isInteger(cols) || (rows as number) < 1 || (cols as number) < 1 || (rows as number) > 100 || (cols as number) > 30 || (rows as number) * (cols as number) > 1000) fail('table_insert_invalid')
      // 保存前在新表格输入的纯文字：rows×cols 字符串，'\n' 分隔单元格段落（replaceCellText 同规）。
      let cells: string[][] | undefined
      if (op.cells !== undefined) {
        if (!Array.isArray(op.cells) || op.cells.length !== rows || op.cells.some(row => !Array.isArray(row) || row.length !== cols)) fail('table_insert_cells_invalid')
        cells = (op.cells as unknown[][]).map(row => row.map(value => text(value)))
        if (cells.reduce((sum, row) => sum + row.reduce((inner, value) => inner + value.length, 0), 0) > 200000) fail('table_insert_cells_invalid')
      }
      return { op, block, newTableXml: newWordTableXml(rows as number, cols as number, cells) }
    }
    if (op.kind === 'insertParagraphImage') {
      // 与 insertParagraph 同锚点语义：图片成为锚点前/后的独立图片段落
      // （引擎 SaveBlock {kind:'image'} → media part + 关系 + 内联 drawing）。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'position', 'image'])
      if (op.position !== 'before' && op.position !== 'after') fail('operation_invalid')
      return { op, block, image: pastedPicture(op.image) }
    }
    if (op.kind === 'setParagraphVerticalAlign') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'value'])
      if (!['baseline', 'superscript', 'subscript'].includes(op.value as string)) fail('vertical_align_invalid')
      return { op, block }
    }
    if (op.kind === 'formatParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'style'])
      const formatting = style(op.style)
      if (formatting.highlight !== undefined && !block.runs!.some(run => run.text.length)) fail('highlight_empty')
      return { op, block, formatting }
    }
    if (op.kind === 'formatRange') {
      // UTF-16选区字符格式：含显式none高亮与baseline上下标覆盖。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'from', 'to', 'style'])
      const formatting = style(op.style)
      linkRange(op, block.runs!.map(run => run.text).join(''))
      return { op, block, formatting }
    }
    if (op.kind === 'setParagraphLink') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'from', 'to', 'href'])
      if (op.href !== null && !safeLinkHref(op.href)) fail('link_href_invalid')
      if (typeof op.from !== 'number' || typeof op.to !== 'number' || !Number.isInteger(op.from) || !Number.isInteger(op.to)
          || op.from < 0 || op.from >= op.to) fail('link_range_invalid')
      return { op, block }
    }
    if (op.kind === 'setParagraphAlignment') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'alignment'])
      if (!['left', 'center', 'right', 'justify'].includes(op.alignment as string)) fail('alignment_invalid')
      return { op, block, alignment: op.alignment as ParaFormat['align'] }
    }
    if (op.kind === 'setParagraphList') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'list'])
      if (!['none', 'bullet', 'ordered'].includes(op.list as string)) fail('list_invalid')
      if (block.type === 'heading') fail('list_heading_unsupported')
      return { op, block }
    }
    if (op.kind === 'setParagraphListLevel') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'ilvl'])
      if (typeof op.ilvl !== 'number' || !Number.isInteger(op.ilvl) || op.ilvl < 0 || op.ilvl > 8) fail('list_level_invalid')
      if (block.type !== 'listItem' || !block.list) fail('list_level_unsupported')
      const definition = parsed.numbering.get(block.list.numId)
      const level = definition?.levels[op.ilvl]
      if (!level || (level.numFmt === 'bullet' || level.picBulletId != null) !== (block.list.kind === 'bullet')) fail('list_level_unsupported')
      return { op, block }
    }
    if (op.kind === 'setParagraphIndent') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'twips'])
      if (typeof op.twips !== 'number' || !Number.isInteger(op.twips) || op.twips < 0 || op.twips > 14400 || op.twips % 720 !== 0) fail('indent_invalid')
      if (block.type === 'listItem') fail('list_indent_unsupported')
      return { op, block }
    }
    if (op.kind === 'setParagraphRulerIndent') {
      if (!rulerIndentEditable(block)) fail('ruler_indent_unsupported')
      const { kind: _kind, blockId: _id, expectedObjectSha256: _hash, ...values } = op
      return { op, block, rulerIndents: normalizeDocxRulerIndent(values) }
    }
    if (op.kind === 'setParagraphTabStops') {
      keys(op, ['kind','blockId','expectedObjectSha256','stops'])
      if (!tabStopsEditable(block)) fail('tabs_source_unsupported')
      return { op, block, tabStops: normalizeDocxTabStops(op.stops) }
    }
    if (op.kind === 'setParagraphSpecialIndent') {
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'twips', 'firstLineChars'].includes(key))) fail('special_indent_invalid')
      if (!validDocxSpecialIndent(op.twips, op.firstLineChars)) fail('special_indent_invalid')
      if (block.type === 'listItem') fail('special_indent_unsupported')
      return { op, block }
    }
    if (op.kind === 'setParagraphRightIndent') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'twips'])
      if (typeof op.twips !== 'number' || !Number.isInteger(op.twips) || op.twips < -14400 || op.twips > 14400) fail('right_indent_invalid')
      return { op, block }
    }
    if (op.kind === 'setParagraphSpacing') {
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'spaceBefore', 'spaceAfter', ...DOCX_LINE_SPACING_FIELDS].includes(key))) fail('paragraph_spacing_invalid')
      const fields = ['spaceBefore', 'spaceAfter', ...DOCX_LINE_SPACING_FIELDS].filter(key => op[key] !== undefined)
      if (!fields.length) fail('paragraph_spacing_invalid')
      for (const key of ['spaceBefore', 'spaceAfter'] as const) {
        if (op[key] !== undefined && (typeof op[key] !== 'number' || !Number.isFinite(op[key]) || !Number.isInteger(op[key]) || (op[key] as number) < 0 || (op[key] as number) > 14400)) fail('paragraph_spacing_invalid')
      }
      if (!docxLineSpacingPatch(op)) fail('paragraph_spacing_invalid')
      return { op, block }
    }
    if (op.kind === 'setParagraphShading') {
      if (parsed.protection?.enforced) fail('paragraph_unsupported')
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'fill', 'clear'].includes(key))) fail('paragraph_shading_invalid')
      if ((typeof op.fill !== 'string' && op.fill !== null) || (typeof op.fill === 'string' && !/^[0-9a-f]{6}$/.test(op.fill)) || typeof op.clear !== 'boolean') fail('paragraph_shading_invalid')
      return { op, block, shading: { fill: op.fill as string | null, clear: op.clear as boolean } }
    }
    if (op.kind === 'setParagraphBorders') {
      if (parsed.protection?.enforced) fail('paragraph_unsupported')
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'borders'].includes(key))) fail('paragraph_borders_invalid')
      if (op.borders === null) return { op, block, borders: null }
      if (!Array.isArray(op.borders) || op.borders.length > 4) fail('paragraph_borders_invalid')
      const sides: string[] = []
      const lines: Record<string, { color?: string; szPt?: number; spacePt?: number }> = {}
      const sideChars: Record<string, string> = { top: 't', bottom: 'b', left: 'l', right: 'r' }
      for (const entry of op.borders as unknown[]) {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) fail('paragraph_borders_invalid')
        const line = entry as ObjectValue
        if (Object.keys(line).some(key => !['side', 'val', 'color', 'szPt', 'spacePt'].includes(key))) fail('paragraph_borders_invalid')
        if (typeof line.side !== 'string' || !(line.side in sideChars) || sides.includes(sideChars[line.side]!) || line.val !== 'single') fail('paragraph_borders_invalid')
        if (line.color !== undefined && line.color !== null && (typeof line.color !== 'string' || !/^[0-9a-fA-F]{6}$/.test(line.color))) fail('paragraph_borders_invalid')
        if (line.szPt !== undefined && line.szPt !== null && (typeof line.szPt !== 'number' || !Number.isFinite(line.szPt) || line.szPt <= 0 || line.szPt > 12 || !Number.isInteger(line.szPt * 8))) fail('paragraph_borders_invalid')
        if (line.spacePt !== undefined && line.spacePt !== null && (typeof line.spacePt !== 'number' || !Number.isInteger(line.spacePt) || (line.spacePt as number) < 0 || (line.spacePt as number) > 31)) fail('paragraph_borders_invalid')
        const ch = sideChars[line.side]!
        sides.push(ch)
        lines[ch] = {
          ...(typeof line.color === 'string' ? { color: line.color.toUpperCase() } : {}),
          ...(typeof line.szPt === 'number' ? { szPt: line.szPt } : {}),
          ...(typeof line.spacePt === 'number' ? { spacePt: line.spacePt } : {}),
        }
      }
      // 源 pBdr 子序 t,b,l,r（parse-props.ts paraBordersOf 规范序）。
      const order = ['t', 'b', 'l', 'r']
      sides.sort((left, right) => order.indexOf(left) - order.indexOf(right))
      return { op, block, borders: { sides: sides.join(''), lines } }
    }
    if (op.kind === 'deleteParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256'])
      return { op, block }
    }
    return fail('operation_unsupported')
  }))
  const nestedTargets = new Set<string>()
  for (const item of operations) if (item.nested) {
    if (nestedTargets.has(item.nested.target.anchor.cellId) || operations.some(other => other !== item && other.block === item.block && !other.nested)) fail('nested_batch_conflict')
    nestedTargets.add(item.nested.target.anchor.cellId)
  }
  for (const item of operations) if (item.styleId && operations.some(other => other.block === item.block && (other.op.kind !== 'setParagraphStyle' || item.op.ribbon === true && other !== item))) fail('paragraph_style_batch_conflict')
  for (const item of operations) if (item.clearRanges && operations.some(other => other.block === item.block && other.op !== item.op)) fail('clear_formatting_batch_conflict')
  // 独立 pPr 属性允许各一次边框与底纹；其他同段修改和重复操作仍拒绝。
  for (const item of operations) if (item.shading && operations.some(other => other.block === item.block && other.op !== item.op && other.op.kind !== 'setParagraphBorders' && !NOTE_LAYOUT_KINDS.has(other.op.kind as string))) fail('paragraph_shading_batch_conflict')
  for (const item of operations) if (item.borders !== undefined && operations.some(other => other.block === item.block && other.op !== item.op && other.op.kind !== 'setParagraphShading' && !NOTE_LAYOUT_KINDS.has(other.op.kind as string))) fail('paragraph_borders_batch_conflict')
  // 段前分页补丁与底纹/边框同规：同段同批次只允许一次分页操作。锚定在该段前/后的
  // 新段插入（空白页 = 新空段 + 后续段分页）只放入 before/after，不改写该段 XML，可共存。
  const anchoredInsert = (kind: unknown) => kind === 'insertParagraph' || kind === 'insertParagraphImage' || kind === 'insertTable' || kind === 'insertCoverPage'
  // 封面恒在文档开头（固定源语义）：锚点必须是正文首个保留块，每批至多一个封面。
  const covers = operations.filter(item => item.op.kind === 'insertCoverPage')
  if (covers.length > 1) fail('cover_page_batch_conflict')
  for (const item of operations) if (item.pageBreakBefore !== undefined && operations.some(other => other.block === item.block && other.op !== item.op && !anchoredInsert(other.op.kind))) fail('paragraph_page_break_batch_conflict')
  for (const item of operations) if (item.op.kind === 'setTableCellBorders' && operations.some(other => other !== item && other.block === item.block && other.op.kind !== 'setCellShading')) fail('cell_borders_batch_conflict')
  for(const item of operations)if(item.op.kind==='setTableRepeatHeaders'&&operations.some(other=>other!==item&&other.block===item.block))fail('table_repeat_headers_batch_conflict')
  for (const item of operations) if ((item.rulerIndents || item.tabStops) && operations.filter(other => other.block === item.block).length > 1) fail('ruler_batch_conflict')
  for (const item of operations) if (item.tableCellShape && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_shape_batch_conflict')
  for (const item of operations) if (item.tableAltText && operations.some(other => other !== item && other.block === item.block)) fail('table_alt_text_batch_conflict')
  for (const item of operations) if (item.tableCellWrap && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_wrap_batch_conflict')
  for (const item of operations) if (item.tableAlignment && operations.some(other => other !== item && other.block === item.block)) fail('table_alignment_batch_conflict')
  for (const item of operations) if (item.tableRowBreaks && operations.some(other => other !== item && other.block === item.block)) fail('table_row_breaks_batch_conflict')
  for (const item of operations) if (item.tableCellMarginOverrides && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_margin_overrides_batch_conflict')
  for (const item of operations) if (item.tableCellMargins && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_margins_batch_conflict')
  for (const item of operations) if (item.tableCellAlignment && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_alignment_batch_conflict')
  for (const item of operations) if (item.tableCellTextDirection && operations.some(other => other !== item && other.block === item.block)) fail('table_cell_text_direction_batch_conflict')
  for (const item of operations) if (item.tableAutoFit && operations.some(other => other !== item && other.block === item.block)) fail('table_autofit_batch_conflict')
  for (const item of operations) if (item.tableAutoFit) {
    const section = tableColumnWidthSection(item.block)
    if (operations.some(other => other.section === section || other.sectionBreak?.section === section)) fail('table_autofit_section_batch_conflict')
  }
  for (const item of operations) if (item.tableRowHeights && operations.some(other => other !== item && other.block === item.block)) fail('table_row_height_batch_conflict')
  for (const item of operations) if (item.tableRowHeights) {
    const section = tableColumnWidthSection(item.block)
    if (operations.some(other => other.section === section || other.sectionBreak?.section === section)) fail('table_row_height_section_batch_conflict')
  }
  for (const item of operations) if (item.tableColumnWidths && operations.some(other => other !== item && other.block === item.block)) fail('table_column_width_batch_conflict')
  for (const item of operations) if (item.tableColumnWidths) {
    const section = allSections.find(current => current.firstBlockIndex <= item.block.docxIndex! && item.block.docxIndex! <= current.lastBlockIndex)
    if (operations.some(other => other.section === section || other.sectionBreak?.section === section)) fail('table_column_width_section_batch_conflict')
  }
  const structuralTables = new Set<string>()
  for (const item of operations) if (item.tableStructure) {
    const id = blockId(item.block)
    if (structuralTables.has(id)) fail('table_structure_batch_conflict')
    structuralTables.add(id)
  }
  for (const item of operations) if (item.cell && structuralTables.has(blockId(item.block))) fail('table_structure_batch_conflict')
  for (const item of operations) if (item.op.kind === 'setCellShading' && operations.some(other => other !== item && other.block === item.block && other.cell?.row === item.cell!.row && other.cell?.column === item.cell!.column)) fail('cell_shading_batch_conflict')
  // 每节每批至多一个分节符；同批不能再改该节页面设置（新节副本须取自原 sectPr）。
  const brokenSections = new Set<unknown>(), laidOutSections = new Set<unknown>()
  for (const item of operations) {
    if (item.sectionBreak) { if (brokenSections.has(item.sectionBreak.section)) fail('section_break_batch_conflict'); brokenSections.add(item.sectionBreak.section) }
    if (item.section) { if (laidOutSections.has(item.section)) fail('section_layout_batch_conflict'); laidOutSections.add(item.section) }
  }
  for (const section of brokenSections) if (laidOutSections.has(section)) fail('section_break_batch_conflict')
  const states = new Map(blocks.map(block => [blockId(block), {
    block, saved: {kind: 'original', docxIndex: block.docxIndex!} as SaveBlock,
    before: [] as SaveBlock[], after: [] as SaveBlock[], deleted: false,
    tableStructure: undefined as ReturnType<typeof editTableStructure> | undefined,
    styleId: undefined as string | undefined,
    shading: undefined as { fill: string | null; clear: boolean } | undefined,
    borders: undefined as { sides: string; lines: Record<string, { color?: string; szPt?: number; spacePt?: number }> } | null | undefined,
    pageBreakBefore: undefined as boolean | undefined,
    cellValues: new Map<string, {row: number; column: number; text: string}>(),
  }]))
  for (const [identity, runs] of [...(notesPlan?.blocks ?? []), ...finalParagraphs]) {
    const state = states.get(identity)!
    if (operations.some(item => item.block === state.block && !NOTE_LAYOUT_KINDS.has(item.op.kind as string)
      && !(item.op.kind === 'setParagraphShading' && paragraphDecorationEditable(state.block, 'shading'))
      && !(item.op.kind === 'setParagraphBorders' && paragraphDecorationEditable(state.block, 'borders')))) fail('note_body_batch_conflict')
    state.saved = { kind: 'generated', block: { ...generated(state.block), runs } }
  }
  for (const [identity, group] of revisionGroups) {
    if (notesPlan?.blocks.has(identity) || finalParagraphs.has(identity)) fail('revision_batch_conflict')
    states.get(identity)!.saved = { kind: 'xml', docxIndex: group.block.docxIndex!, xml: group.xml! }
  }
  // 引擎补建缺失 numbering.xml 时自带 1/2 两个模板定义。
  let nextNumId = Math.max(2, ...[...parsed.numbering.keys()].map(id => Number(id)).filter(Number.isSafeInteger)) + 1
  const newDefs: { numId: string; kind: 'bullet' | 'ordered' }[] = []
  let sectionValues: Partial<SectionSettings> | undefined
  // 非尾节：分节段 sectPr 的页面设置 / 起始方式补丁；尾节起始方式经 saveDocx sectionStartType。
  const sectionPatches = new Map<typeof trailingSection, { values?: SectionEditValues; type?: SectionBreakType }>()
  let trailingStartType: SectionBreakType | undefined
  let hfTitlePg: boolean | undefined, hfEvenOdd: boolean | undefined
  let hfFmt: string | null | undefined, hfStart: number | null | undefined
  for (const edit of hfEdits.values()) {
    if (edit.titlePg !== undefined) hfTitlePg = edit.titlePg
    if (edit.evenAndOddHeaders !== undefined) hfEvenOdd = edit.evenAndOddHeaders
    if (edit.pageNumberFmt !== undefined) hfFmt = edit.pageNumberFmt
    if (edit.pageNumberStart !== undefined) hfStart = edit.pageNumberStart
  }
  const listId = (kind: 'bullet' | 'ordered') => {
    const existing = blocks.find(block => block.list?.kind === kind && block.list.ilvl === 0)
    if (existing?.list) return existing.list.numId
    let definition = newDefs.find(definition => definition.kind === kind)
    if (!definition) { definition = { kind, numId: String(nextNumId++) }; newDefs.push(definition) }
    return definition.numId
  }
  for (const item of operations) {
    if (item.sectionValues) {
      if (item.section === trailingSection) {
        const { titlePg, evenAndOddHeaders, pageNumberFmt, pageNumberStart, ...layout } = item.sectionValues
        if (titlePg !== undefined) {
          if (hfTitlePg !== undefined && hfTitlePg !== titlePg) fail('section_title_page_batch_conflict')
          hfTitlePg = titlePg
        }
        if (evenAndOddHeaders !== undefined) {
          if (hfEvenOdd !== undefined && hfEvenOdd !== evenAndOddHeaders) fail('document_even_odd_batch_conflict')
          hfEvenOdd = evenAndOddHeaders
        }
        if (pageNumberFmt !== undefined) {
          if (hfFmt !== undefined && hfFmt !== pageNumberFmt) fail('section_page_number_batch_conflict')
          hfFmt = pageNumberFmt
        }
        if (pageNumberStart !== undefined) {
          if (hfStart !== undefined && hfStart !== pageNumberStart) fail('section_page_number_batch_conflict')
          hfStart = pageNumberStart
        }
        if (Object.keys(layout).length) sectionValues = { ...sectionValues, ...layout }
      }
      else sectionPatches.set(item.section!, { ...sectionPatches.get(item.section!), values: item.sectionValues })
      continue
    }
    if (item.sectionBreak) {
      const { section, type } = item.sectionBreak
      states.get(blockId(item.block))!.after.push({ kind: 'xml', xml: `<w:p><w:pPr>${section.sectPrXml}</w:pPr></w:p>` })
      if (section === trailingSection) trailingStartType = type
      else sectionPatches.set(section, { ...sectionPatches.get(section), type })
      continue
    }
    const state = states.get(blockId(item.block))!
    if (state.deleted) fail('operation_after_delete')
    if (item.clearRanges) {
      const defaultStyleId = [...parsed.styles.values()].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      state.saved = { kind: 'generated', docxIndex: item.block.docxIndex!, block: clearedParagraph(item.block, item.clearRanges, defaultStyleId) }
    } else if (item.styleId) {
      state.styleId = item.styleId
    } else if (item.shading) {
      state.shading = item.shading
    } else if (item.borders !== undefined) {
      state.borders = item.borders
    } else if (item.pageBreakBefore !== undefined) {
      state.pageBreakBefore = item.pageBreakBefore
    } else if (item.tableAltText) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableAltText.xml }
    } else if (item.tableCellWrap) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellWrap.xml }
    } else if (item.tableAlignment) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableAlignment.xml }
    } else if (item.tableRowBreaks) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableRowBreaks.xml }
    } else if (item.tableCellMarginOverrides) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellMarginOverrides.xml }
    } else if (item.tableCellMargins) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellMargins.xml }
    } else if (item.tableCellAlignment) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellAlignment.xml }
    } else if (item.tableCellTextDirection) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellTextDirection.xml }
    } else if (item.tableAutoFit) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableAutoFit.xml }
    } else if (item.tableRowHeights) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableRowHeights.xml }
    } else if (item.tableColumnWidths) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableColumnWidths.xml }
    } else if (item.tableCellShape) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableCellShape.xml }
    } else if (item.tableStructure) {
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: item.tableStructure.xml }
      state.tableStructure = item.tableStructure
    } else if (item.op.kind === 'insertParagraph') {
      state[item.op.position as 'before' | 'after'].push({ kind: 'generated', block: {type: 'paragraph', runs: [{text:item.value!}], ...(item.op.pageBreakBefore === true ? { format: { pageBreakBefore: true } } : {})} })
    } else if (item.op.kind === 'insertCoverPage') {
      state.before.push(...item.coverBlocks!.map(block => ({ kind: 'generated' as const, block })))
    } else if (item.op.kind === 'insertTable') {
      state[item.op.position as 'before' | 'after'].push({ kind: 'xml', xml: item.newTableXml! })
    } else if (item.op.kind === 'insertParagraphImage') {
      state[item.op.position as 'before' | 'after'].push({ kind: 'image', image: item.image! })
    } else if (item.op.kind === 'deleteParagraph') {
      state.deleted = true
    } else if (item.op.kind === 'setTableRepeatHeaders') {
      state.saved={kind:'xml',docxIndex:item.block.docxIndex!,xml:patchTableRepeatHeaders(item.block.originalXml!,item.op.expectedRowCount,item.op.headers,item.op.prefixRowCount)}
    } else if (item.op.kind === 'setTableCellBorders') {
      // 身份及steps已对原始来源整批核验；在当前XML上合成，避免覆盖先前shd补丁。
      const xml = state.saved.kind === 'xml' ? state.saved.xml : item.block.originalXml!
      const cells = cellXmls(item.block).map((row, r) => row.map((_, c) => ({ cellId: cellId(item.block, r, c) })))
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: patchDocxTableCellBorders(xml, item.op.steps, cells) }
    } else if (item.op.kind === 'setCellShading') {
      const xml = state.saved.kind === 'xml' ? state.saved.xml : item.block.originalXml!
      const rows = xmlSegments(xml, 'w:tr', 0, xml.length), row = rows[item.cell!.row]!
      const cells = xmlSegments(xml, 'w:tc', row.start, row.end), cell = cells[item.cell!.column]!
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: xml.slice(0, cell.start) + patchDocxCellShading(xml.slice(cell.start, cell.end), item.op.fill) + xml.slice(cell.end) }
    } else if (item.nested) {
      const xml = state.saved.kind === 'xml' ? state.saved.xml : item.block.originalXml!
      state.saved = { kind: 'xml', docxIndex: item.block.docxIndex!, xml: patchNestedCellText(xml, item.nested.target, item.nested.paragraphs) }
    } else if (item.op.kind === 'replaceCellText') {
      const xml = state.saved.kind === 'xml' ? state.saved.xml : item.block.originalXml!
      const grid: (null | (null | string[])[])[] = []
      grid[item.cell!.row] = []
      grid[item.cell!.row]![item.cell!.column] = [item.value!]
      const patched = patchTableCellTexts(xml, grid)
      state.saved = {kind:'xml', docxIndex:item.block.docxIndex!, xml:patched}
      state.cellValues.set(`${item.cell!.row}:${item.cell!.column}`, {row:item.cell!.row, column:item.cell!.column, text:item.value!})
    } else {
      const block = state.saved.kind === 'generated' ? state.saved.block : generated(item.block)
      if (item.op.kind === 'setParagraphVerticalAlign') {
        if (!block.runs.some(run => run.text.length)) fail('vertical_align_empty')
        block.runs = block.runs.map(run => item.op.value === 'baseline'
          ? { ...run, vertAlign: undefined, rawRPr: baselineRunProperties(run.rawRPr) }
          : { ...run, vertAlign: item.op.value as 'superscript' | 'subscript' })
      } else if (item.op.kind === 'formatParagraph') {
        block.runs = (block.runs.length ? block.runs : [{ text: '' }]).map(run => applyRunFormatting(run, item.formatting!, object(item.op.style)))
      } else if (item.op.kind === 'formatRange') {
        const range = linkRange(item.op, block.runs.map(run => run.text).join(''))
        block.runs = formattedRuns(block.runs, range.from, range.to, item.formatting!, object(item.op.style))
      } else if (item.op.kind === 'setParagraphLink') {
        const range = linkRange(item.op, block.runs.map(run => run.text).join(''))
        block.runs = linkedRuns(block.runs, range.from, range.to, item.op.href as string | null)
      } else if (item.op.kind === 'setParagraphAlignment') {
        block.format = { ...block.format, align: item.alignment }
        const rawPPr = (block.rawPPr || '<w:pPr></w:pPr>').replace(/^<w:pPr([^>]*)\/>$/, '<w:pPr$1></w:pPr>')
        block.rawPPr = mergePPrFormat(rawPPr, block.format, item.block.format, new Set(['w:jc']))
      } else if (item.op.kind === 'setParagraphList') {
        const kind = item.op.list as 'none' | 'bullet' | 'ordered'
        const numId = kind === 'none' ? '0' : listId(kind)
        block.type = kind === 'none' ? 'paragraph' : 'listItem'
        block.list = kind === 'none' ? undefined : { kind, numId, ilvl: 0 }
        // numId=0 also cancels numbering inherited from the paragraph style.
        const raw = block.rawPPr ?? ''
        const opening = /^<w:pPr(?:\s[^>]*)?>/.exec(raw)?.[0] ?? '<w:pPr>'
        const children = raw.endsWith('</w:pPr>') ? splitXmlChildren(raw.slice(opening.length, -'</w:pPr>'.length)).filter(child => child.name !== 'w:numPr') : []
        const numPr = pPrWithNumPr('', { numId, ilvl: 0 }).slice('<w:pPr>'.length, -'</w:pPr>'.length)
        const at = children.findIndex(child => PPR_CHILD_ORDER.indexOf(child.name) > PPR_CHILD_ORDER.indexOf('w:numPr'))
        children.splice(at < 0 ? children.length : at, 0, { name: 'w:numPr', xml: numPr })
        block.rawPPr = `${opening}${children.map(child => child.xml).join('')}</w:pPr>`
      } else if (item.op.kind === 'setParagraphListLevel') {
        if (!block.list) fail('list_level_unsupported')
        block.list = { ...block.list, ilvl: item.op.ilvl as number }
        block.rawPPr = pPrWithNumPr(block.rawPPr ?? '', { numId: block.list.numId, ilvl: block.list.ilvl })
      } else if (item.op.kind === 'setParagraphIndent') {
        block.format = { ...block.format, indentLeft: item.op.twips as number }
        block.rawPPr = pPrWithIndLeft(block.rawPPr ?? '', item.op.twips as number)
      } else if (item.tabStops) {
        const previous = { ...block.format, tabStops: undefined }
        block.format = { ...block.format, tabStops: item.tabStops }
        block.rawPPr = mergeCellParaFormat(block.rawPPr || '<w:pPr></w:pPr>', block.format, previous)
      } else if (item.rulerIndents) {
        const values = item.rulerIndents
        const previous = { ...block.format, ...(values.leftTwips !== undefined ? { indentLeft: undefined } : {}), ...(values.firstLineTwips !== undefined ? { indentFirstLine: undefined } : {}) }
        block.format = { ...block.format, ...(values.leftTwips !== undefined ? { indentLeft: values.leftTwips } : {}), ...(values.firstLineTwips !== undefined ? { indentFirstLine: values.firstLineTwips } : {}) }
        block.rawPPr = mergeCellParaFormat(block.rawPPr || '<w:pPr></w:pPr>', block.format, previous)
      } else if (item.op.kind === 'setParagraphSpecialIndent') {
        const previous = { ...block.format, indentFirstLine: undefined }
        block.format = { ...block.format, indentFirstLine: item.op.twips as number,
          charIndents: { ...block.format?.charIndents, firstLine: item.op.firstLineChars as number | undefined, hanging: undefined } }
        // 保留左右缩进；字符首行保留原生单位，其余显式零覆盖直接或继承字符特殊缩进。
        block.rawPPr = mergeCellParaFormat(block.rawPPr || '<w:pPr></w:pPr>', block.format, previous)
          .replace(/<w:ind\b([^>]*)\/>/, (_, attrs: string) => `<w:ind${attrs.replace(/\s+w:(?:firstLineChars|hangingChars)="[^"]*"/g, '')} w:firstLineChars="${item.op.firstLineChars ?? 0}" w:hangingChars="0"/>`)
      } else if (item.op.kind === 'setParagraphRightIndent') {
        block.format = { ...block.format, indentRight: item.op.twips as number }
        block.rawPPr = pPrWithIndRight(block.rawPPr ?? '', item.op.twips as number)
      } else if (item.op.kind === 'setParagraphSpacing') {
        const values = item.op as ObjectValue
        // 命令同时清自动间距，即使数值未变也要重建对应的属性组。
        const previousFormat = { ...block.format,
          ...(values.spaceBefore !== undefined ? { spaceBefore: undefined } : {}),
          ...(values.spaceAfter !== undefined ? { spaceAfter: undefined } : {}),
        }
        block.format = { ...block.format,
          ...(values.spaceBefore !== undefined ? { spaceBefore: values.spaceBefore as number } : {}),
          ...(values.spaceAfter !== undefined ? { spaceAfter: values.spaceAfter as number } : {}),
          ...Object.fromEntries(Object.entries(docxLineSpacingPatch(values)!).map(([key, value]) => [key, value ?? undefined])),
          ...(values.spaceBefore !== undefined ? { spaceBeforeAuto: undefined } : {}),
          ...(values.spaceAfter !== undefined ? { spaceAfterAuto: undefined } : {}),
        }
        const rawPPr = (block.rawPPr || '<w:pPr></w:pPr>').replace(/^<w:pPr([^>]*)\/>$/, '<w:pPr$1></w:pPr>')
        block.rawPPr = mergeCellParaFormat(rawPPr, block.format, previousFormat)
        if (values.spaceBefore === 0) block.rawPPr = pPrWithZeroSpaceBefore(block.rawPPr)
      } else {
        if (block.runs.some(run => run.link) && item.value !== block.runs.map(run => run.text).join('')) fail('link_text_replace_unsupported')
        let remaining = Array.from(item.value!)
        block.runs = (block.runs.length ? block.runs : [{ text: '' }]).map((run, index, runs) => {
          const length = index === runs.length - 1 ? remaining.length : Array.from(run.text).length
          const value = remaining.splice(0, length).join('')
          return {...run, text:value}
        })
      }
      state.saved = {kind:'generated', docxIndex:item.block.docxIndex!, block}
    }
  }
  for (const cover of covers) {
    const at = cover.block ? blocks.indexOf(cover.block) : -1
    if (at < 0 || blocks.slice(0, at).some(block => !states.get(blockId(block))!.deleted)) fail('cover_page_not_at_start')
  }
  for (const state of states.values()) if (state.styleId) {
    const original = state.block.originalXml ?? fail('paragraph_style_xml_invalid')
    const ribbon = operations.some(item => item.block === state.block && item.op.kind === 'setParagraphStyle' && item.op.ribbon === true)
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: ribbon ? ribbonStyleXml(state.block, state.styleId) : paragraphStyleXml(original, state.styleId) }
  }
  for (const state of states.values()) if (state.shading || state.borders !== undefined) {
    // 最终run先编译；边框底纹只合成其当前pPr，不用原XML覆盖已编辑的正文。
    const generated = state.saved.kind === 'generated' ? state.saved.block : undefined
    let xml = generated ? `<w:p>${generated.rawPPr ?? ''}</w:p>` : state.saved.kind === 'xml' ? state.saved.xml : state.block.originalXml ?? fail('paragraph_decoration_xml_invalid')
    if (state.shading) xml = paragraphShadingXml(xml, state.shading)
    if (state.borders !== undefined) xml = paragraphBordersXml(xml, state.borders)
    if (generated) {
      const pPr = xmlSegments(xml, 'w:pPr', 0, xml.length)[0]
      generated.rawPPr = pPr ? xml.slice(pPr.start, pPr.end) : ''
    } else state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml }
  }
  for (const state of states.values()) if (state.pageBreakBefore !== undefined) {
    const original = state.block.originalXml ?? fail('paragraph_page_break_xml_invalid')
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: paragraphPageBreakBeforeXml(original, state.pageBreakBefore) }
  }
  for (const [section, patch] of sectionPatches) {
    const breakBlock = blocks.find(block => block.docxIndex === section.lastBlockIndex)
    const state = breakBlock && states.get(blockId(breakBlock))
    const original = breakBlock?.originalXml
    if (!state || !original || state.saved.kind !== 'original' || !original.includes(section.sectPrXml)) fail('section_break_paragraph_invalid')
    let sectPr = section.sectPrXml
    if (patch.values) {
      const { titlePg, pageNumberFmt, pageNumberStart, ...layout } = patch.values
      if (Object.keys(layout).length) sectPr = applySectionSettings(sectPr, { ...section.settings, ...layout })
      if (titlePg !== undefined) sectPr = applyTitlePg(sectPr, titlePg)
      if (pageNumberFmt !== undefined || pageNumberStart !== undefined) sectPr = applyPageNumType(sectPr,
        pageNumberFmt === undefined ? section.pageNumberFmt : pageNumberFmt ?? undefined,
        pageNumberStart === undefined ? section.pageNumberStart : pageNumberStart ?? undefined)
    }
    if (patch.type) sectPr = applySectionStartType(sectPr, patch.type)
    state.saved = { kind: 'xml', docxIndex: breakBlock.docxIndex!, xml: original.replace(section.sectPrXml, () => sectPr) }
  }
  const finalBlocks: SaveBlock[] = []
  for (const state of states.values()) finalBlocks.push(...state.before, ...(state.deleted ? [] : [state.saved]), ...state.after)
  // 页码格式/起始：null = 移除该字段；只改其一未提供时沿用当前值（w:pgNumType 整体重写）。
  let pgNumType: { fmt?: string; start?: number } | undefined
  if (hfFmt !== undefined || hfStart !== undefined) {
    pgNumType = {}
    const fmt = hfFmt === undefined ? trailingSection.pageNumberFmt : hfFmt ?? undefined
    const start = hfStart === undefined ? trailingSection.pageNumberStart : hfStart ?? undefined
    if (fmt !== undefined) pgNumType.fmt = fmt
    if (start !== undefined) pgNumType.start = start
  }
  const hfOptionKey = (edit: HeaderFooterEdit) =>
    `${edit.part}${edit.variant === 'default' ? '' : edit.variant[0]!.toUpperCase() + edit.variant.slice(1)}` as 'header' | 'footer' | 'headerFirst' | 'footerFirst' | 'headerEven' | 'footerEven'
  const hfOptions = Object.fromEntries([...hfEdits.values()].filter(edit => !edit.afterLink && edit.section === trailingSection).map(edit => [hfOptionKey(edit), edit.value])) as Partial<Record<'header' | 'footer' | 'headerFirst' | 'footerFirst' | 'headerEven' | 'footerEven', HeaderFooter>>
  let output = await saveDocx(parsed, finalBlocks, {
    ...(notesPlan?.footnotes !== undefined ? { footnotes: notesPlan.footnotes } : {}),
    ...(notesPlan?.endnotes !== undefined ? { endnotes: notesPlan.endnotes } : {}),
    ...(newDefs.length ? { numbering: { newDefs } } : {}),
    ...(sectionValues ? { section: { ...readSectionSettings(parsed), ...sectionValues } } : {}),
    ...(trailingStartType ? { sectionStartType: trailingStartType } : {}),
    ...hfOptions,
    sectionHf: [...hfEdits.values()].filter(edit => !edit.afterLink && edit.section !== trailingSection).map(edit => ({ lastBlockIndex: edit.section.lastBlockIndex, kind: edit.part, variant: edit.variant, hf: edit.value })),
    ...(hfTitlePg !== undefined ? { titlePg: hfTitlePg } : {}),
    ...(hfEvenOdd !== undefined ? { evenAndOddHeaders: hfEvenOdd } : {}),
    ...(pgNumType ? { pgNumType } : {}),
    ...(pageColor !== undefined ? { pageColor } : {}),
    ...(watermark !== undefined ? { watermark } : {}),
  })
  const preserveHfNamespaces = async (input: Uint8Array, selected: HeaderFooterEdit[]) => {
    if (!selected.length) return input
    // 上游重建HF根节点只带少数固定xmlns；原绘图节点仍可能使用wp、mc等声明。
    // 原根属性完整保留，仅补引擎新生成节点所需而来源未声明的namespace。
    const editedZip = await loadDocxZip(input)
    const editedSections = readSections(await parseDocx(input))
    const editedTargets = await parseRels(editedZip, 'word/_rels/document.xml.rels')
    for (const edit of selected) {
      const originalXml = edit.sourceXml
      if (!originalXml) continue
      const originalRoot = /<w:(?:hdr|ftr)\b[^>]*>/.exec(originalXml)?.[0]
      const section = editedSections[allSections.indexOf(edit.section)]!
      const id = (edit.part === 'header' ? section.headerRefs : section.footerRefs)[edit.variant]
      const target = id ? editedTargets.get(id)?.target : undefined
      const path = target ? resolvePartPath('word', target) : null
      if (!originalRoot || !path) fail('hf_reference_invalid')
      const xml = await editedZip.file(path)!.async('string'), root = /<w:(?:hdr|ftr)\b[^>]*>/.exec(xml)?.[0]
      if (!root) fail('hf_write_not_applied')
      let preserved = originalRoot.replace(/\/>$/, '>')
      for (const match of root.matchAll(/\s+xmlns(?::[\w.-]+)?=["'][^"']*["']/g)) {
        const name = /^\s*(xmlns(?::[\w.-]+)?)=/.exec(match[0])![1]!
        if (!new RegExp(`\\s${name}=`).test(preserved)) preserved = preserved.slice(0, -1) + match[0] + '>'
      }
      editedZip.file(path, xml.replace(root, () => preserved))
    }
    return editedZip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
  }
  output = await preserveHfNamespaces(output, [...hfEdits.values()].filter(edit => !edit.afterLink))
  if (hfLinks.size) {
    const outputZip = await loadDocxZip(output)
    let documentXml = await outputZip.file('word/document.xml')!.async('string')
    let relsXml = await outputZip.file('word/_rels/document.xml.rels')!.async('string')
    let typesXml = await outputZip.file('[Content_Types].xml')!.async('string')
    const current = readSections(await parseDocx(output))
    const outputTargets = new Map<string, string>()
    for (const match of relsXml.matchAll(/<Relationship\b[^>]*>/g)) {
      const id = /\bId="([^"]+)"/.exec(match[0])?.[1], target = /\bTarget="([^"]+)"/.exec(match[0])?.[1]
      if (id && target && !/\bTargetMode="External"/.test(match[0])) outputTargets.set(id, resolvePartPath('word', target))
    }
    let sectionCursor = 0
    const clonedParts: string[] = []
    // 来源身份先整体校验，按文档节顺序处理继承；后节复制前节本批已生效的部件。
    const inspectOutputRelationships = createHfRelationshipInspector(outputZip)
    const effective = new Map<string, { xml: string; rId: string | null; path: string | null; copyable: boolean }>()
    for (const [index, section] of current.entries()) {
      let sectPr = section.sectPrXml
      const offset = documentXml.indexOf(section.sectPrXml, sectionCursor)
      if (offset < 0) fail('hf_section_write_invalid')
      for (const key of HF_PART_KEYS) {
        const [part, variant] = key.split('.') as [HeaderFooterPart, HfVariant]
        const rId = (part === 'header' ? section.headerRefs : section.footerRefs)[variant] ?? null
        const ownPath = rId ? outputTargets.get(rId) : undefined
        if (rId && (!ownPath || !outputZip.file(ownPath))) fail('hf_reference_invalid')
        const ownXml = rId ? await outputZip.file(ownPath!)!.async('string') : ''
        const graph = await inspectOutputRelationships(ownPath ?? null)
        const own = rId ? { xml: ownXml, rId, path: ownPath!, copyable: !graph.reason } : undefined
        const inherited = effective.get(key) ?? { xml: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:${part === 'header' ? 'hdr' : 'ftr'} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p/></w:${part === 'header' ? 'hdr' : 'ftr'}>`, rId: null, path: null, copyable: true }
        const link = hfLinks.get(`${index}:${part}:${variant}`)
        let next = own ?? inherited
        if (link && link.linked !== !rId) {
          sectPr = removeHfReference(sectPr, part, variant)
          if (link.linked) next = inherited
          else {
            if (!inherited.copyable) fail('hf_link_unsupported')
            const directory = inherited.path ? posix.dirname(inherited.path) : 'word'
            let n = 1, path = posix.join(directory, `${part}${n}.xml`)
            while (outputZip.file(path) || outputZip.file(hfRelsPath(path))) { n++; path = posix.join(directory, `${part}${n}.xml`) }
            const target = posix.relative('word', path).split('/').map(encodeURIComponent).join('/')
            const partName = '/' + path.split('/').map(encodeURIComponent).join('/')
            outputZip.file(path, inherited.xml)
            const inheritedRels = inherited.path ? outputZip.file(hfRelsPath(inherited.path)) : null
            if (inheritedRels) outputZip.file(hfRelsPath(path), await inheritedRels.async('uint8array'))
            let rel = 1
            while (new RegExp(`\\bId="rId${rel}"`).test(relsXml)) rel++
            const newRId = `rId${rel}`
            relsXml = relsXml.replace('</Relationships>', `<Relationship Id="${newRId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${part}" Target="${target}"/></Relationships>`)
            typesXml = typesXml.replace('</Types>', `<Override PartName="${partName}" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.${part}+xml"/></Types>`)
            const ref = `<w:${part}Reference w:type="${variant}" r:id="${newRId}"/>`
            const opening = /^<w:sectPr\b[^>]*>/.exec(sectPr)?.[0] ?? fail('hf_section_write_invalid')
            const existingHeaders = part === 'footer' ? sectPr.slice(opening.length).match(/^(?:<w:headerReference\b[^>]*\/>)+/)?.[0] ?? '' : ''
            const at = opening.length + existingHeaders.length
            sectPr = sectPr.slice(0, at) + ref + sectPr.slice(at)
            clonedParts.push(path)
            next = { xml: inherited.xml, rId: newRId, path, copyable: true }
          }
        }
        effective.set(key, next)
      }
      documentXml = documentXml.slice(0, offset) + sectPr + documentXml.slice(offset + section.sectPrXml.length)
      sectionCursor = offset + sectPr.length
    }
    outputZip.file('word/document.xml', documentXml)
    outputZip.file('word/_rels/document.xml.rels', relsXml)
    outputZip.file('[Content_Types].xml', typesXml)
    // 必须按新part真实目录和最终内容类型重新读取，避免相对Target迁移后悬空。
    const verifyClonedRelationships = createHfRelationshipInspector(outputZip)
    for (const path of clonedParts) if ((await verifyClonedRelationships(path)).reason) fail('hf_link_write_not_applied')
    const core = sourceZip.file('docProps/core.xml')
    if (core) outputZip.file('docProps/core.xml', await core.async('uint8array'))
    output = await outputZip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
  }
  const afterLinkEdits = [...hfEdits.values()].filter(edit => edit.afterLink)
  if (afterLinkEdits.length) {
    // 新own先由已核验的原XML/rels建立，再复用原生引擎编辑该新part，避免写穿继承owner。
    const linked = await parseDocx(output), linkedSections = readSections(linked)
    const changedEdits: HeaderFooterEdit[] = []
    for (const edit of afterLinkEdits) {
      const section = linkedSections[allSections.indexOf(edit.section)]!
      const id = (edit.part === 'header' ? section.headerRefs : section.footerRefs)[edit.variant]
      const info = id ? linked.hfParts?.[id] : undefined
      if (!info) fail('hf_after_link_invalid')
      edit.value = hfValueFromText(info, edit.lines.join('\n'), edit.pageNumber, edit.align)
      const sameAlign = edit.align === undefined || (info.paras ?? []).filter(simpleHfPara).every(para => (para.align ?? 'left') === edit.align)
      if (editableHfText(info) !== expectedHfText(edit) || !sameAlign) changedEdits.push(edit)
    }
    const options = Object.fromEntries(changedEdits.filter(edit => edit.section === trailingSection).map(edit => [hfOptionKey(edit), edit.value]))
    if (changedEdits.length) output = await saveDocx(linked, linked.blocks.filter(block => !block.hidden).map(block => ({ kind: 'original' as const, docxIndex: block.docxIndex! })), {
      ...options,
      sectionHf: changedEdits.filter(edit => edit.section !== trailingSection).map(edit => ({ lastBlockIndex: linkedSections[allSections.indexOf(edit.section)]!.lastBlockIndex, kind: edit.part, variant: edit.variant, hf: edit.value })),
    })
    output = await preserveHfNamespaces(output, changedEdits)
    const edited = await loadDocxZip(output), relationships = await parseRels(edited, 'word/_rels/document.xml.rels')
    const checkedSections = readSections(await parseDocx(output)), inspectEdited = createHfRelationshipInspector(edited)
    if (checkedSections.length !== allSections.length) fail('hf_section_write_invalid')
    for (const edit of afterLinkEdits) {
      const section = checkedSections[allSections.indexOf(edit.section)]!
      const id = (edit.part === 'header' ? section.headerRefs : section.footerRefs)[edit.variant]
      const target = id ? relationships.get(id)?.target : undefined, path = target ? resolvePartPath('word', target) : null
      if (!path || (await inspectEdited(path)).reason) fail('hf_link_write_not_applied')
    }
    const core = sourceZip.file('docProps/core.xml')
    if (core) edited.file('docProps/core.xml', await core.async('uint8array'))
    output = await edited.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
  }
  if (hfEdits.size) {
    // 独立回读：引用已落到尾节、部件文本与引擎落盘规则一致（域以标记回读）。
    const reopened = await parseDocx(output)
    for (const edit of hfEdits.values()) {
      const reopenedSection = readSections(reopened)[allSections.indexOf(edit.section)]!
      const rId = (edit.part === 'header' ? reopenedSection.headerRefs : reopenedSection.footerRefs)[edit.variant]
      const info = rId ? reopened.hfParts?.[rId] : undefined
      if (!info || editableHfText(info) !== expectedHfText(edit)) fail('hf_write_not_applied')
    }
  }
  if (noteOperations.length && notesPlan) {
    const outputZip = await loadDocxZip(output)
    for (const [kind, expected] of Object.entries(notesPlan.parts)) {
      if (await outputZip.file(`word/${kind}s.xml`)?.async('string') !== expected) fail('note_write_not_applied')
    }
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const [identity, expectedRuns] of [...notesPlan.blocks, ...finalParagraphs]) {
      const state = states.get(identity)!, index = finalBlocks.indexOf(state.saved)
      const actual = reread[index]?.runs
      const references = (runs: Run[]) => runs.flatMap(run => run.noteRef ? [run.noteRef] : [])
      if (!actual || JSON.stringify(references(actual)) !== JSON.stringify(references(expectedRuns))) fail('note_reference_write_not_applied')
    }
  }
  if (operations.some(item => item.nested)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.nested) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (state.saved.kind !== 'xml' || reread[index]?.originalXml !== state.saved.xml) fail('nested_write_not_applied')
      verifyNestedCellModel(reread[index]?.table, item.nested.target, item.nested.paragraphs)
    }
  }
  if (operations.some(item => item.tableAltText)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableAltText) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_alt_text_write_not_applied')
      verifyTableAltTextResult(reread[index], item.tableAltText)
    }
  }
  if (operations.some(item => item.tableCellWrap)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellWrap) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_wrap_write_not_applied')
      verifyTableCellWrapResult(reread[index], item.tableCellWrap)
    }
  }
  if (operations.some(item => item.tableAlignment)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableAlignment) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_alignment_write_not_applied')
      verifyTableAlignmentResult(reread[index], item.tableAlignment)
    }
  }
  if (operations.some(item => item.tableRowBreaks)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableRowBreaks) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_row_breaks_write_not_applied')
      verifyTableRowBreakResult(reread[index], item.tableRowBreaks)
    }
  }
  if (operations.some(item => item.tableCellMarginOverrides)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellMarginOverrides) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_margin_overrides_write_not_applied')
      verifyTableCellMarginOverridesResult(reread[index], item.tableCellMarginOverrides)
    }
  }
  if (operations.some(item => item.tableCellMargins)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellMargins) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_margins_write_not_applied')
      verifyTableCellMarginsResult(reread[index], item.tableCellMargins)
    }
  }
  if (operations.some(item => item.tableCellAlignment)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellAlignment) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_alignment_write_not_applied')
      verifyTableCellAlignmentResult(reread[index], item.tableCellAlignment)
    }
  }
  if (operations.some(item => item.tableCellTextDirection)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellTextDirection) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_text_direction_write_not_applied')
      verifyTableCellTextDirectionResult(reread[index], item.tableCellTextDirection)
    }
  }
  if (operations.some(item => item.tableAutoFit)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableAutoFit) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_autofit_write_not_applied')
      verifyTableAutoFitResult(reread[index], item.tableAutoFit)
    }
  }
  if (operations.some(item => item.tableRowHeights)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableRowHeights) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_row_height_write_not_applied')
      verifyTableRowHeightResult(reread[index], item.tableRowHeights)
    }
  }
  if (operations.some(item => item.tableColumnWidths)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableColumnWidths) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_column_width_write_not_applied')
      verifyTableColumnWidthResult(reread[index], item.tableColumnWidths)
    }
  }
  if (operations.some(item => item.tableCellShape)) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const item of operations) if (item.tableCellShape) {
      const state = states.get(blockId(item.block))!, index = finalBlocks.indexOf(state.saved)
      if (!reread[index]) fail('table_cell_shape_write_not_applied')
      verifyTableCellShapeResult(reread[index], item.tableCellShape)
    }
  }
  if(operations.some(item=>item.op.kind==='setTableRepeatHeaders')){
    const reread=(await parseDocx(output)).blocks.filter(block=>!block.hidden)
    for(const item of operations)if(item.op.kind==='setTableRepeatHeaders'){
      const state=states.get(blockId(item.block))!,index=finalBlocks.indexOf(state.saved)
      const actual=reread[index]?.table?.repeatHeaderRows
      if(!actual||JSON.stringify(actual)!==JSON.stringify(item.op.headers))fail('table_repeat_headers_write_not_applied')
    }
  }
  // 标记补丁不触碰 metadata 或其他部件；保留段落补丁及仅 titlePg 的保存语义。
  if ((operations.length || revisionGroups.size) && operations.every(item => item.tableAltText || item.tableCellWrap || item.tableAlignment || item.tableRowBreaks || item.tableCellMarginOverrides || item.tableCellMargins || item.tableCellAlignment || item.tableCellTextDirection || item.tableAutoFit || item.tableRowHeights || item.tableColumnWidths || item.tableCellShape || item.op.kind === 'setTableRepeatHeaders' || item.op.kind === 'setParagraphStyle' || item.op.kind === 'setParagraphShading' || item.op.kind === 'setCellShading' || item.op.kind === 'setTableCellBorders' || item.op.kind === 'setParagraphBorders' || item.op.kind === 'setParagraphPageBreakBefore'
    || item.op.kind === 'setSectionLayout' && Object.keys(item.sectionValues ?? {}).every(key => ['titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'].includes(key)))) {
    const core = sourceZip.file('docProps/core.xml')
    if (core) {
      const outputZip = await loadDocxZip(output)
      outputZip.file('docProps/core.xml', await core.async('uint8array'))
      output = await outputZip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
    }
  }
  if (operations.some(item => item.sectionBreak || (item.section && item.section !== trailingSection))) {
    // 独立回读：节数随分节符增加，被改的非尾节设置与起始方式已落盘。
    const reread = readSections(await parseDocx(output))
    if (reread.length !== allSections.length + brokenSections.size) fail('section_write_not_applied')
  }
  if (operations.some(item => item.op.kind === 'replaceCellText' || item.op.kind === 'setCellShading' || item.op.kind === 'setTableCellBorders' || item.tableStructure)) {
    const reopened = await parseDocx(output)
    for (const state of states.values()) {
      const shaded = operations.some(item => item.block === state.block && (item.op.kind === 'setCellShading' || item.op.kind === 'setTableCellBorders'))
      if ((!state.cellValues.size && !state.tableStructure && !shaded) || state.saved.kind !== 'xml') continue
      const xml = state.saved.xml
      const table = reopened.blocks.find(block => block.type === 'table' && block.originalXml === xml)?.table
      if (shaded && !table) fail('cell_shading_write_not_applied')
      if (state.tableStructure && (JSON.stringify(table?.rows.map(row => row.map(cell => cell.paras.join('\n')))) !== JSON.stringify(state.tableStructure.matrix)
        || JSON.stringify(table?.colWidthsTwips) !== JSON.stringify(state.tableStructure.widths))) fail('table_structure_write_not_applied')
      for (const cell of state.cellValues.values()) {
        if (table?.rows[cell.row]?.[cell.column]?.paras.join('\n') !== cell.text) fail('cell_write_not_applied')
      }
    }
  }
  const borderEdits = operations.filter(item => item.op.kind === 'setSectionLayout' && item.sectionValues && 'pageBorder' in item.sectionValues)
  if (borderEdits.length) {
    // 独立回读：每个被改的节，w:pgBorders 解析结果与请求逐项一致（固定引擎 readSections / readSectionSettings）。
    const reparsed = await parseDocx(output), reread = readSections(reparsed)
    if (reread.length !== allSections.length) fail('page_border_write_not_applied')
    for (const item of borderEdits) {
      const index = allSections.indexOf(item.section!)
      const actual = index === allSections.length - 1 ? readSectionSettings(reparsed) : reread[index]!.settings
      const expected = { ...sectionSettingsOf(item.section!), ...item.sectionValues } as SectionSettings
      if (JSON.stringify(normalizedPageBorder(actual, true)) !== JSON.stringify(normalizedPageBorder(expected))) fail('page_border_write_not_applied')
    }
  }
  if (watermark !== undefined) {
    try { assertDocxWatermarkWritten(await readDocxHeaderParts(sourceZip), await readDocxHeaderParts(await loadDocxZip(output)), watermark) }
    catch { fail('watermark_write_not_applied') }
  }
  if (pageColor !== undefined) {
    const outputZip = await loadDocxZip(output)
    try { assertDocxPageColorWritten(await outputZip.file('word/document.xml')?.async('string') ?? '', await outputZip.file('word/settings.xml')?.async('string') ?? '', pageColor) }
    catch { fail('page_color_write_not_applied') }
  }
  if (revisionGroups.size) {
    const reread = (await parseDocx(output)).blocks.filter(block => !block.hidden)
    for (const [identity, group] of revisionGroups) {
      const state = states.get(identity)!, index = finalBlocks.indexOf(state.saved)
      if (index < 0 || reread[index]?.originalXml !== group.xml) fail('revision_write_not_applied')
    }
  }
  await writeFile(request.output as string, output, {flag: 'wx'})
  process.stdout.write(JSON.stringify({ sourceSha256, sha256: hash(output), size: output.length }))
}
