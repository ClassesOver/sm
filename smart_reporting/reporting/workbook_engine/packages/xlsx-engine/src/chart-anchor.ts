/** 固定源 xlsx-drawing-edit.ts 的 anchor 分支；只改既有 chart graphicFrame 的 from/to。
 * oneCellAnchor 按源语义保留 ext（仅移动），absoluteAnchor 按源语义拒绝。
 */
import { SaxesParser } from 'saxes'
import { z } from 'zod'
import { readCharts } from './chart-read'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { relationships } from './sheet-removal-parts'
import { assemblePackage, assertOnlyTouchedEntriesChanged, createBufferEntrySource } from './zip'

const integer = z.number().int().safe()
const anchorSchema = z.object({
  fromRow: integer.min(0).max(1048575), fromColumn: integer.min(0).max(16383),
  toRow: integer.min(0).max(1048575), toColumn: integer.min(0).max(16383),
  fromRowOffset: integer, fromColumnOffset: integer, toRowOffset: integer, toColumnOffset: integer,
}).strict()
export const chartAnchorEditSchema = z.object({
  sheetName: z.string().min(1).max(31), chartPath: z.string().regex(/^xl\/charts\/chart[1-9]\d*\.xml$/),
  mode: z.enum(['move', 'resize']), before: anchorSchema,
  anchor: anchorSchema.refine(value => value.fromRowOffset >= 0 && value.fromColumnOffset >= 0 && value.toRowOffset >= 0 && value.toColumnOffset >= 0 &&
    (value.toRow > value.fromRow || value.toRow === value.fromRow && value.toRowOffset > value.fromRowOffset) &&
    (value.toColumn > value.fromColumn || value.toColumn === value.fromColumn && value.toColumnOffset > value.fromColumnOffset), '图表锚点范围无效'),
}).strict()
export type ChartAnchorEdit = z.infer<typeof chartAnchorEditSchema>

