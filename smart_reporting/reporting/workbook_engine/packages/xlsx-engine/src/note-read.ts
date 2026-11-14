import { sha256Hex } from './sha256'
import { decodeXmlText, readXmlAttribute } from './xml'
import type { EntrySource } from './zip'

export const NOTE_LIMIT = 1000
export const NOTE_TEXT_LIMIT = 32767
export interface LegacyNote { row: number; column: number; author: string; text: string }
export interface SheetNotesModel {
  notes: LegacyNote[]
  sourceIdentity: string
  readOnlyReason?: string
}
export interface NoteSource extends SheetNotesModel {
  commentsPath?: string; commentsXml?: string; vmlPath?: string; vmlXml?: string
  commentXml: Map<string, string>; shapeXml: Map<string, string>; authors: string[]
}
export const noteKey = (row: number, column: number) => `${row}:${column}`
const tag = (name: string) => `(?:[\\w.-]+:)?${name}`
export function noteShapes(xml: string): string[] {
  return [...xml.matchAll(new RegExp(`<${tag('shape')}\\b[^>]*>[\\s\\S]*?<\\/${tag('shape')}>`, 'g'))].map(m => m[0])
}
export function shapeKey(xml: string): string | undefined {
  if (!/ObjectType=["']Note["']/.test(xml)) return undefined
  const row = xml.match(new RegExp(`<${tag('Row')}>(\\d+)<\\/${tag('Row')}>`))?.[1]
  const col = xml.match(new RegExp(`<${tag('Column')}>(\\d+)<\\/${tag('Column')}>`))?.[1]
  return row !== undefined && col !== undefined ? noteKey(Number(row), Number(col)) : undefined
}
function targetPath(sheetPath: string, target: string): string {
  if (target.includes('\\') || /[?#:%]/.test(target)) throw new Error('批注关系路径不安全')
  const parts = target.startsWith('/') ? [] : sheetPath.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') { if (!parts.pop()) throw new Error('批注关系越界') }
    else if (part && part !== '.') parts.push(part)
  }
  const path = parts.join('/')
  if (!path.startsWith('xl/')) throw new Error('批注关系越界')
  return path
}
export async function readSheetNotes(source: EntrySource, path: string, options: { allowPictures?: boolean; allowThreads?: boolean } = {}): Promise<NoteSource> {
  const result: NoteSource = { notes: [], sourceIdentity: '', commentXml: new Map(), shapeXml: new Map(), authors: [] }
  try {
    const sheet = await source.readText(path)
    const relsPath = path.replace(/\/([^/]+)$/, '/_rels/$1.rels')
    const rels = await source.has(relsPath) ? await source.readText(relsPath) : ''
    if (/<(?:\w+:)?sheetProtection\b/.test(sheet)) throw new Error('受保护工作表暂不支持批注编辑')
    if (!options.allowThreads && /threadedComment|person\b|persons\b/i.test(rels + sheet)) throw new Error('线程批注不属于 legacy notes，暂不支持编辑')
    const relationships = [...rels.matchAll(/<Relationship\b[^>]*\/?\s*>/g)].map(m => m[0])
    const notes = relationships.filter(r => readXmlAttribute(r, 'Type') === 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments')
    const vml = relationships.filter(r => readXmlAttribute(r, 'Type') === 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing')
    if (notes.length > 1 || vml.length > 1) throw new Error('批注关系不唯一')
    for (const r of [...notes, ...vml]) if (readXmlAttribute(r, 'TargetMode') || !readXmlAttribute(r, 'Target')) throw new Error('不支持外部批注关系')
    if (notes[0]) {
      result.commentsPath = targetPath(path, readXmlAttribute(notes[0], 'Target')!)
      result.commentsXml = await source.readText(result.commentsPath)
    }
    if (vml[0]) {
      result.vmlPath = targetPath(path, readXmlAttribute(vml[0], 'Target')!)
      result.vmlXml = await source.readText(result.vmlPath)
      const legacy = sheet.match(/<legacyDrawing\b[^>]*\/?\s*>/)?.[0]
      if (!legacy || readXmlAttribute(legacy, 'r:id') !== readXmlAttribute(vml[0], 'Id')) throw new Error('VML 与工作表关联不一致')
      if (!options.allowPictures && await source.has(result.vmlPath.replace(/\/([^/]+)$/, '/_rels/$1.rels'))) throw new Error('含图片或外部对象的 VML 暂不能保真编辑')
    }
    if (!!notes.length !== !!vml.length || /<legacyDrawing\b/.test(sheet) !== !!vml.length) throw new Error('批注与 VML 来源不完整')
    const xml = result.commentsXml ?? ''
    const drawing = result.vmlXml ?? ''
    if (xml.length + drawing.length + rels.length > 2 * 1024 * 1024) throw new Error('批注来源超出 2 MiB 预算')
    if (/<!|<extLst\b|<r\b|<phoneticPr\b|<rPh\b/.test(xml.replace(/<\?xml[^>]*>/, ''))) throw new Error('富文本或扩展批注暂不能保真编辑')
    result.authors = [...xml.matchAll(/<author>([\s\S]*?)<\/author>/g)].map(m => decodeXmlText(m[1]!))
    let total = 0
    for (const m of xml.matchAll(/<comment\b[^>]*>[\s\S]*?<\/comment>/g)) {
      const raw = m[0], address = readXmlAttribute(raw, 'ref') ?? ''
      const pos = address.match(/^([A-Z]{1,3})([1-9]\d{0,6})$/)
      if (!pos) throw new Error('批注单元格地址无效')
      const row = Number(pos[2]) - 1
      let column = 0
      for (const c of pos[1]!) column = column * 26 + c.charCodeAt(0) - 64
      column--
      const authorId = readXmlAttribute(raw, 'authorId') ?? ''
      if (!/^\d+$/.test(authorId) || !result.authors[Number(authorId)] && result.authors[Number(authorId)] !== '') throw new Error('批注作者身份无效')
      const body = raw.match(/<text>([\s\S]*?)<\/text>/)?.[1]
      if (body === undefined || !/^\s*(?:<t\b[^>]*>[\s\S]*?<\/t>\s*)+$/.test(body)) throw new Error('批注文本结构暂不能保真编辑')
      const text = [...body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map(t => decodeXmlText(t[1]!)).join('')
      total += text.length
      if (row > 1048575 || column > 16383 || text.length > NOTE_TEXT_LIMIT || result.notes.length >= NOTE_LIMIT || total > 1024 * 1024) throw new Error('批注超出单元格、数量或文本预算')
      const key = noteKey(row, column)
      if (result.commentXml.has(key)) throw new Error('同一单元格有重复批注')
      result.commentXml.set(key, raw)
      result.notes.push({ row, column, author: result.authors[Number(authorId)]!, text })
    }
    for (const shape of noteShapes(drawing)) {
      if (!/ObjectType=["']Note["']/.test(shape)) continue // Untargeted simple legacy objects remain byte-for-byte.
      const key = shapeKey(shape)
      if (!key || result.shapeXml.has(key) || !result.commentXml.has(key) || !options.allowPictures && /<(?:\w+:)?(?:imagedata|image|group)\b/i.test(shape)) throw new Error('混合图形或复杂 VML 暂不能保真编辑')
      result.shapeXml.set(key, shape)
    }
    if (/<(?:[\w.-]+:)?shape\b[^>]*\/>/.test(drawing)) throw new Error('自闭合 VML 对象暂不能保真编辑')
    if (result.commentXml.size !== result.shapeXml.size || /<(?:\w+:)?group\b/i.test(drawing) || !options.allowPictures && /<(?:\w+:)?(?:imagedata|image)\b/i.test(drawing)) throw new Error('批注与 VML 图形不匹配')
    if (drawing && !/<(?:[\w.-]+:)?shapetype\b[^>]*\bid="[^"]+"/.test(drawing)) throw new Error('VML 批注图形类型缺失')
    result.sourceIdentity = sha256Hex(JSON.stringify([path, rels, xml, drawing]))
  } catch (error) { result.readOnlyReason = (error as Error).message }
  return result
}
