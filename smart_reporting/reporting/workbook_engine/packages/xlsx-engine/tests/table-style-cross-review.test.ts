import { expect, it } from 'vitest'
import { readCustomTableStyles } from '../src/table-style-read'

function palette(dxf: string) {
  const xml = `<styleSheet><dxfs><dxf>${dxf}</dxf></dxfs><tableStyles><tableStyle name="Review"><tableStyleElement type="wholeTable" dxfId="0"/></tableStyle></tableStyles></styleSheet>`
  return readCustomTableStyles(xml).get('Review')!.palette
}

it('matches fixed-source integer-floor gradient blending for odd component sums', () => {
  // visuals/styles.rs mix_hex divides u16 sums by 2 (floor).
  expect(palette('<fill><gradientFill><stop position="0"><color rgb="FF000000"/></stop><stop position="1"><color rgb="FFFFFFFF"/></stop></gradientFill></fill>').wholeTableFill).toBe('#7F7F7F')
})

it('ignores a none left border and falls back to the real top outline like the fixed source', () => {
  // visuals/styles.rs parse_border returns None for style=none before table_styles left.or(top).
  expect(palette('<border><left style="none"><color rgb="FFFF0000"/></left><top style="thin"><color rgb="FF00FF00"/></top></border>')).toMatchObject({ wholeTableBorderColor: '#00FF00', wholeTableBorderStyle: 'thin' })
})