const XDR = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
const A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const relsPath = (part: string) => part.replace(/([^/]+)$/, '_rels/$1.rels')
function resolveTarget(owner: string, target: string): string {
  if (/[\\?#:%\x00-\x1f]/.test(target)) throw new Error('图表关系路径无效')
  const parts = target.startsWith('/') ? [] : owner.split('/').slice(0, -1)
  for (const part of target.split('/')) {
    if (part === '..') { if (!parts.pop()) throw new Error('图表关系越界') }
    else if (part && part !== '.') parts.push(part)
  }
  const path = parts.join('/')
  if (!path.startsWith('xl/')) throw new Error('图表关系越界')
  return path
}

function anchorSpan(xml: string, relId: string) {
  const parser = new SaxesParser({ xmlns: true }), stack: { uri: string; local: string }[] = []
  const matches: { start: number; end: number; prefix: string; kind: string }[] = []
  let anchor: { start: number; prefix: string; kind: string; frames: number; charts: number; targets: number; safe: boolean } | undefined
  parser.on('doctype', () => { throw new Error('图表锚点不支持DOCTYPE') })
  parser.on('opentag', tag => {
    stack.push({ uri: tag.uri, local: tag.local })
    const depth = stack.length
    if (depth === 1 && (tag.uri !== XDR || tag.local !== 'wsDr')) throw new Error('图表绘图根元素无效')
    if (depth === 2 && tag.uri === XDR && ['twoCellAnchor', 'oneCellAnchor', 'absoluteAnchor'].includes(tag.local))
      anchor = { start: xml.lastIndexOf('<', parser.position - 1), prefix: tag.prefix ? `${tag.prefix}:` : '', kind: tag.local, frames: 0, charts: 0, targets: 0, safe: true }
    if (!anchor) return
    if (depth === 3) {
      if (tag.uri !== XDR || !['from', 'to', 'pos', 'ext', 'graphicFrame', 'clientData'].includes(tag.local)) anchor.safe = false
      if (tag.uri === XDR && tag.local === 'graphicFrame') anchor.frames++
    }
    if (tag.uri === C && tag.local === 'chart') {
      anchor.charts++
      if (Object.values(tag.attributes).some(attr => attr.uri === R && attr.local === 'id' && attr.value === relId)) {
        anchor.targets++
        const expected = [[XDR, 'graphicFrame'], [A, 'graphic'], [A, 'graphicData'], [C, 'chart']]
        if (depth !== 6 || !expected.every(([uri, local], index) => stack[index + 2]?.uri === uri && stack[index + 2]?.local === local)) anchor.safe = false
      }
    }
  })
  parser.on('closetag', () => {
    if (stack.length === 2 && anchor) {
      if (anchor.targets) {
        if (!anchor.safe || anchor.frames !== 1 || anchor.charts !== 1 || anchor.targets !== 1) throw new Error('图表锚点身份不完整或包含其他对象')
        matches.push({ ...anchor, end: parser.position })
      }
      anchor = undefined
    }
    stack.pop()
  })
  parser.write(xml).close()
  if (matches.length !== 1) throw new Error('图表锚点身份不唯一或不完整')
  return matches[0]!
}

/** 移植源 applyOneEdit 的 from/to 替换，保留 graphicFrame、前缀及所有非目标字节。 */
function patchAnchor(xml: string, relId: string, edit: ChartAnchorEdit) {
  const span = anchorSpan(xml, relId), p = span.prefix, pre = p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (span.kind === 'absoluteAnchor') throw new Error('源 writer 不支持绝对锚点图表移动或缩放')
  if (span.kind === 'oneCellAnchor' && edit.mode === 'resize') throw new Error('源 writer 仅支持单单元格锚点图表移动，不支持缩放')
  let patched = xml.slice(span.start, span.end)
  for (const side of span.kind === 'twoCellAnchor' ? ['from', 'to'] as const : ['from'] as const) {
    const value = edit.anchor
    const marker = `<${p}${side}><${p}col>${side === 'from' ? value.fromColumn : value.toColumn}</${p}col>` +
      `<${p}colOff>${side === 'from' ? value.fromColumnOffset : value.toColumnOffset}</${p}colOff>` +
      `<${p}row>${side === 'from' ? value.fromRow : value.toRow}</${p}row>` +
      `<${p}rowOff>${side === 'from' ? value.fromRowOffset : value.toRowOffset}</${p}rowOff></${p}${side}>`
    const pattern = new RegExp(`<${pre}${side}>[\\s\\S]*?</${pre}${side}>`, 'g')
    if ([...patched.matchAll(pattern)].length !== 1) throw new Error('图表锚点标记不唯一或尚不支持该命名空间布局')
    patched = patched.replace(pattern, () => marker)
  }
  return xml.slice(0, span.start) + patched + xml.slice(span.end)
}

export async function applyChartAnchors(bytes: Uint8Array, raw: readonly ChartAnchorEdit[]): Promise<Uint8Array> {
  const edits = z.array(chartAnchorEditSchema).min(1).max(100).parse(raw)
  if (new Set(edits.map(edit => edit.chartPath)).size !== edits.length) throw new Error('图表锚点目标重复')
  const source = await createBufferEntrySource(bytes), replaced = new Map<string, string>()
  const sheets = parseSheetElements(await source.readText('xl/workbook.xml'))
  for (const edit of edits) {
    const sheet = sheets.find(item => item.name === edit.sheetName)
    if (!sheet) throw new Error('图表工作表已变化')
    const worksheetPath = await resolveWorksheetPath(source, sheet.relationshipId!)
    const sheetLinks = relationships(await source.readText(relsPath(worksheetPath)), relsPath(worksheetPath))
      .filter(link => link.type === `${R}/drawing` && !link.external)
    if (sheetLinks.length !== 1) throw new Error('工作表绘图关系不唯一')
    const drawingPath = resolveTarget(worksheetPath, sheetLinks[0]!.target), drawingRels = relsPath(drawingPath)
    const links = relationships(await source.readText(drawingRels), drawingRels)
      .filter(link => link.type === `${R}/chart` && !link.external && resolveTarget(drawingPath, link.target) === edit.chartPath)
    if (links.length !== 1) throw new Error('图表不属于当前工作表或关系不唯一')
    const xml = replaced.get(drawingPath) ?? await source.readText(drawingPath, { preservePrefixes: true })
    // 先验证实际关系与锚点能力，绝对锚点即使 before 失配也给出具体限制。
    const next = patchAnchor(xml, links[0]!.id, edit)
    const charts = (await readCharts(bytes, worksheetPath)).filter(chart => chart.chartPath === edit.chartPath)
    if (charts.length !== 1 || Object.entries(edit.before).some(([key, value]) => value !== (charts[0]!.anchor[key as keyof typeof edit.before] ?? 0)))
      throw new Error('图表锚点身份已变化，请重新操作')
    replaced.set(drawingPath, next)
  }
  const mutation = await assemblePackage(bytes, { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [...replaced.keys()] })
  assertOnlyTouchedEntriesChanged(mutation)
  return mutation.buffer
}
