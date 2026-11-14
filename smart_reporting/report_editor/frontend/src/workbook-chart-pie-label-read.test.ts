import { expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyChartAdditions } from '@sheets-web/xlsx-engine/chart-add'
import { assemblePackage, createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'

it.each(['pie', 'doughnut'] as const)('reads %s category-percent labels with real saved point overrides', async chartType => {
  let bytes = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 12, toColumn: 12, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType, title: '标签', dataLabels: 'category-percent', dataLabelFormat: '0.0%',
      series: [{ name: '收入', valuesRef: 'Sheet1!B2:B3', values: [3, 7], categories: ['甲', '乙'] }] },
  }])
  const source = await createBufferEntrySource(bytes), path = 'xl/charts/chart1.xml'
  const style = '<c:txPr><a:p><a:pPr><a:defRPr sz="1400" b="1"><a:solidFill><a:srgbClr val="123456"/></a:solidFill></a:defRPr></a:pPr></a:p></c:txPr>'
  const xml = (await source.readText(path)).replace('<c:dLbls>', '<c:dLbls>' +
    '<c:dLbl><c:idx val="1"/><c:delete val="1"/></c:dLbl>' + style + '<c:dLblPos val="bestFit"/>')
    .replace('</c:ser>', '<c:dLbls><c:dLbl><c:idx val="0"/><c:showPercent val="1"/><c:showVal val="0"/></c:dLbl>' +
      '<c:showPercent val="0"/><c:showVal val="1"/></c:dLbls></c:ser>')
  bytes = (await assemblePackage(bytes, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const chart = (await readWorkbook(bytes)).sheets[0]!.charts![0]!
  expect(chart.dataLabels).toMatchObject({ showValue: false, showCategory: true, showPercent: true, numberFormat: '0.0%',
    style: { sizePt: 14, bold: true, color: '#123456' } })
  expect(chart.dataLabels?.unsupported).toBeUndefined()
  expect(chart.dataLabels?.points?.[1]).toMatchObject({ deleted: true })
  expect(chart.series[0]!.dataLabels).toMatchObject({ showPercent: false, showValue: true, points: { 0: { showPercent: true, showValue: false } } })
  expect(chart.series[0]!.dataLabels?.unsupported).toBeUndefined()
  expect(await (await createBufferEntrySource(bytes)).readText(chart.chartPath)).toContain('showPercent')
})
