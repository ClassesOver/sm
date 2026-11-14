import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'
import { buildChartXml, applyChartAdditions } from '../src/chart-add'
import { applyChartEdit, type ChartSeriesSetEntry } from '../src/chart-edit'
import { createBlankWorkbook, readWorkbook } from '../src'
import { applyChartEdits } from '../src/rules'
import { createBufferEntrySource } from '../src/zip'

const series = ['North', 'South', 'Rate'].map((name, index) => ({ name, categories: ['Q1', 'Q2'], values: [index + 1, index + 2] }))
const original = () => buildChartXml({ chartType: 'combo', title: 'Keep title', series })
const groups = (xml: string) => [...xml.matchAll(/<c:(barChart|lineChart)>([\s\S]*?)<\/c:\1>/g)].map(match => ({ family: match[1], body: match[2]!, ids: [...match[2]!.matchAll(/<c:axId val="(\d+)"\/>/g)].map(id => id[1]) }))
const axes = (xml: string) => [...xml.matchAll(/<c:(catAx|valAx)>[\s\S]*?<\/c:\1>/g)].map(match => match[0])
const entries = [
  { name: 'Secondary bar', values: [900, 500], categories: ['A', 'B'], plot: 'barChart', secondaryAxis: true },
  { name: 'Primary line', values: [3, 4], plot: 'lineChart', secondaryAxis: false },
  { name: 'Primary bar', values: [10, 20], plot: 'barChart', secondaryAxis: false, color: '#123456' },
  { name: 'Secondary line', values: [800, 600], plot: 'lineChart', secondaryAxis: true },
] as const

describe('source combo Select Data', () => {
  it('regroups all four family/axis combinations with global idx/order and preserves axes/title/tail', () => {
    const before = original().replace('</c:plotArea>', '<c:spPr><a:ln/></c:spPr></c:plotArea>')
    const after = applyChartEdit(before, { seriesSet: entries })
    expect(groups(after).map(group => [group.family, group.ids])).toEqual([
      ['barChart', ['100000001', '100000002']], ['lineChart', ['100000001', '100000002']],
      ['barChart', ['100000003', '100000004']], ['lineChart', ['100000003', '100000004']],
    ])
    expect(groups(after).map(group => group.body.match(/<c:order val="(\d+)"/)![1])).toEqual(['2', '1', '0', '3'])
    expect(axes(after)).toEqual(axes(before))
    expect(after).toContain('Keep title'); expect(after).toContain('<c:spPr><a:ln/></c:spPr>')
    expect(after).toContain('<a:srgbClr val="123456"/>')
  })

  it('removes the secondary pair when every tagged series moves to primary', () => {
    const before = original(), after = applyChartEdit(before, { seriesSet: entries.map(entry => ({ ...entry, secondaryAxis: false })) })
    expect(groups(after)).toHaveLength(2); expect(axes(after)).toEqual(axes(before).slice(0, 2))
    expect(after).not.toContain('100000003'); expect(after).not.toContain('100000004')
  })

  it('synthesizes a hidden category/right value pair when a tagged set needs a secondary scale', () => {
    const before = buildChartXml({ chartType: 'column', title: 'Keep', series })
    const after = applyChartEdit(before, { seriesSet: entries })
    expect(axes(after)).toHaveLength(4); expect(axes(after).slice(0, 2)).toEqual(axes(before))
    expect(after).toContain('<c:delete val="1"/><c:axPos val="b"/>')
    expect(after).toContain('<c:axPos val="r"/>')
    expect(groups(after)[2]!.ids).not.toEqual(groups(after)[0]!.ids)
  })

  it('rejects exotic multi-plots and 3D series axes rather than dropping their structure', () => {
    expect(() => applyChartEdit(original().replaceAll('lineChart', 'areaChart'), { seriesSet: entries })).toThrow(/bar \+ line/)
    expect(() => applyChartEdit(original().replace('</c:plotArea>', '<c:serAx><c:axId val="99"/></c:serAx></c:plotArea>'), { seriesSet: entries })).toThrow(/series axes/)
  })

  it('keeps original namespace bindings while rebuilding combo groups', () => {
    const before = original().replaceAll('xmlns:c=', 'xmlns:q=').replaceAll('c:', 'q:')
    const after = applyChartEdit(before, { seriesSet: entries })
    expect(after).toContain('<q:barChart>'); expect(after).not.toContain('<c:'); expect(after).toContain('Secondary line')
  })

  it('roundtrips actual XLSX plot and secondary-axis tags without changing unrelated ZIP parts', async () => {
    const before = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', anchor: { fromRow: 2, fromColumn: 3, toRow: 18, toColumn: 12, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }, chart: { chartType: 'combo', title: 'Keep', series } }])
    const initial = (await readWorkbook(before)).sheets[0]!.charts![0]!
    expect(initial.series.map(entry => [entry.plot, entry.secondaryAxis])).toEqual([['barChart', false], ['barChart', false], ['lineChart', true]])
    const after = await applyChartEdits(before, [{ chartPath: initial.chartPath, seriesSet: entries as readonly ChartSeriesSetEntry[] }])
    const read = (await readWorkbook(after)).sheets[0]!.charts![0]!
    expect(read.kind).toBe('combo')
    expect(read.series.map(entry => [entry.name, entry.plot, entry.secondaryAxis])).toEqual([
      ['Primary bar', 'barChart', false], ['Primary line', 'lineChart', false], ['Secondary bar', 'barChart', true], ['Secondary line', 'lineChart', true],
    ])
    const a = await createBufferEntrySource(before), b = await createBufferEntrySource(after), za = await JSZip.loadAsync(before), zb = await JSZip.loadAsync(after)
    expect(await b.paths()).toEqual(await a.paths())
    for (const path of await a.paths()) if (path !== initial.chartPath) expect(await zb.file(path)!.async('uint8array')).toEqual(await za.file(path)!.async('uint8array'))
  })

  it('keeps the secondary scale readable when tagged series collapse to one family', async () => {
    const before = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', anchor: { fromRow: 2, fromColumn: 3, toRow: 18, toColumn: 12, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }, chart: { chartType: 'combo', title: 'Keep', series } }])
    const after = await applyChartEdits(before, [{ chartPath: 'xl/charts/chart1.xml', seriesSet: entries.map(entry => ({ ...entry, plot: 'barChart' as const })) }])
    const chart = (await readWorkbook(after)).sheets[0]!.charts![0]!
    expect(chart.series.map(entry => entry.secondaryAxis)).toEqual([false, false, true, true])
    expect(chart.secondaryAxes?.value.position).toBe('right')
  })
})
