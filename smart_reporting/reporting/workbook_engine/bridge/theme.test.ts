import { expect, it } from 'vitest'
import { createBlankWorkbook, createBufferEntrySource, readWorkbook } from '../packages/xlsx-engine/src/index'
import { assemblePackage } from '../packages/xlsx-engine/src/zip'
import { applyWorkbookOperations } from './operations'

const ember = ['#FFFFFF', '#2B1B14', '#F7EBE6', '#632B1A', '#C43E1C', '#E97132', '#FFC000', '#8A3B12', '#D98F73', '#A33517', '#C43E1C', '#954F72']
// Office 默认主题（clrScheme + fontScheme），与 Excel/openpyxl 写出的 theme1.xml 结构一致；含主题关系与内容类型。
const officeTheme = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office Theme"><a:themeElements>'
  + '<a:clrScheme name="Office"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
  + ['4472C4', 'ED7D31', 'A5A5A5', 'FFC000', '5B9BD5', '70AD47'].map((value, index) => `<a:accent${index + 1}><a:srgbClr val="${value}"/></a:accent${index + 1}>`).join('')
  + '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
  + '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
  + '<a:fmtScheme name="Office"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme></a:themeElements></a:theme>'
async function themedWorkbook(): Promise<Uint8Array> {
  const bytes = await createBlankWorkbook(), source = await createBufferEntrySource(bytes)
  const types = (await source.readText('[Content_Types].xml')).replace('</Types>', '<Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/></Types>')
  const rels = (await source.readText('xl/_rels/workbook.xml.rels')).replace('</Relationships>', '<Relationship Id="rIdTheme1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>')
  return (await assemblePackage(bytes, { replaced: new Map([['[Content_Types].xml', types], ['xl/_rels/workbook.xml.rels', rels]]), added: new Map([['xl/theme/theme1.xml', officeTheme]]), addedBinary: new Map(), removedEntries: [], addedEntries: ['xl/theme/theme1.xml'], touchedEntries: ['[Content_Types].xml', 'xl/_rels/workbook.xml.rels'] })).buffer
}
const theme = async (bytes: Uint8Array) => (await createBufferEntrySource(bytes)).readText('xl/theme/theme1.xml')

it('rewrites theme colors and fonts in place and the reader resolves the new palette', async () => {
  const source = await themedWorkbook()
  expect((await readWorkbook(source)).themePalette?.[4]).toBe('#4472C4')
  const before = await createBufferEntrySource(source)
  const saved = await applyWorkbookOperations(source, [
    { kind: 'setThemePart', themePath: 'xl/theme/theme1.xml', state: { colors: { name: 'Ember', values: ember }, fonts: { name: 'Trebuchet MS', major: 'Trebuchet MS', minor: 'Calibri' } } },
  ])
  const xml = await theme(saved)
  expect(xml).toMatch(/<a:clrScheme name="Ember">/)
  expect(xml).toContain('<a:dk1><a:srgbClr val="2B1B14"/></a:dk1>')
  expect(xml).toContain('<a:accent1><a:srgbClr val="C43E1C"/></a:accent1>')
  expect(xml).toMatch(/<a:fontScheme name="Trebuchet MS">/)
  expect(xml).toMatch(/<a:majorFont>[\s\S]*?<a:latin typeface="Trebuchet MS"/)
  expect(xml).toMatch(/<a:minorFont>[\s\S]*?<a:latin typeface="Calibri"/)
  expect((await readWorkbook(saved)).themePalette).toEqual(ember)
  // 其余部件字节不变
  const after = await createBufferEntrySource(saved)
  for (const path of ['xl/workbook.xml', 'xl/styles.xml', 'xl/worksheets/sheet1.xml']) expect(await after.readText(path)).toBe(await before.readText(path))
  // 只改字体时配色保持
  const fontsOnly = await applyWorkbookOperations(saved, [{ kind: 'setThemePart', themePath: 'xl/theme/theme1.xml', state: { fonts: { name: 'Arial', major: 'Arial', minor: 'Arial' } } }])
  expect(await theme(fontsOnly)).toContain('<a:accent1><a:srgbClr val="C43E1C"/></a:accent1>')
  expect(await theme(fontsOnly)).toMatch(/<a:fontScheme name="Arial">/)
})

it('rejects other parts, malformed palettes and font names before writing', async () => {
  const bytes = await themedWorkbook()
  // 没有主题部件的工作簿（固定源 appThemeNeedsThemePart）同样拒绝
  await expect(applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'setThemePart', themePath: 'xl/theme/theme1.xml', state: { colors: { name: 'Ember', values: ember } } }])).rejects.toThrow(/no xl\/theme\/theme1.xml/)
  const colors = { name: 'Ember', values: ember }
  for (const op of [
    { themePath: 'xl/styles.xml', state: { colors } },
    { themePath: 'xl/theme/theme2.xml', state: { colors } },
    { themePath: 'xl/theme/theme1.xml', state: {} },
    { themePath: 'xl/theme/theme1.xml', state: { colors: { name: 'x', values: ember.slice(1) } } },
    { themePath: 'xl/theme/theme1.xml', state: { colors: { name: 'x', values: ember.map((value, index) => index ? value : 'red') } } },
    { themePath: 'xl/theme/theme1.xml', state: { colors: { name: '', values: ember } } },
    { themePath: 'xl/theme/theme1.xml', state: { fonts: { name: 'x', major: 'A\nB', minor: 'C' } } },
    { themePath: 'xl/theme/theme1.xml', state: { fonts: { name: 'x', major: 'A', minor: 'C', extra: 1 } } },
    { themePath: 'xl/theme/theme1.xml', state: { colors }, extra: true },
  ]) await expect(applyWorkbookOperations(bytes, [{ kind: 'setThemePart', ...op }])).rejects.toThrow()
})
