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
  const matches = [...xml.matchAll(/<Relationship\b[^>]*(?:\/>|>[\s\S]*?<\/Relationship>)/g)]
  const match = matches.filter(item => new RegExp(`\\bId="${id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"`).test(item[0]))
  if (match.length !== 1) throw new Error('图表关系身份不唯一')
  return xml.replace(match[0]![0], '')
}

function removeAnchor(xml: string, relId: string): string {
  const anchors = [...xml.matchAll(/<xdr:(?:twoCellAnchor|oneCellAnchor|absoluteAnchor)\b[^>]*>[\s\S]*?<\/xdr:(?:twoCellAnchor|oneCellAnchor|absoluteAnchor)>/g)]
  const matching = anchors.filter(item => /<xdr:graphicFrame\b[\s\S]*?<c:chart\b[^>]*\br:id="([^"]+)"/.exec(item[0])?.[1] === relId)
  if (matching.length !== 1) throw new Error('图表锚点身份不唯一或不完整')
  return xml.replace(matching[0]![0], '')
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
  const drawingRelsXml = await source.readText(drawingRelsPath)
  const chartLinks = relationships(drawingRelsXml, drawingRelsPath).filter(link => link.type === CHART_REL && !link.external && targetPath(drawingPath, link.target) === operation.chartPath)
  if (chartLinks.length !== 1) throw new Error('图表不属于当前工作表或图表关系不唯一')
  const chartRelId = chartLinks[0]!.id
  const drawingXml = await source.readText(drawingPath)
  const graphicFrames = [...drawingXml.matchAll(/<xdr:graphicFrame\b[\s\S]*?<\/xdr:graphicFrame>/g)]
  if (graphicFrames.filter(item => item[0].includes(`r:id="${chartRelId}"`)).length !== 1) throw new Error('图表锚点身份不唯一')

  for (const rels of (await source.paths()).filter(path => path.endsWith('.rels'))) {
    const owner = rels === '_rels/.rels' ? '' : rels.replace(/(^|\/)\_rels\/([^/]+)\.rels$/, '$1$2')
    for (const link of relationships(await source.readText(rels), rels)) {
      if (owner && !link.external && targetPath(owner, link.target) === operation.chartPath && !(rels === drawingRelsPath && link.id === chartRelId))
        throw new Error('图表部件被其他关系共享')
    }
  }

  const drawingAfter = removeAnchor(drawingXml, chartRelId)
  const relsAfter = removeRelationship(drawingRelsXml, chartRelId)
  const contentTypes = await source.readText('[Content_Types].xml')
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
