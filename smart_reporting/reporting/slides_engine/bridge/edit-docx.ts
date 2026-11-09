// GenOffice Apache-2.0: 仅从原文件解析锚点，不接受客户端 OOXML 或资源路径。
import { MAX_TABLE_STEPS, TABLE_STRUCTURE_KINDS, editTableStructure, editTableStructureSteps, tableStructureAvailability, type TableStructureKind } from './docx-table-structure.ts'
import { createHash } from 'node:crypto'
import { loadDocxZip } from '../packages/docx-engine/src/zip-load.ts'
import { attrsOf, findChild, childrenOf, xmlParser, escapeXmlAttr } from '../packages/docx-engine/src/xml-utils.ts'
import { resolve } from 'node:path'
import { readFile, writeFile, realpath, stat } from 'node:fs/promises'
import { PAGE_MARK, parseDocx, saveDocx, patchTableCellTexts, mergePPrFormat, readSections, readSectionSettings, type Block, type GeneratedBlock, type HfParagraph, type HeaderFooter, type HfPartInfo, type Run, type TableModel, type SaveBlock, type ParaFormat, type SectionSettings } from '@genoffice/docx-engine'
import { generateTableModelXml, mergeCellParaFormat, pPrWithIndLeft, pPrWithNumPr, PPR_CHILD_ORDER, RPR_CHILD_ORDER, splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate.ts'

type ObjectValue = Record<string, unknown>
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
function style(value: unknown): Partial<Run> {
  const spec = object(value)
  keys(spec, ['bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color', 'highlight'])
  if (!Object.keys(spec).length) fail('style_invalid')
  const result: Partial<Run> = {}
  for (const name of ['bold', 'italic', 'underline', 'strike'] as const) {
    if (spec[name] !== undefined) {
      if (typeof spec[name] !== 'boolean') fail('style_invalid')
      result[name] = spec[name] as boolean
    }
  }
  if (spec.fontSize !== undefined) {
    if (typeof spec.fontSize !== 'number' || !Number.isFinite(spec.fontSize) || spec.fontSize < 1 || spec.fontSize > 200 || !Number.isInteger(spec.fontSize * 2)) fail('style_invalid')
    result.sizeHalfPoints = (spec.fontSize as number) * 2
  }
  if (spec.fontFamily !== undefined) {
    if (typeof spec.fontFamily !== 'string' || !spec.fontFamily.trim() || spec.fontFamily.length > 128 || /[\x00-\x1f]/.test(spec.fontFamily)) fail('style_invalid')
    result.font = spec.fontFamily as string
  }
  if (spec.color !== undefined) {
    if (typeof spec.color !== 'string' || !/^[a-f\d]{6}$/i.test(spec.color)) fail('style_invalid')
    result.color = (spec.color as string).toUpperCase()
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
  part: HeaderFooterPart; variant: HfVariant; value: HeaderFooter; pageNumber: boolean; lines: string[]
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
  if (target.startsWith('/')) return target.slice(1)
  const parts = base.split('/')
  for (const segment of target.split('/')) {
    if (segment === '..') parts.pop()
    else if (segment !== '.') parts.push(segment)
  }
  return parts.join('/')
}

const requestBytes = await readFile(process.argv[2] ?? fail('request_missing'))
if (requestBytes.length > 12 * 1024 * 1024) fail('operations_too_large')
const request = object(JSON.parse(requestBytes.toString('utf8')))
keys(request, ['kind', 'input', 'output', 'operations'])
if (!['inspect', 'patch'].includes(request.kind as string) || typeof request.input !== 'string') fail('request_invalid')
const bytes = new Uint8Array(await readFile(request.input as string))
if (!bytes.length || bytes.length > 24 * 1024 * 1024) fail('content_invalid_or_too_large')
const sourceSha256 = hash(bytes)
const parsed = await parseDocx(bytes)
const blocks = parsed.blocks.filter(block => !block.hidden)
const sourceZip = await loadDocxZip(bytes)
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
const blockId = (block: Block) => hash(`${sourceSha256}:block:${block.docxIndex}`)
const cellId = (block: Block, row: number, column: number) => hash(`${sourceSha256}:cell:${block.docxIndex}:${row}:${column}`)
const trailingSection = readSections(parsed).at(-1)!
const sectionId = hash(`${sourceSha256}:section:${trailingSection.lastBlockIndex}`)
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
const indexed = new Map(blocks.map(block => [blockId(block), block]))
const model = () => ({ sourceSha256, modelSource: 'genoffice-docx-engine:f8c17004fb730df11f0f743164ffd8b4281bb38c', desktopVerified: false,
  capabilities: { paragraphs: true, basicStyles: true, simpleTableText: true, simpleTableStructure: true, replaceImage: false, headerFooter: true },
  sections: [{ sectionId, expectedSectionSha256: hash(trailingSection.sectPrXml), settings: readSectionSettings(parsed) }],
  headersFooters: {
    titlePg: trailingSection.titlePg,
    evenAndOddHeaders: parsed.evenAndOddHeaders ?? false,
    pageNumberFmt: trailingSection.pageNumberFmt ?? null,
    pageNumberStart: trailingSection.pageNumberStart ?? null,
    parts: Object.fromEntries(hfPartAnchors),
  },
  blocks: blocks.map(block => ({ blockId: blockId(block), expectedObjectSha256: hash(block.originalXml ?? ''),
    type: block.type, text: block.runs?.map(run => run.text).join('') ?? block.previewText ?? '', links: linksOf(block),
    ...(block.list ? { list: block.list } : {}),
    paragraphStyleEditable: paragraphStyleEditable(block),
    editable: editableParagraph(block), readOnlyReason: editableParagraph(block) ? null : 'docx_object_unsupported',
    deletable: editableParagraph(block) || coverMarkerParagraph(block),
    ...(block.type === 'table' ? { ...tableStructureAvailability(block), rowCount: block.table?.rows.length ?? 0, columnCount: block.table?.rows[0]?.length ?? 0, cells: cellXmls(block).map((row, r) => row.map((xml, c) => ({
      cellId: cellId(block, r, c), expectedObjectSha256: hash(xml), row: r, column: c,
      text: block.table?.rows[r]?.[c]?.paras.join('\n') ?? '', editable: editableTable(block) && editableCell(xml),
      readOnlyReason: editableTable(block) && editableCell(xml) ? null : 'docx_cell_unsupported',
    }))) } : {}),
  })) })

if (request.kind === 'inspect') {
  process.stdout.write(JSON.stringify(model()))
} else {
  if (typeof request.output !== 'string' || !Array.isArray(request.operations) || request.operations.length > 500) fail('operation_invalid')
  const sourcePath = await realpath(request.input as string)
  const outputPath = await realpath(request.output as string).catch(() => resolve(request.output as string))
  const sourceIdentity = await stat(sourcePath)
  const outputIdentity = await stat(outputPath).catch(() => undefined)
  if (sourcePath === outputPath || (outputIdentity && sourceIdentity.ino === outputIdentity.ino && sourceIdentity.dev === outputIdentity.dev)) fail('output_overwrites_source')
  // 页眉/页脚部件编辑：节锚定、不落在正文 block 上，先于 block 操作单独校验收集；
  // 同一 (part, variant) 一批只允许一次编辑。
  const hfEdits = new Map<string, HeaderFooterEdit>()
  for (const raw of request.operations) {
    const op = object(raw)
    if (op.kind !== 'setHeaderFooter') continue
    keys(op, ['kind', 'sectionId', 'expectedSectionSha256', 'part', 'variant', 'expectedPartSha256', 'text', 'pageNumber', 'align', 'titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'])
    if (op.sectionId !== sectionId || op.expectedSectionSha256 !== hash(trailingSection.sectPrXml)) fail('section_anchor_invalid')
    if (op.part !== 'header' && op.part !== 'footer') fail('hf_part_invalid')
    if (!HF_VARIANTS.includes(op.variant as HfVariant)) fail('hf_part_invalid')
    if (typeof op.pageNumber !== 'boolean') fail('hf_part_invalid')
    if (op.align !== undefined && !['left', 'center', 'right'].includes(op.align as string)) fail('hf_part_invalid')
    for (const key of ['titlePg', 'evenAndOddHeaders'] as const) {
      if (op[key] !== undefined && typeof op[key] !== 'boolean') fail('hf_part_invalid')
    }
    const fmt = op.pageNumberFmt
    if (fmt !== undefined && fmt !== null && (typeof fmt !== 'string' || !PAGE_NUMBER_FORMATS.has(fmt))) fail('page_number_format_invalid')
    const start = op.pageNumberStart
    if (start !== undefined && start !== null && (typeof start !== 'number' || !Number.isInteger(start) || start < 0 || start > 999999)) fail('page_number_format_invalid')
    const found = await trailingHfPart(op.part as HeaderFooterPart, op.variant as HfVariant)
    if (hash(found.xml) !== op.expectedPartSha256) fail('hf_anchor_invalid')
    const value = text(op.text)
    const key = `${op.part}:${op.variant}`
    if (hfEdits.has(key)) fail('hf_batch_conflict')
    hfEdits.set(key, {
      part: op.part as HeaderFooterPart, variant: op.variant as HfVariant,
      value: hfValueFromText(found.info, value, op.pageNumber as boolean, op.align as 'left' | 'center' | 'right' | undefined),
      pageNumber: op.pageNumber as boolean, lines: value.split('\n'),
      ...(op.titlePg !== undefined ? { titlePg: op.titlePg as boolean } : {}),
      ...(op.evenAndOddHeaders !== undefined ? { evenAndOddHeaders: op.evenAndOddHeaders as boolean } : {}),
      ...(fmt !== undefined ? { pageNumberFmt: fmt as string | null } : {}),
      ...(start !== undefined ? { pageNumberStart: start as number | null } : {}),
    })
  }
  const blockOperations = request.operations.filter(raw => object(raw).kind !== 'setHeaderFooter')
  // 先对同一来源快照整批校验；应用时按请求顺序组合，expectedObjectSha256 不随前序修改改变。
  const operations = blockOperations.map(raw => {
    const op = object(raw)
    if (op.kind === 'setSectionLayout') {
      keys(op, ['kind', 'sectionId', 'expectedSectionSha256', 'values'])
      if (op.sectionId !== sectionId || op.expectedSectionSha256 !== hash(trailingSection.sectPrXml)) fail('section_anchor_invalid')
      const values = object(op.values)
      keys(values, ['orientation', 'pageWidth', 'pageHeight', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft', 'columns', 'headerDist', 'footerDist'])
      if (!Object.keys(values).length) fail('section_layout_invalid')
      if (values.orientation !== undefined && !['portrait', 'landscape'].includes(values.orientation as string)) fail('section_layout_invalid')
      for (const key of ['pageWidth', 'pageHeight'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 1440 || values[key] > 31680)) fail('section_layout_invalid')
      for (const key of ['marginTop', 'marginRight', 'marginBottom', 'marginLeft'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 0 || values[key] > 14400)) fail('section_layout_invalid')
      if (values.columns !== undefined && (typeof values.columns !== 'number' || !Number.isInteger(values.columns) || values.columns < 1 || values.columns > 3)) fail('section_layout_invalid')
      for (const key of ['headerDist', 'footerDist'] as const) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || values[key] < 0 || values[key] > 31680)) fail('section_layout_invalid')
      const current = readSectionSettings(parsed)
      if (Number(values.marginLeft ?? current.marginLeft) + Number(values.marginRight ?? current.marginRight) >= Number(values.pageWidth ?? current.pageWidth)
        || Number(values.marginTop ?? current.marginTop) + Number(values.marginBottom ?? current.marginBottom) >= Number(values.pageHeight ?? current.pageHeight)) fail('section_layout_invalid')
      return { op, sectionValues: values as Partial<SectionSettings> }
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
    if (op.kind === 'replaceCellText') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'cellId', 'text'])
      const rows = cellXmls(block)
      let found: { row: number; column: number; xml: string } | undefined
      rows.forEach((row, r) => row.forEach((xml, c) => { if (cellId(block, r, c) === op.cellId) found = { row: r, column: c, xml } }))
      if (!found || hash(found.xml) !== op.expectedObjectSha256) fail('anchor_invalid')
      if (!editableTable(block) || !editableCell(found.xml)) fail('cell_unsupported')
      return { op, block, cell: found, value: text(op.text) }
    }
    if (hash(block.originalXml ?? '') !== op.expectedObjectSha256) fail('anchor_invalid')
    if (op.kind === 'setParagraphStyle') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'styleId'])
      if (!paragraphStyleEditable(block)) fail('paragraph_style_unsupported')
      const target = sourceParagraphStyle(op.styleId)
      const sourceId = block.styleId ?? [...parsed.styles.values()].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceId) sourceParagraphStyle(sourceId)
      return { op, block, styleId: target.styleId }
    }
    if (op.kind === 'deleteParagraph' && coverMarkerParagraph(block)) {
      // 封面书签段只读但可整段删除（移除/替换已保存图库封面）。
      keys(op, ['kind', 'blockId', 'expectedObjectSha256'])
      return { op, block }
    }
    if (!editableParagraph(block)) fail('paragraph_unsupported')
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
    if (op.kind === 'setParagraphRightIndent') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'twips'])
      if (typeof op.twips !== 'number' || !Number.isInteger(op.twips) || op.twips < -14400 || op.twips > 14400) fail('right_indent_invalid')
      return { op, block }
    }
    if (op.kind === 'setParagraphSpacing') {
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'spaceBefore', 'spaceAfter', 'lineSpacing'].includes(key))) fail('paragraph_spacing_invalid')
      const fields = ['spaceBefore', 'spaceAfter', 'lineSpacing'].filter(key => op[key] !== undefined)
      if (!fields.length) fail('paragraph_spacing_invalid')
      for (const key of ['spaceBefore', 'spaceAfter'] as const) {
        if (op[key] !== undefined && (typeof op[key] !== 'number' || !Number.isFinite(op[key]) || !Number.isInteger(op[key]) || (op[key] as number) < 0 || (op[key] as number) > 14400)) fail('paragraph_spacing_invalid')
      }
      if (op.lineSpacing !== undefined && (typeof op.lineSpacing !== 'number' || ![1, 1.15, 1.5, 2, 2.5, 3].includes(op.lineSpacing))) fail('paragraph_spacing_invalid')
      return { op, block }
    }
    if (op.kind === 'setParagraphShading') {
      if (Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'fill', 'clear'].includes(key))) fail('paragraph_shading_invalid')
      if ((typeof op.fill !== 'string' && op.fill !== null) || (typeof op.fill === 'string' && !/^[0-9a-f]{6}$/.test(op.fill)) || typeof op.clear !== 'boolean') fail('paragraph_shading_invalid')
      return { op, block, shading: { fill: op.fill as string | null, clear: op.clear as boolean } }
    }
    if (op.kind === 'setParagraphBorders') {
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
  })
  for (const item of operations) if (item.styleId && operations.some(other => other.block === item.block && other.op.kind !== 'setParagraphStyle')) fail('paragraph_style_batch_conflict')
  // 底纹补丁与段落样式同规：同段同批次只允许底纹操作，不能与文字/格式/结构混存。
  for (const item of operations) if (item.shading && operations.some(other => other.block === item.block && other.op !== item.op)) fail('paragraph_shading_batch_conflict')
  // 段落边框补丁与底纹同规：同段同批次只允许一次边框操作。
  for (const item of operations) if (item.borders !== undefined && operations.some(other => other.block === item.block && other.op !== item.op)) fail('paragraph_borders_batch_conflict')
  // 段前分页补丁与底纹/边框同规：同段同批次只允许一次分页操作。锚定在该段前/后的
  // 新段插入（空白页 = 新空段 + 后续段分页）只放入 before/after，不改写该段 XML，可共存。
  const anchoredInsert = (kind: unknown) => kind === 'insertParagraph' || kind === 'insertParagraphImage' || kind === 'insertTable' || kind === 'insertCoverPage'
  // 封面恒在文档开头（固定源语义）：锚点必须是正文首个保留块，每批至多一个封面。
  const covers = operations.filter(item => item.op.kind === 'insertCoverPage')
  if (covers.length > 1) fail('cover_page_batch_conflict')
  for (const item of operations) if (item.pageBreakBefore !== undefined && operations.some(other => other.block === item.block && other.op !== item.op && !anchoredInsert(other.op.kind))) fail('paragraph_page_break_batch_conflict')
  const structuralTables = new Set<string>()
  for (const item of operations) if (item.tableStructure) {
    const id = blockId(item.block)
    if (structuralTables.has(id)) fail('table_structure_batch_conflict')
    structuralTables.add(id)
  }
  for (const item of operations) if (item.cell && structuralTables.has(blockId(item.block))) fail('table_structure_batch_conflict')
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
  // 引擎补建缺失 numbering.xml 时自带 1/2 两个模板定义。
  let nextNumId = Math.max(2, ...[...parsed.numbering.keys()].map(id => Number(id)).filter(Number.isSafeInteger)) + 1
  const newDefs: { numId: string; kind: 'bullet' | 'ordered' }[] = []
  let sectionValues: Partial<SectionSettings> | undefined
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
    if (item.sectionValues) { sectionValues = { ...sectionValues, ...item.sectionValues }; continue }
    const state = states.get(blockId(item.block))!
    if (state.deleted) fail('operation_after_delete')
    if (item.styleId) {
      state.styleId = item.styleId
    } else if (item.shading) {
      state.shading = item.shading
    } else if (item.borders !== undefined) {
      state.borders = item.borders
    } else if (item.pageBreakBefore !== undefined) {
      state.pageBreakBefore = item.pageBreakBefore
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
        block.runs = (block.runs.length ? block.runs : [{ text: '' }]).map(run => ({...run, ...item.formatting}))
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
          ...(values.lineSpacing !== undefined ? { lineSpacing: values.lineSpacing as number, lineRule: undefined, lineRawTwips: undefined } : {}),
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
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: paragraphStyleXml(original, state.styleId) }
  }
  for (const state of states.values()) if (state.shading) {
    const original = state.block.originalXml ?? fail('paragraph_shading_xml_invalid')
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: paragraphShadingXml(original, state.shading) }
  }
  for (const state of states.values()) if (state.pageBreakBefore !== undefined) {
    const original = state.block.originalXml ?? fail('paragraph_page_break_xml_invalid')
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: paragraphPageBreakBeforeXml(original, state.pageBreakBefore) }
  }
  for (const state of states.values()) if (state.borders !== undefined) {
    const original = state.block.originalXml ?? fail('paragraph_borders_xml_invalid')
    state.saved = { kind: 'xml', docxIndex: state.block.docxIndex!, xml: paragraphBordersXml(original, state.borders) }
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
  const hfOptions = Object.fromEntries([...hfEdits.values()].map(edit => [hfOptionKey(edit), edit.value])) as Partial<Record<'header' | 'footer' | 'headerFirst' | 'footerFirst' | 'headerEven' | 'footerEven', HeaderFooter>>
  let output = await saveDocx(parsed, finalBlocks, {
    ...(newDefs.length ? { numbering: { newDefs } } : {}),
    ...(sectionValues ? { section: { ...readSectionSettings(parsed), ...sectionValues } } : {}),
    ...hfOptions,
    ...(hfTitlePg !== undefined ? { titlePg: hfTitlePg } : {}),
    ...(hfEvenOdd !== undefined ? { evenAndOddHeaders: hfEvenOdd } : {}),
    ...(pgNumType ? { pgNumType } : {}),
  })
  if (hfEdits.size) {
    // 独立回读：引用已落到尾节、部件文本与引擎落盘规则一致（域以标记回读）。
    const reopened = await parseDocx(output)
    const reopenedSection = readSections(reopened).at(-1)!
    for (const edit of hfEdits.values()) {
      const rId = (edit.part === 'header' ? reopenedSection.headerRefs : reopenedSection.footerRefs)[edit.variant]
      const info = rId ? reopened.hfParts?.[rId] : undefined
      if (!info || editableHfText(info) !== expectedHfText(edit)) fail('hf_write_not_applied')
    }
  }
  // A pStyle/shading/borders/page-break-only patch does not touch metadata or any other package entry.
  if (operations.length && operations.every(item => item.op.kind === 'setParagraphStyle' || item.op.kind === 'setParagraphShading' || item.op.kind === 'setParagraphBorders' || item.op.kind === 'setParagraphPageBreakBefore')) {
    const core = sourceZip.file('docProps/core.xml')
    if (core) {
      const outputZip = await loadDocxZip(output)
      outputZip.file('docProps/core.xml', await core.async('uint8array'))
      output = await outputZip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
    }
  }
  if (operations.some(item => item.op.kind === 'replaceCellText' || item.tableStructure)) {
    const reopened = await parseDocx(output)
    for (const state of states.values()) {
      if ((!state.cellValues.size && !state.tableStructure) || state.saved.kind !== 'xml') continue
      const xml = state.saved.xml
      const table = reopened.blocks.find(block => block.type === 'table' && block.originalXml === xml)?.table
      if (state.tableStructure && (JSON.stringify(table?.rows.map(row => row.map(cell => cell.paras.join('\n')))) !== JSON.stringify(state.tableStructure.matrix)
        || JSON.stringify(table?.colWidthsTwips) !== JSON.stringify(state.tableStructure.widths))) fail('table_structure_write_not_applied')
      for (const cell of state.cellValues.values()) {
        if (table?.rows[cell.row]?.[cell.column]?.paras.join('\n') !== cell.text) fail('cell_write_not_applied')
      }
    }
  }
  await writeFile(request.output as string, output, {flag: 'wx'})
  process.stdout.write(JSON.stringify({ sourceSha256, sha256: hash(output), size: output.length }))
}
