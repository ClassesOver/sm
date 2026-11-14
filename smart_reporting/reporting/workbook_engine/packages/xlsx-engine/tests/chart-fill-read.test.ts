import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { readCharts } from '../src/chart-read'

async function fixture(fill: string, points = '', vary = '', theme = false) {
  const bytes = await applyChartAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 9, toColumn: 11, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: '来源填充', series: [{ name: '收入', categories: ['A', 'B', 'C'], values: [3, 6, 9], valuesRef: 'Sheet1!B2:B4', color: '#126B3A' }] },
  }])
  const zip = await JSZip.loadAsync(bytes), path = 'xl/charts/chart1.xml'
  zip.file(path, (await zip.file(path)!.async('string'))
    .replace(/<c:spPr>[\s\S]*?<\/c:spPr>/, `<c:spPr>${fill}</c:spPr>${points}`)
    .replace('<c:barChart>', `<c:barChart>${vary}`))
  if (theme) {
    zip.file('xl/theme/theme1.xml', '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:themeElements><a:clrScheme name="Custom">' +
      [['dk1','000000'],['lt1','FFFFFF'],['dk2','44546A'],['lt2','E7E6E6'],['accent1','136B4A'],['accent2','A02040'],['accent3','223344'],['accent4','654321'],['accent5','AABBCC'],['accent6','123456'],['hlink','0563C1'],['folHlink','954F72']]
        .map(([name,color]) => `<a:${name}><a:srgbClr val="${color}"/></a:${name}>`).join('') + '</a:clrScheme></a:themeElements></a:theme>')
    const rels = 'xl/_rels/workbook.xml.rels'
    zip.file(rels, (await zip.file(rels)!.async('string')).replace('</Relationships>', '<Relationship Id="theme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>'))
  }
  return zip.generateAsync({ type: 'uint8array' })
}
const point = (index: string, fill: string) => `<c:dPt><c:idx val="${index}"/><c:spPr>${fill}</c:spPr></c:dPt>`
const rgb = (color: string) => `<a:solidFill><a:srgbClr val="${color}"/></a:solidFill>`
const chart = async (bytes: Uint8Array) => (await readCharts(bytes, 'xl/worksheets/sheet1.xml'))[0]!

it('保留稀疏逐点覆盖和无填充，不把点或轮廓色当作系列填充', async () => {
  const bytes = await fixture(rgb('126B3A'), point('2', rgb('FF0000')) + point('0', '<a:noFill/>'))
  const original = bytes.slice(), result = await chart(bytes)
  expect(result.series[0]).toMatchObject({ color: '#126B3A', pointColors: { 0: 'transparent', 2: '#FF0000' } })
  expect(result.series[0]!.colorPreviewUnavailable).toBeUndefined()
  expect(bytes).toEqual(original)
})

it('用现有工作簿主题解析显式主题色及默认系列调色板', async () => {
  const result = await chart(await fixture('<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>', point('1', '<a:solidFill><a:schemeClr val="accent2"/></a:solidFill>'), '<c:varyColors val="1"/>', true))
  expect(result.series[0]).toMatchObject({ color: '#136B4A', pointColors: { 1: '#A02040' } })
  expect(result.palette).toEqual(['#136B4A', '#A02040', '#223344', '#654321', '#AABBCC', '#123456'])
  expect(result.varyColors).toBe(true)
})

it('系列填充跟随工作簿的实际主题关系，不读取旧固定路径', async () => {
  const bytes = await fixture('<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>', '', '', true)
  const zip = await JSZip.loadAsync(bytes), rels = 'xl/_rels/workbook.xml.rels'
  zip.file('xl/theme/actual.xml', (await zip.file('xl/theme/theme1.xml')!.async('string')).replace('136B4A', 'A040C0'))
  zip.file(rels, (await zip.file(rels)!.async('string')).replace('theme/theme1.xml', 'theme/actual.xml'))
  const result = await chart(await zip.generateAsync({ type: 'uint8array' }))
  expect(result.series[0]!.color).toBe('#A040C0')
  expect(result.palette?.[0]).toBe('#A040C0')
})

it('缺少实际主题时不把显式系列主题填充误画成默认蓝色', async () => {
  const result = await chart(await fixture('<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>'))
  expect(result.series[0]!.colorPreviewUnavailable).toBe(true)
  expect(result.series[0]!.color).toBeUndefined()
})

it.each(['<a:solidFill><a:schemeClr val="missing"/></a:solidFill>', '<a:gradFill/>', '<a:solidFill><a:srgbClr val="4472C4"><a:alpha val="50000"/></a:srgbClr></a:solidFill>'])('无法可靠解析的填充明确标记，而不是读取未变换的基色：%s', async fill => {
  const result = await chart(await fixture(fill))
  expect(result.series[0]!.colorPreviewUnavailable).toBe(true)
  expect(result.series[0]!.color).toBeUndefined()
})

it.each([
  ['4472C4', '<a:lumMod val="75000"/>', '#2F5597'],
  ['7F0000', '<a:lumMod val="40000"/><a:lumOff val="60000"/>', '#FF6666'],
  ['7F0000', '<a:lumOff val="60000"/><a:lumMod val="40000"/>', '#AD0000'],
  ['000000', '<a:lumOff val="200000"/><a:lumMod val="50000"/>', '#808080'],
])('按来源顺序计算亮度变换 %s %s，不改变HLS饱和度', async (base, modifiers, expected) => {
  const result = await chart(await fixture(`<a:solidFill><a:srgbClr val="${base}">${modifiers}</a:srgbClr></a:solidFill>`))
  expect(result.series[0]!.color).toBe(expected)
  expect(result.series[0]!.colorPreviewUnavailable).toBeUndefined()
})

it('系列无填充与显式varyColors=false不会被默认蓝色或逐点调色板覆盖', async () => {
  const result = await chart(await fixture('<a:noFill/>', '', '<c:varyColors val="false"/>'))
  expect(result.series[0]!.color).toBe('transparent')
  expect(result.varyColors).toBe(false)
})

it('重复点身份不猜测覆盖顺序，也不把嵌套线条颜色当作点填充', async () => {
  const result = await chart(await fixture('', point('1', rgb('FF0000')) + point('1', rgb('00FF00')) + point('2', `<a:ln>${rgb('0000FF')}</a:ln>`)))
  expect(result.series[0]!.colorPreviewUnavailable).toBe(true)
  expect(result.series[0]!.pointColors?.[2]).toBeUndefined()
})
