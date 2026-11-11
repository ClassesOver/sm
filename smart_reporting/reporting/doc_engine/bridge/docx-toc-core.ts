import { generateTocFieldXml, splitXmlChildren, type TocEntry } from '../packages/docx-engine/src/generate'
import type { parseDocx } from '../packages/docx-engine/src/parse'
import { scanBody, type BodyElement } from '../packages/docx-engine/src/scan'
import type { Block } from '../packages/docx-engine/src/types'

type Parsed = Awaited<ReturnType<typeof parseDocx>>
export type TocKind = 'insertToc' | 'updateToc'
export type TocOperation = { kind: 'insertToc'; blockId: string; expectedObjectSha256: string; position: 'before' | 'after' }
  | { kind: 'updateToc'; blockId: string; expectedObjectSha256: string }
export const isDocxTocOperation = (value: { kind?: unknown }): boolean => value.kind === 'insertToc' || value.kind === 'updateToc'
export function readDocxTocOperation(value: unknown): TocOperation {
  const op = value as Partial<TocOperation> | null
  if (!op || typeof op !== 'object' || !isDocxTocOperation(op) || !/^[a-f0-9]{64}$/.test(op.blockId ?? '')
    || !/^[a-f0-9]{64}$/.test(op.expectedObjectSha256 ?? '')
    || (op.kind === 'insertToc' && op.position !== 'before' && op.position !== 'after')
    || Object.keys(op).some(key => !['kind', 'blockId', 'expectedObjectSha256', ...(op.kind === 'insertToc' ? ['position'] : [])].includes(key))) throw new Error('docx_toc_operation')
  return op as TocOperation
}

/** Same heading categories as fixed GenOffice collectHeadings: heading nodes and headings inherited by paragraph/list styles. */
export function docxTocEntries(parsed: Parsed): TocEntry[] {
  return parsed.blocks.flatMap(block => {
    if (block.hidden || block.altChunk || /^toc(?:heading|[1-9])$/i.test(block.styleId ?? '') || !['heading', 'paragraph', 'listItem'].includes(block.type)) return []
    const style = block.styleId ? parsed.styles?.get(block.styleId) : undefined
    const level = block.type === 'heading' ? block.level ?? 1 : style?.headingOutlineOff ? undefined : style?.headingLevel
    const text = (block.runs ?? []).map(run => run.text).join('').replace(/[\t\r\n]+/g, ' ')
    return level && level <= 9 && text.trim() ? [{ level, text }] : []
  })
}

export const docxTocPageBreak = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
export function docxTocXml(entries: TocEntry[], keepPageBreak = false): string[] {
  return [...generateTocFieldXml(entries), ...(keepPageBreak ? [docxTocPageBreak] : [])]
}

