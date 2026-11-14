import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { readCharts } from '../src/chart-read'

const EMU = 9525
const drawingPath = 'xl/drawings/drawing1.xml'
const worksheetPath = 'xl/worksheets/sheet1.xml'

async function fixture(kind: 'oneCellAnchor' | 'absoluteAnchor', prefix = 'xdr', extent = `cx="${128 * EMU}" cy="${92 * EMU}"`) {
  const added = await applyChartAdditions(await createBlankWorkbook(), [{
    worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 4, fromRowOffset: 3 * EMU, fromColumnOffset: 5 * EMU,
      toRow: 9, toColumn: 12, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: '锚点 & 保真', series: [{ name: '收入', categories: ['A', 'B'], values: [3, 6], valuesRef: 'Sheet1!$B$2:$B$3' }] },
  }])
  const zip = await JSZip.loadAsync(added)
  let xml = await zip.file(drawingPath)!.async('string')
  xml = xml.replace(/<xdr:twoCellAnchor\b[^>]*>([\s\S]*?)<\/xdr:twoCellAnchor>/, (_whole, block: string) => {
    const frame = block.slice(block.indexOf('<xdr:graphicFrame'))
    const start = kind === 'oneCellAnchor' ? block.match(/<xdr:from>[\s\S]*?<\/xdr:from>/)![0]
      : `<xdr:pos x="${405 * EMU}" y="${190 * EMU}"/>`
    return `<xdr:${kind}>${start}<xdr:ext ${extent}/>${frame}</xdr:${kind}>`
  })
  if (prefix !== 'xdr') {
    xml = xml.replace('xmlns:xdr=', prefix ? `xmlns:${prefix}=` : 'xmlns=')
      .replace(/(<\/?)(?:xdr:)/g, `$1${prefix ? prefix + ':' : ''}`)
  }
  zip.file(drawingPath, xml)
  return zip.generateAsync({ type: 'uint8array' })
}

it.each(['xdr', '', 'drawing'])('读取单单元格锚点 %s，保留单元格移动与固定EMU尺寸', async prefix => {
  const bytes = await fixture('oneCellAnchor', prefix), original = bytes.slice()
  const charts = await readCharts(bytes, worksheetPath)
  expect(charts).toHaveLength(1)
  expect(charts[0]!.anchor).toEqual({ fromRow: 2, fromColumn: 4, toRow: 2, toColumn: 4,
    fromRowOffset: 3 * EMU, fromColumnOffset: 5 * EMU,
    toRowOffset: 95 * EMU, toColumnOffset: 133 * EMU })
  expect(charts[0]!.title).toBe('锚点 & 保真')
  expect(charts[0]!.series[0]!.valuesRef).toBe('Sheet1!$B$2:$B$3')
  expect(bytes).toEqual(original)
})

it.each(['xdr', '', 'drawing'])('读取绝对锚点 %s，不猜测行高列宽', async prefix => {
  const bytes = await fixture('absoluteAnchor', prefix), original = bytes.slice()
  const charts = await readCharts(bytes, worksheetPath)
  expect(charts).toHaveLength(1)
  expect(charts[0]!.anchor).toEqual({ fromRow: 0, fromColumn: 0, toRow: 0, toColumn: 0,
    fromRowOffset: 190 * EMU, fromColumnOffset: 405 * EMU,
    toRowOffset: 282 * EMU, toColumnOffset: 533 * EMU })
  expect(bytes).toEqual(original)
})

it.each(['oneCellAnchor', 'absoluteAnchor'] as const)('无效尺寸的 %s 不产生虚构图框，也不影响同页有效图表', async kind => {
  const bytes = await fixture(kind), zip = await JSZip.loadAsync(bytes)
  const valid = await zip.file(drawingPath)!.async('string')
  const anchor = valid.match(new RegExp(`<xdr:${kind}\\b[^>]*>[\\s\\S]*?</xdr:${kind}>`))![0]
  const invalid = ['cx="bad" cy="100"', 'cx="-1" cy="100"', 'cx="0" cy="100"', 'cy="100"', 'cx="9007199254740992" cy="100"']
    .map(extent => anchor.replace(/<xdr:ext[^>]*\/>/, `<xdr:ext ${extent}/>`)).join('')
  zip.file(drawingPath, valid.replace('</xdr:wsDr>', invalid + '</xdr:wsDr>'))
  expect(await readCharts(await zip.generateAsync({ type: 'uint8array' }), worksheetPath)).toHaveLength(1)
})
