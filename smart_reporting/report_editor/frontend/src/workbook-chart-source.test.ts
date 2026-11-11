import { expect, it } from 'vitest'
import { readWorkbookChartSource } from './workbook-chart-source'
const ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
const type = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
const rels = (entries: string) => `<Relationships xmlns="${ns}">${entries}</Relationships>`
const rel = (id: string, kind: string, target: string) => `<Relationship Id="${id}" Type="${type}${kind}" Target="${target}"/>`
const source = (parts: Record<string,string>) => ({ paths: async () => Object.keys(parts), has: async (path: string) => path in parts, readText: async (path: string) => { if (!(path in parts)) throw Error('missing'); return parts[path]! } })
it('reads actual chart owners through drawing relationships and retains unowned charts', async () => {
 const actual = await readWorkbookChartSource(source({
  'xl/worksheets/_rels/sheet1.xml.rels': rels(rel('d','drawing','../drawings/drawing1.xml')),
  'xl/drawings/drawing1.xml': '<drawing/>',
  'xl/drawings/_rels/drawing1.xml.rels': rels(rel('c','chart','../charts/chart1.xml')),
  'xl/charts/chart1.xml': '<owned/>', 'xl/charts/chart2.xml': '<orphan/>',
 }), [{name:'Other',path:'xl/worksheets/sheet1.xml'},{name:'Source',path:'xl/worksheets/sheet2.xml'}])
 expect(actual.sheets.get('Other')).toEqual([{path:'xl/charts/chart1.xml',xml:'<owned/>'}])
 expect(actual.sheets.get('Source')).toEqual([])
 expect(actual.unowned).toEqual([{path:'xl/charts/chart2.xml',xml:'<orphan/>'}])
})
it('refuses incomplete or external chart relationships instead of authorizing from an empty projection', async () => {
 for (const target of ['../charts/missing.xml','https://example.com/chart.xml']) {
  const parts={'xl/worksheets/_rels/sheet1.xml.rels':rels(rel('c','chart',target))}
  await expect(readWorkbookChartSource(source(parts),[{name:'Other',path:'xl/worksheets/sheet1.xml'}])).rejects.toThrow()
 }
})
it('uses relationship namespace identity and rejects malformed relationships', async () => {
 const sheet=[{name:'Other',path:'xl/worksheets/sheet1.xml'}]
 await expect(readWorkbookChartSource(source({'xl/worksheets/_rels/sheet1.xml.rels':'<Relationships>'}),sheet)).rejects.toThrow()
 const actual=await readWorkbookChartSource(source({'xl/worksheets/_rels/sheet1.xml.rels':`<Relationships xmlns="urn:foreign">${rel('c','chart','../charts/missing.xml')}</Relationships>`}),sheet)
 expect(actual.sheets.get('Other')).toEqual([])
})
