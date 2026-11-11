import { SaxesParser } from 'saxes'
import type { EntrySource } from '@sheets-web/xlsx-engine/zip'
import { resolveTablePartPath } from '@sheets-web/xlsx-engine/table-read'
import type { ChartRemovalSource } from './workbook-chart-sheet-removal'

export interface WorkbookChartSource {
  sheets: Map<string, ChartRemovalSource[]>
  unowned: ChartRemovalSource[]
}
const relationshipNamespaces = new Set(['http://schemas.openxmlformats.org/package/2006/relationships', 'http://purl.oclc.org/ooxml/package/relationships'])
const officeRelationship = /^(?:http:\/\/schemas\.openxmlformats\.org\/officeDocument\/2006\/relationships\/|http:\/\/purl\.oclc\.org\/ooxml\/officeDocument\/relationships\/)(drawing|chart)$/
const relsPath = (path: string) => path.replace(/([^/]+)$/, '_rels/$1.rels')

/** 从实际OPC关系读取图表所有者；图表未投影到渲染器不代表文件中不存在。 */
export async function readWorkbookChartSource(source: EntrySource, sheets: readonly { name: string; path: string }[]): Promise<WorkbookChartSource> {
  const result: WorkbookChartSource = { sheets: new Map(), unowned: [] }
  const owned = new Set<string>(), charts = new Map<string, ChartRemovalSource>()
  const readChart = async (path: string) => {
    if (!charts.has(path)) charts.set(path, { path, xml: await source.readText(path) })
    return charts.get(path)!
  }
  const related = async (path: string) => {
    if (!await source.has(relsPath(path))) return []
    const links: { kind: string; path: string }[] = []
    const parser = new SaxesParser({ xmlns: true })
    parser.on('opentag', node => {
      if (node.local !== 'Relationship' || !relationshipNamespaces.has(node.uri)) return
      const attribute = (name: string) => Object.values(node.attributes).find(attr => !attr.uri && attr.local === name)?.value
      const kind = officeRelationship.exec(attribute('Type') ?? '')?.[1]
      if (!kind) return
      const target = attribute('Target')
      const mode = attribute('TargetMode')
      if (!target || mode !== undefined && mode !== 'Internal') throw new Error('图表关系来源无法完整核对')
      links.push({ kind, path: resolveTablePartPath(path, target) })
    })
    parser.write(await source.readText(relsPath(path))).close()
    return links
  }
  for (const sheet of sheets) {
    const found = new Map<string, ChartRemovalSource>()
    for (const link of await related(sheet.path)) {
      if (link.kind === 'drawing') await source.readText(link.path)
      const links = link.kind === 'chart' ? [link] : await related(link.path)
      for (const chart of links.filter(item => item.kind === 'chart')) {
        found.set(chart.path, await readChart(chart.path)); owned.add(chart.path)
      }
    }
    result.sheets.set(sheet.name, [...found.values()])
  }
  for (const path of await source.paths()) if (/^xl\/charts\/chart[0-9]+\.xml$/.test(path) && !owned.has(path))
    result.unowned.push(await readChart(path))
  return result
}
