import { SaxesParser } from 'saxes'
import { parseSheetElements, resolveWorksheetPath } from './workbook-read'
import { createBufferEntrySource, assemblePackage, type EntrySource, type MutationPlan } from './zip'
import { relationships, removePartOverrides } from './sheet-removal-parts'

export interface ChartDeletion {
  readonly sheetName: string
  readonly chartPath: string
}

const CHART_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart'
const DRAWING_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing'
const relsPath = (part: string) => part.replace(/([^/]+)$/, '_rels/$1.rels')

function targetPath(owner: string, target: string): string {
  if (/[\\?#:%\x00-\x1f]/.test(target)) throw new Error('图表关系路径无效')
  const segments = target.startsWith('/') ? [] : owner.split('/').slice(0, -1)
  for (const segment of target.split('/')) {
    if (segment === '..') { if (!segments.pop()) throw new Error('图表关系越界') }
    else if (segment && segment !== '.') segments.push(segment)
  }
  const path = segments.join('/')
  if (!path.startsWith('xl/')) throw new Error('图表关系越界')
  return path
}

function removeRelationship(xml: string, id: string): string {
  const parser = new SaxesParser({ xmlns: true }), spans: { start: number; end: number }[] = []
  let depth = 0, start = 0, removing = false
  parser.on('doctype', () => { throw new Error('图表关系不支持DOCTYPE') })
  parser.on('opentag', tag => {
    depth++
    if (depth !== 2 || tag.local !== 'Relationship' || !['http://schemas.openxmlformats.org/package/2006/relationships', 'http://purl.oclc.org/ooxml/package/relationships'].includes(tag.uri)) return
    removing = Object.values(tag.attributes).some(attr => !attr.uri && attr.local === 'Id' && attr.value === id)
    if (removing) start = xml.lastIndexOf('<', parser.position - 1)
  })
  parser.on('closetag', () => { if (depth === 2 && removing) { spans.push({ start, end: parser.position });removing = false }depth-- })
  parser.write(xml).close()
  if (spans.length !== 1) throw new Error('图表关系身份不唯一')
  return xml.slice(0, spans[0]!.start) + xml.slice(spans[0]!.end)
}

function removeAnchor(xml: string, relId: string): string {
  const xdr = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
  const drawing = 'http://schemas.openxmlformats.org/drawingml/2006/main'
  const chart = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
  const officeRel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
  const parser = new SaxesParser({ xmlns: true }), stack: { uri: string; local: string }[] = []
  const matches: { start: number; end: number }[] = []
  let anchor: { start: number; frames: number; charts: number; targets: number; safe: boolean } | undefined
  parser.on('doctype', () => { throw new Error('图表绘图不支持DOCTYPE') })
  parser.on('opentag', tag => {
    stack.push({ uri: tag.uri, local: tag.local })
    const depth = stack.length
    if (depth === 1 && (tag.uri !== xdr || tag.local !== 'wsDr')) throw new Error('图表绘图根元素无效')
    if (depth === 2 && tag.uri === xdr && ['twoCellAnchor', 'oneCellAnchor', 'absoluteAnchor'].includes(tag.local))
      anchor = { start: xml.lastIndexOf('<', parser.position - 1), frames: 0, charts: 0, targets: 0, safe: true }
    if (!anchor) return
    if (depth === 3) {
      if (tag.uri !== xdr || !['from', 'to', 'pos', 'ext', 'graphicFrame', 'clientData'].includes(tag.local)) anchor.safe = false
      if (tag.uri === xdr && tag.local === 'graphicFrame') anchor.frames++
    }
    if (tag.uri === chart && tag.local === 'chart') {
      anchor.charts++
      const expected = [[xdr, 'graphicFrame'], [drawing, 'graphic'], [drawing, 'graphicData'], [chart, 'chart']]
      const owned = depth === 6 && expected.every(([uri, local], index) => stack[index + 2]?.uri === uri && stack[index + 2]?.local === local)
      if (Object.values(tag.attributes).some(attr => attr.uri === officeRel && attr.local === 'id' && attr.value === relId)) {
        anchor.targets++
        if (!owned) anchor.safe = false
      }
    }
  })
  parser.on('closetag', () => {
    if (stack.length === 2 && anchor) {
      if (anchor.targets) {
        if (!anchor.safe || anchor.frames !== 1 || anchor.charts !== 1 || anchor.targets !== 1) throw new Error('图表锚点含其他对象或身份不完整')
        matches.push({ start: anchor.start, end: parser.position })
      }
      anchor = undefined
    }
    stack.pop()
  })
  parser.write(xml).close()
  if (matches.length !== 1) throw new Error('图表锚点身份不唯一或不完整')
  return xml.slice(0, matches[0]!.start) + xml.slice(matches[0]!.end)
}

async function deleteOne(source: EntrySource, operation: ChartDeletion) {
  if (!/^xl\/charts\/chart[1-9]\d*\.xml$/.test(operation.chartPath)) throw new Error('图表路径无效')
  const workbookXml = await source.readText('xl/workbook.xml')
  const sheet = parseSheetElements(workbookXml).find(item => item.name === operation.sheetName)
  if (!sheet) throw new Error(`找不到工作表 ${operation.sheetName}`)
  const worksheetPath = await resolveWorksheetPath(source, sheet.relationshipId!)
  const sheetLinks = await source.has(relsPath(worksheetPath))
    ? relationships(await source.readText(relsPath(worksheetPath)), relsPath(worksheetPath)) : []
  const drawingLinks = sheetLinks.filter(link => link.type === DRAWING_REL && !link.external)
  if (drawingLinks.length !== 1) throw new Error('当前工作表的绘图关系不唯一')
  const drawingPath = targetPath(worksheetPath, drawingLinks[0]!.target)
  if (!await source.has(drawingPath)) throw new Error('绘图部件缺失')
  const drawingRelsPath = relsPath(drawingPath)
  if (!await source.has(drawingRelsPath)) throw new Error('绘图关系缺失')
  const drawingRelsXml = await source.readText(drawingRelsPath, { preservePrefixes: true })
  const chartLinks = relationships(drawingRelsXml, drawingRelsPath).filter(link => link.type === CHART_REL && !link.external && targetPath(drawingPath, link.target) === operation.chartPath)
  if (chartLinks.length !== 1) throw new Error('图表不属于当前工作表或图表关系不唯一')
  const chartRelId = chartLinks[0]!.id
  const drawingXml = await source.readText(drawingPath, { preservePrefixes: true })

  for (const rels of (await source.paths()).filter(path => path.endsWith('.rels'))) {
    const owner = rels === '_rels/.rels' ? '' : rels.replace(/(^|\/)\_rels\/([^/]+)\.rels$/, '$1$2')
    for (const link of relationships(await source.readText(rels), rels)) {
      if (owner && !link.external && targetPath(owner, link.target) === operation.chartPath && !(rels === drawingRelsPath && link.id === chartRelId))
        throw new Error('图表部件被其他关系共享')
    }
  }

  const drawingAfter = removeAnchor(drawingXml, chartRelId)
  const relsAfter = removeRelationship(drawingRelsXml, chartRelId)
  const contentTypes = await source.readText('[Content_Types].xml', { preservePrefixes: true })
  return { drawingPath, drawingAfter, drawingRelsPath, relsAfter, chartRelId, contentTypes: removePartOverrides(contentTypes, new Set([operation.chartPath])), chartPath: operation.chartPath }
}

export async function applyChartDeletions(sourceBytes: Uint8Array, deletions: readonly ChartDeletion[]): Promise<Uint8Array> {
  if (!deletions.length || deletions.length > 100 || new Set(deletions.map(item => item.chartPath)).size !== deletions.length)
    throw new Error('图表删除请求无效')
  const source = await createBufferEntrySource(sourceBytes)
  const plans = []
  for (const deletion of deletions) plans.push(await deleteOne(source, deletion))
  const replaced = new Map<string, string>(), removedEntries = new Set<string>(), touchedEntries = new Set<string>()
  for (const plan of plans) {
    const currentDrawing = replaced.get(plan.drawingPath)
    const currentRels = replaced.get(plan.drawingRelsPath)
    replaced.set(plan.drawingPath, currentDrawing === undefined ? plan.drawingAfter : removeAnchor(currentDrawing, plan.chartRelId))
    replaced.set(plan.drawingRelsPath, currentRels === undefined ? plan.relsAfter : removeRelationship(currentRels, plan.chartRelId))
    const currentContentTypes = replaced.get('[Content_Types].xml')
    replaced.set('[Content_Types].xml', currentContentTypes === undefined
      ? plan.contentTypes
      : removePartOverrides(currentContentTypes, new Set([plan.chartPath])))
    removedEntries.add(plan.chartPath)
    for (const path of [plan.drawingPath, plan.drawingRelsPath, '[Content_Types].xml', plan.chartPath]) touchedEntries.add(path)
  }
  const mutation: MutationPlan = { replaced, added: new Map(), addedBinary: new Map(), removedEntries: [...removedEntries], addedEntries: [], touchedEntries: [...touchedEntries] }
  return (await assemblePackage(sourceBytes, mutation)).buffer
}
