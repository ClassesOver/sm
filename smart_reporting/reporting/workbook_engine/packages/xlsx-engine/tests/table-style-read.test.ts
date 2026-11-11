import { expect, it } from 'vitest'
import { readCustomTableStyles } from '../src/table-style-read'

const styleXml = (dxfs: string[], elements: string, colors = '') => `<styleSheet><dxfs count="${dxfs.length}">${dxfs.map(dxf => `<dxf>${dxf}</dxf>`).join('')}</dxfs><tableStyles><tableStyle name="My&amp;Style" pivot="0">${elements}</tableStyle></tableStyles>${colors}</styleSheet>`
const element = (type: string, index: number) => `<tableStyleElement type="${type}" dxfId="${index}"/>`

it('reads only the fixed-source custom band palette without treating other DXF font formats as table style features', () => {
  const xml = styleXml([
    '<font><b/><color rgb="FFFF0000"/></font><fill><patternFill><bgColor rgb="FF102030"/><fgColor rgb="FF999999"/></patternFill></fill><border><bottom style="double"><color rgb="FF112233"/></bottom></border>',
    '<fill><patternFill><bgColor rgb="FFDEEBF7"/></patternFill></fill>',
    '<fill><patternFill><bgColor rgb="FFFFC000"/></patternFill></fill><border><top style="medium"><color rgb="FF225588"/></top></border>',
  ], element('headerRow', 0) + element('firstRowStripe', 1) + element('totalRow', 2) + element('notSupported', 0))
  expect(readCustomTableStyles(xml).get('My&Style')).toEqual({ name: 'My&Style', palette: {
    headerFill: '#102030', headerFontColor: '#FF0000', headerBottomBorderColor: '#112233', headerBottomBorderStyle: 'double',
    stripeFill: '#DEEBF7', totalRowFill: '#FFC000', totalRowBorderColor: '#225588', totalRowBorderStyle: 'medium',
  } })
})

it('resolves theme tint, indexed palette overrides, fixed system slots, and invalid DXF references independently', () => {
  const xml = styleXml([
    '<fill><patternFill><bgColor theme="4" tint="0.5" rgb="FFFF0000"/></patternFill></fill>',
    '<fill><patternFill><bgColor indexed="0"/></patternFill></fill>',
    '<font><color indexed="64"/></font>',
  ], element('headerRow', 0) + element('firstRowStripe', 1) + element('firstHeaderCell', 2) + element('secondRowStripe', 99), '<colors><indexedColors><rgbColor rgb="FF123456"/></indexedColors></colors>')
  const palette = readCustomTableStyles(xml, ['#FFFFFF', '#000000', '#EEEEEE', '#222222', '#000000']).get('My&Style')!.palette
  expect(palette).toEqual({ headerFill: '#7F7F7F', stripeFill: '#123456', firstHeaderCellFontColor: '#000000' })
})

it('reads custom outlines, inner grid, column emphasis, both stripe colors and first header text', () => {
  const xml = styleXml([
    '<fill><patternFill><bgColor rgb="FFEEEEEE"/></patternFill></fill><border><left style="medium"><color rgb="FF111111"/></left><top style="thin"><color rgb="FF999999"/></top><horizontal style="dashed"><color rgb="FF222222"/></horizontal><vertical style="dotted"><color rgb="FF333333"/></vertical></border>',
    '<fill><patternFill><bgColor rgb="FFAACCEE"/></patternFill></fill><font><color rgb="FFABCDEF"/></font>',
  ], element('wholeTable', 0) + ['firstColumn', 'lastColumn', 'secondRowStripe', 'firstColumnStripe', 'secondColumnStripe', 'firstHeaderCell'].map(kind => element(kind, 1)).join(''))
  expect(readCustomTableStyles(xml).get('My&Style')!.palette).toEqual({
    wholeTableFill: '#EEEEEE', wholeTableBorderColor: '#111111', wholeTableBorderStyle: 'medium', innerHorizontalBorderColor: '#222222', innerHorizontalBorderStyle: 'dashed', innerVerticalBorderColor: '#333333', innerVerticalBorderStyle: 'dotted',
    firstColumnFill: '#AACCEE', lastColumnFill: '#AACCEE', secondRowStripeFill: '#AACCEE', columnStripeFill: '#AACCEE', secondColumnStripeFill: '#AACCEE', firstHeaderCellFontColor: '#ABCDEF',
  })
})

it('flattens a gradient DXF like the fixed-source reader and skips absent definitions', () => {
  const xml = styleXml(['<fill><gradientFill><stop position="0"><color rgb="FF000000"/></stop><stop position="1"><color rgb="FFFFFFFF"/></stop></gradientFill></fill>'], element('wholeTable', 0))
  expect(readCustomTableStyles(xml).get('My&Style')!.palette.wholeTableFill).toBe('#7F7F7F')
  expect(readCustomTableStyles('<styleSheet><tableStyles/></styleSheet>').size).toBe(0)
})
