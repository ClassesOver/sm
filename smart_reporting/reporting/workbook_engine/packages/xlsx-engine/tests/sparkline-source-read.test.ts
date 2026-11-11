import { expect, it } from 'vitest'
import { readSparklines } from '../src/sparklines'
const x14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const xm = 'http://schemas.microsoft.com/office/excel/2006/main'
const wrap = (source: string) => `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><extLst><ext uri="{05C60535-1F16-4FD2-B633-F4F36F0B64E0}" xmlns:p="${x14}" xmlns:q="${xm}"><p:sparklineGroups><p:sparklineGroup type="column" markers="true" displayAxis="1" custom="preserve"><p:colorSeries rgb="FFA1B2C3"/><p:sparklines><p:sparkline><q:f>${source}</q:f><q:sqref> G2 </q:sqref></p:sparkline></p:sparklines></p:sparklineGroup></p:sparklineGroups></ext></extLst></worksheet>`
it.each([
  ["'来源 ! O''Brien 中文'!$B$2:$D$2", "来源 ! O'Brien 中文"],
  ['Other!$B$2:$D$2', 'Other'], ['来源!$B$2:$D$2', '来源'],
  ["'A&amp;B'!$B$2:$D$2", 'A&B'],
])('保留namespace别名前缀和限定表身份 %s', (source, sourceSheet) => {
  expect(readSparklines(wrap(source))).toEqual([{ kind: 'column', source: '$B$2:$D$2', sourceSheet, target: 'G2', color: '#A1B2C3', markers: true, showAxis: true }])
})
it('未限定来源仍保留同页语义，CDATA引用也解析', () => {
  expect(readSparklines(wrap('<![CDATA[$B$2:$D$2]]>'))[0]).toMatchObject({ source: '$B$2:$D$2', target: 'G2' })
  expect(readSparklines(wrap('<![CDATA[$B$2:$D$2]]>'))[0]).not.toHaveProperty('sourceSheet')
})
it.each(['[external.xlsx]Sheet1!B2:D2', "'Sheet1:Sheet3'!B2:D2", 'SUM(B2:D2)', 'Other!B2:XFE2', "'Broken!B2:D2"])('无法可靠解析引用时不误画本页 %s', source => {
  expect(readSparklines(wrap(source))).toEqual([])
})
it('同名伪namespace对象和XML正文伪标签不会进入read模型', () => {
  expect(readSparklines(wrap('Other!$B$2:$D$2').replaceAll(x14, 'urn:fake'))).toEqual([])
  expect(readSparklines(`<!--${wrap('Other!$B$2:$D$2')}-->${wrap('B2:D2')}`)).toHaveLength(1)
})

it('拒绝伪扩展容器、重复来源及带嵌套未知对象的来源', () => {
  expect(readSparklines(wrap('B2:D2').replace('<ext uri=', '<foreign:ext xmlns:foreign="urn:other" uri=').replace('</ext>', '</foreign:ext>'))).toEqual([])
  expect(readSparklines(wrap('B2:D2').replace('</q:f>', '</q:f><q:f>B2:D2</q:f>'))).toEqual([])
  expect(readSparklines(wrap('B2<q:unknown/>:D2'))).toEqual([])
})
