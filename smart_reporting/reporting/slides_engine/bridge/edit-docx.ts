// GenOffice Apache-2.0: 仅从原文件解析锚点，不接受客户端 OOXML 或资源路径。
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
import { readFile, writeFile, realpath, stat } from 'node:fs/promises'
import { parseDocx, saveDocx, patchTableCellTexts, mergePPrFormat, readSections, readSectionSettings, type Block, type GeneratedBlock, type Run, type SaveBlock, type ParaFormat, type SectionSettings } from '@genoffice/docx-engine'
import { mergeCellParaFormat, pPrWithIndLeft, pPrWithNumPr, PPR_CHILD_ORDER, splitXmlChildren, xmlSegments } from '../packages/docx-engine/src/generate.ts'

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
  keys(spec, ['bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color'])
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
  return result
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
const blockId = (block: Block) => hash(`${sourceSha256}:block:${block.docxIndex}`)
const cellId = (block: Block, row: number, column: number) => hash(`${sourceSha256}:cell:${block.docxIndex}:${row}:${column}`)
const trailingSection = readSections(parsed).at(-1)!
const sectionId = hash(`${sourceSha256}:section:${trailingSection.lastBlockIndex}`)
const indexed = new Map(blocks.map(block => [blockId(block), block]))
const model = () => ({ sourceSha256, modelSource: 'genoffice-docx-engine:f8c17004fb730df11f0f743164ffd8b4281bb38c', desktopVerified: false,
  capabilities: { paragraphs: true, basicStyles: true, simpleTableText: true, replaceImage: false },
  sections: [{ sectionId, expectedSectionSha256: hash(trailingSection.sectPrXml), settings: readSectionSettings(parsed) }],
  blocks: blocks.map(block => ({ blockId: blockId(block), expectedObjectSha256: hash(block.originalXml ?? ''),
    type: block.type, text: block.runs?.map(run => run.text).join('') ?? block.previewText ?? '', links: linksOf(block),
    ...(block.list ? { list: block.list } : {}),
    editable: editableParagraph(block), readOnlyReason: editableParagraph(block) ? null : 'docx_object_unsupported',
    ...(block.type === 'table' ? { cells: cellXmls(block).map((row, r) => row.map((xml, c) => ({
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
  // 先对同一来源快照整批校验；应用时按请求顺序组合，expectedObjectSha256 不随前序修改改变。
  const operations = request.operations.map(raw => {
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
    if (op.kind === 'replaceCellText') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'cellId', 'text'])
      const rows = cellXmls(block)
      let found: { row: number; column: number; xml: string } | undefined
      rows.forEach((row, r) => row.forEach((xml, c) => { if (cellId(block, r, c) === op.cellId) found = { row: r, column: c, xml } }))
      if (!found || hash(found.xml) !== op.expectedObjectSha256) fail('anchor_invalid')
      if (!editableTable(block) || !editableCell(found.xml)) fail('cell_unsupported')
      return { op, block, cell: found, value: text(op.text) }
    }
    if (!editableParagraph(block)) fail('paragraph_unsupported')
    if (hash(block.originalXml!) !== op.expectedObjectSha256) fail('anchor_invalid')
    if (op.kind === 'replaceParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'text'])
      const value = text(op.text)
      if (block.runs!.some(run => run.link) && value !== block.runs!.map(run => run.text).join('')) fail('link_text_replace_unsupported')
      return { op, block, value }
    }
    if (op.kind === 'insertParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'position', 'text'])
      if (op.position !== 'before' && op.position !== 'after') fail('operation_invalid')
      return { op, block, value: text(op.text) }
    }
    if (op.kind === 'formatParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256', 'style'])
      return { op, block, formatting: style(op.style) }
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
        if (op[key] !== undefined && (typeof op[key] !== 'number' || !Number.isInteger(op[key]) || ![0, 240].includes(op[key] as number))) fail('paragraph_spacing_invalid')
      }
      if (op.lineSpacing !== undefined && (typeof op.lineSpacing !== 'number' || ![1, 1.15, 1.5, 2, 2.5, 3].includes(op.lineSpacing))) fail('paragraph_spacing_invalid')
      return { op, block }
    }
    if (op.kind === 'deleteParagraph') {
      keys(op, ['kind', 'blockId', 'expectedObjectSha256'])
      return { op, block }
    }
    return fail('operation_unsupported')
  })
  const states = new Map(blocks.map(block => [blockId(block), {
    block, saved: {kind: 'original', docxIndex: block.docxIndex!} as SaveBlock,
    before: [] as SaveBlock[], after: [] as SaveBlock[], deleted: false,
    cellValues: new Map<string, {row: number; column: number; text: string}>(),
  }]))
  // 引擎补建缺失 numbering.xml 时自带 1/2 两个模板定义。
  let nextNumId = Math.max(2, ...[...parsed.numbering.keys()].map(id => Number(id)).filter(Number.isSafeInteger)) + 1
  const newDefs: { numId: string; kind: 'bullet' | 'ordered' }[] = []
  let sectionValues: Partial<SectionSettings> | undefined
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
    if (item.op.kind === 'insertParagraph') {
      state[item.op.position as 'before' | 'after'].push({ kind: 'generated', block: {type: 'paragraph', runs: [{text:item.value!}]} })
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
      if (item.op.kind === 'formatParagraph') {
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
  const finalBlocks: SaveBlock[] = []
  for (const state of states.values()) finalBlocks.push(...state.before, ...(state.deleted ? [] : [state.saved]), ...state.after)
  const output = await saveDocx(parsed, finalBlocks, {
    ...(newDefs.length ? { numbering: { newDefs } } : {}),
    ...(sectionValues ? { section: { ...readSectionSettings(parsed), ...sectionValues } } : {}),
  })
  if (operations.some(item => item.op.kind === 'replaceCellText')) {
    const reopened = await parseDocx(output)
    for (const state of states.values()) {
      if (!state.cellValues.size || state.saved.kind !== 'xml') continue
      const xml = state.saved.xml
      const table = reopened.blocks.find(block => block.type === 'table' && block.originalXml === xml)?.table
      for (const cell of state.cellValues.values()) {
        if (table?.rows[cell.row]?.[cell.column]?.paras.join('\n') !== cell.text) fail('cell_write_not_applied')
      }
    }
  }
  await writeFile(request.output as string, output, {flag: 'wx'})
  process.stdout.write(JSON.stringify({ sourceSha256, sha256: hash(output), size: output.length }))
}