const tocInstruction = /<w:instrText(?:\s[^>]*)?>\s*TOC(?=\s|\\|<)/i
const styleToc = /<w:pStyle\b[^>]*\bw:val\s*=\s*["']TOC[1-9]["']/i
const fieldEvents = /<w:fldChar\b[^>]*\bw:fldCharType\s*=\s*["'](begin|separate|end)["'][^>]*\/>|<w:(?:t|tab)(?:\s|\/>|>)/g
const pageBreak = /<w:br\s+w:type\s*=\s*["']page["']\s*\/>/g
const wordNamespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const inner = (xml: string) => xml.slice(xml.indexOf('>') + 1, xml.lastIndexOf('</'))
type ParagraphRange = { start: number; end: number }

/** Verify that parsed source identities name complete raw top-level paragraphs. */
export function docxTocSource(parsed: Parsed) {
  const xml = parsed.internal?.documentXml ?? ''
  const root = /^\uFEFF?\s*(?:<\?xml[^?]*\?>\s*)?<w:document\s[^>]*>/.exec(xml)?.[0]
  const safe = !!root && new RegExp('\\bxmlns:w=["\']' + wordNamespace + '["\']').test(root)
    && (xml.match(/\bxmlns:w\s*=/g)?.length ?? 0) === 1 && !/<!DOCTYPE/i.test(xml)
    && !parsed.protection?.enforced
  const paragraphs = new Map<number, ParagraphRange>(), wrapped = new Map<number, { index: number; range: ParagraphRange }[]>()
  const unavailable = { xml, elements: [] as BodyElement[], paragraphs, wrapped, safe: false }
  if (!safe) return unavailable
  let elements: BodyElement[]
  try { elements = scanBody(xml).elements } catch { return unavailable }
  const blocksByStart = new Map<number, Block>()
  let owner = 0
  for (const block of parsed.blocks) {
    const element = block.docxIndex == null ? undefined : parsed.extras?.elements?.[block.docxIndex]
    if (block.docxIndex == null || !element || block.hidden || block.altChunk) continue
    if (!block.sdtShell) { blocksByStart.set(element.start, block); continue }
    const shell = block.sdtShell
    while (elements[owner] && elements[owner]!.end <= element.start) owner++
    const container = elements[owner]
    if (container?.name !== 'w:sdt' || element.start < container.start || element.end > container.end
      || element.name !== 'w:p' || block.sdtShells?.length !== 1 || block.originalXml !== xml.slice(element.start, element.end)) continue
    const range = { start: element.start + shell.openXml.length, end: element.end - shell.closeXml.length }
    if (!/^<w:p(?:\s|>)/.test(xml.slice(range.start, range.end))) continue
    if (!wrapped.has(container.start)) wrapped.set(container.start, [])
    wrapped.get(container.start)!.push({ index: block.docxIndex, range })
  }
  for (const element of elements) {
    const block = blocksByStart.get(element.start)
    if (element.name === 'w:p' && block?.docxIndex != null && block.originalXml === xml.slice(element.start, element.end)) paragraphs.set(block.docxIndex, element)
  }
  return { xml, elements, paragraphs, wrapped, safe }
}

/** Accept only field paragraphs and known result runs; don't delete surrounding prose or opaque markup. */
function tocParagraphContent(xml: string): string | null {
  if (/<!|<\?|<w:sectPr\b|<w:\w+Change\b/.test(xml)) return null
  const safeRun = (run: string) => splitXmlChildren(inner(run)).every(part =>
    ['w:rPr', 'w:fldChar', 'w:instrText', 'w:t', 'w:tab', 'w:br'].includes(part.name))
  const parts = splitXmlChildren(inner(xml)).filter(part => part.name !== 'w:pPr')
  if (!parts.every(part => part.name === 'w:r' && safeRun(part.xml)
    || part.name === 'w:hyperlink' && /\bw:anchor\s*=/.test(part.xml)
    && splitXmlChildren(inner(part.xml)).every(run => run.name === 'w:r' && safeRun(run.xml)))) return null
  return parts.map(part => part.xml).join('')
}

export function docxTocRegion(parsed: Parsed, source = docxTocSource(parsed)) {
  const { xml, paragraphs, wrapped } = source
  let elements: ParagraphRange[] = source.elements
  let first = elements.findIndex(element => tocInstruction.test(xml.slice(element.start, element.end)))
  if (first < 0) return { reason: 'missing' as const }
  const byStart = new Map([...paragraphs].map(([index, element]) => [element.start, index]))
  const container = source.elements[first]!
  if (container.name === 'w:sdt') {
    const shell = xml.slice(container.start, container.end)
    if (!/<w:docPartGallery\s+w:val=["'](?:Table of Contents|TOC)["']\s*\/>/i.test(shell) || /<w:lock\b|<w:dataBinding\b/.test(shell)) return { reason: 'unsupported' as const }
    const children = wrapped.get(container.start) ?? []
    elements = children.map(({ index, range }) => { byStart.set(range.start, index); return range })
    first = elements.findIndex(element => tocInstruction.test(xml.slice(element.start, element.end)))
    if (first < 0) return { reason: 'unsupported' as const }
  }
  const indices: number[] = []
  let depth = 0, separated = false, ended = false, previousEnd = elements[first]!.start
  for (let i = first; i < elements.length; i++) {
    const element = elements[i]!, fragment = xml.slice(element.start, element.end)
    const index = byStart.get(element.start)
    const content = tocParagraphContent(fragment)
    if (index === undefined || xml.slice(previousEnd, element.start).trim() || content == null) break
    const events = [...content.matchAll(fieldEvents)]
    const fields = events.flatMap(event => event[1] ? [event[1]] : [])
    const instructions = [...fragment.matchAll(/<w:instrText(?:\s[^>]*)?>\s*([A-Za-z]+)[^<]*<\/w:instrText>/g)].map(match => match[1]?.toUpperCase())
    if (i === first ? fields[0] !== 'begin' || instructions[0] !== 'TOC' : instructions.includes('TOC')) break
    if (instructions.some(instruction => instruction !== 'TOC' && instruction !== 'PAGEREF')) break
    if (i > first && !styleToc.test(fragment) && (!fields.includes('end') || /<w:t(?:\s|>)/.test(fragment))) break
    let invalid = false
    for (const event of events) {
      const field = event[1]
      if (ended || !field && (depth === 0 || !separated)) { invalid = true; break }
      if (field === 'begin') {
        if (depth > 0 && !separated) { invalid = true; break }
        depth++
      } else if (field === 'separate' && depth === 1) {
        if (separated) { invalid = true; break }
        separated = true
      } else if (field === 'end') {
        depth--
        if (depth === 0) ended = true
      }
    }
    const breaks = [...fragment.matchAll(pageBreak)].length
    if (invalid || depth < 0 || /<w:br\b/.test(fragment) && (breaks !== 1 || depth !== 0)) break
    indices.push(index)
    if (depth === 0 && separated && ended) return { indices, start: elements[first]!.start, end: element.end, keepPageBreak: breaks === 1 }
    if (depth === 0) break
    previousEnd = element.end
  }
  return { reason: 'unsupported' as const }
}
