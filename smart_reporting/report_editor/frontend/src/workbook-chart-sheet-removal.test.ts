import { expect, it } from 'vitest'
const implementation = './workbook-chart-sheet-removal'
const chartNamespace = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
const chart = (formula: string) => `<chartSpace xmlns="${chartNamespace}"><chart><ser><val><numRef><f>${formula}</f></numRef></val></ser></chart></chartSpace>`
const book = () => {
  const sheet = (id: string, name: string) => ({ getSheetId: () => id, getSheetName: () => name })
  const source = sheet('source', 'Source'), other = sheet('other', 'Other')
  return { getId: () => 'book-id', getSheets: () => [source, other], getActiveSheet: () => source, getSheetBySheetId: (id: string) => [source, other].find(s => s.getSheetId() === id) }
}
it.each(['Source!A1:A5', "'sOuRcE'!$A$1:$A$5", "'[book-id]SOURCE'!a1:a5"] )('rejects actual unprojected chart formula %s', async formula => {
  const { assertChartSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertChartSheetRemoval(book(), 'source', (id: string) => id === 'other' ? [{ path: 'xl/charts/chart1.xml', xml: chart(formula) }] : [])).toThrow('Other')
})
it.each(['Other!A1:A5', '&quot;Source!A1&quot;', "'[remote.xlsx]Source'!A1", '[BOOK-ID]Source!A1'])('preserves literal or external formula %s', async formula => {
  const { assertChartSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertChartSheetRemoval(book(), 'source', () => [{ path: 'xl/charts/chart1.xml', xml: chart(formula) }])).not.toThrow()
})
it('does not request charts owned only by the removed sheet', async () => {
  const { assertChartSheetRemoval } = await import(/* @vite-ignore */ implementation)
  const visited: string[] = []
  expect(() => assertChartSheetRemoval(book(), 'source', (id: string) => { visited.push(id);if(id === 'source') throw Error('owned source should not be read');return [] })).not.toThrow()
  expect(visited).toEqual(['other'])
})
it('propagates incomplete actual package ownership instead of trusting empty live projection', async () => {
  const { assertChartSheetRemoval } = await import(/* @vite-ignore */ implementation)
  expect(() => assertChartSheetRemoval(book(), 'source', () => { throw Error('实际图表关系来源无法完整核对') })).toThrow('完整核对')
})
