import { expect, it } from 'vitest'
import { parseStylesheet } from '../src/style-read'
import { StylesheetEditor } from '../src/styles-write'
const styles = (alignment: string) => `<styleSheet><fonts count="1"><font><sz val="17"/></font></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0">${alignment}</xf></cellXfs></styleSheet>`
it.each([0, 45, 90, 135, 180, 255])('reads direct textRotation=%s attributes rather than searching for nonexistent child tags', textRotation => {
  const result = parseStylesheet(styles(`<alignment textRotation="${textRotation}" indent="3" horizontal="right" wrapText="1"/>`))
  expect(result.cellXfs[0]!.alignment).toMatchObject({ textRotation, indent: 3, horizontal: 'right', wrapText: true })
  expect(result.fonts[0]!.size).toBe(17)
})
it('keeps absent and nonfinite direct attributes unset while reading valid explicit zeros', () => {
  expect(parseStylesheet(styles('<alignment/>')).cellXfs[0]!.alignment).toMatchObject({ textRotation: undefined, indent: undefined })
  expect(parseStylesheet(styles('<alignment textRotation="NaN" indent="Infinity"/>')).cellXfs[0]!.alignment).toMatchObject({ textRotation: undefined, indent: undefined })
  expect(parseStylesheet(styles('<alignment textRotation="0" indent="0"/>')).cellXfs[0]!.alignment).toMatchObject({ textRotation: 0, indent: 0 })
})

it('reads cell font vertical alignment from OOXML', () => {
  const xml = '<styleSheet><fonts count="3"><font><vertAlign val="superscript"/></font><font><vertAlign val="subscript"/></font><font><vertAlign val="baseline"/></font></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>'
  const result = parseStylesheet(xml)
  expect(result.fonts.map(font => font.vertAlign)).toEqual(['superscript', 'subscript', undefined])
})

it.each(['superscript', 'subscript'] as const)('writes %s while preserving sibling font properties', value => {
  const xml = '<styleSheet><fonts count="1"><font><b/><i/><color rgb="FF123456"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs></styleSheet>'
  const editor = new StylesheetEditor(xml)
  const index = editor.resolveStyle(0, { vertAlign: value })
  const saved = editor.serialize()
  const parsed = parseStylesheet(saved)
  expect(parsed.cellXfs[index]!.fontId).toBeGreaterThan(0)
  expect(parsed.fonts[parsed.cellXfs[index]!.fontId]).toMatchObject({ vertAlign: value, bold: true, italic: true, color: '#123456' })
  const cleared = new StylesheetEditor(saved)
  const baseline = cleared.resolveStyle(index, { vertAlign: 'baseline' })
  expect(parseStylesheet(cleared.serialize()).fonts[parseStylesheet(cleared.serialize()).cellXfs[baseline]!.fontId]!.vertAlign).toBeUndefined()
})

import JSZip from 'jszip'
import { createBlankWorkbook } from '../src/blank'
import { readWorkbook } from '../src/workbook-read'
it.each(['row', 'column', 'default', 'named', 'disabled', 'disabled-secondary'])('exposes a safe rotation read-only source gate for %s inherited styles', async source => {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  let sheet = await zip.file('xl/worksheets/sheet1.xml')!.async('string')
  let stylesheet = await zip.file('xl/styles.xml')!.async('string')
  if (source === 'row') sheet = sheet.replace(/<sheetData\s*\/>/, '<sheetData><row r="1" s="0" customFormat="1"/></sheetData>')
  if (source === 'column') sheet = sheet.replace('<sheetData', '<cols><col min="1" max="1" style="0"/></cols><sheetData')
  if (source === 'default' || source === 'disabled') stylesheet = stylesheet.replace(/(<cellXfs\b[^>]*>)<xf\b[^>]*\/>/, `$1<xf numFmtId="0" fontId="0" fillId="0" borderId="0"${source === 'disabled' ? ' applyAlignment="0"' : ''}><alignment textRotation="37"/></xf>`)
  if (source === 'named') stylesheet = stylesheet.replace(/(<cellStyleXfs\b[^>]*>)<xf\b[^>]*\/>/, '$1<xf numFmtId="0" fontId="0" fillId="0" borderId="0"><alignment textRotation="37"/></xf>')
  if (source === 'disabled-secondary') stylesheet = stylesheet.replace('</cellXfs>', '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="0"><alignment textRotation="37"/></xf></cellXfs>')
  zip.file('xl/worksheets/sheet1.xml', sheet);zip.file('xl/styles.xml',stylesheet)
  const model = await readWorkbook(await zip.generateAsync({type:'uint8array'}))
  expect(model.sheets[0]!.rotationReadOnlyReason).toBe('xlsx_rotation_inherited_style_unsupported')
})

it.each(['row', 'column', 'default', 'named', 'disabled', 'disabled-secondary'])('exposes the same indent read-only source gate for %s inherited styles', async source => {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  let sheet = await zip.file('xl/worksheets/sheet1.xml')!.async('string')
  let stylesheet = await zip.file('xl/styles.xml')!.async('string')
  if (source === 'row') sheet = sheet.replace(/<sheetData\s*\/>/, '<sheetData><row r="1" s="0" customFormat="1"/></sheetData>')
  if (source === 'column') sheet = sheet.replace('<sheetData', '<cols><col min="1" max="1" style="0"/></cols><sheetData')
  if (source === 'default' || source === 'disabled') stylesheet = stylesheet.replace(/(<cellXfs\b[^>]*>)<xf\b[^>]*\/>/, `$1<xf numFmtId="0" fontId="0" fillId="0" borderId="0"${source === 'disabled' ? ' applyAlignment="0"' : ''}><alignment indent="2"/></xf>`)
  if (source === 'named') stylesheet = stylesheet.replace(/(<cellStyleXfs\b[^>]*>)<xf\b[^>]*\/>/, '$1<xf numFmtId="0" fontId="0" fillId="0" borderId="0"><alignment indent="2"/></xf>')
  if (source === 'disabled-secondary') stylesheet = stylesheet.replace('</cellXfs>', '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="0"><alignment indent="2"/></xf></cellXfs>')
  zip.file('xl/worksheets/sheet1.xml', sheet)
  zip.file('xl/styles.xml', stylesheet)
  const model = await readWorkbook(await zip.generateAsync({ type: 'uint8array' }))
  expect(model.sheets[0]!.indentReadOnlyReason).toBe('xlsx_indent_inherited_style_unsupported')
})

it('leaves direct cell indent editable', async () => {
  expect((await readWorkbook(await createBlankWorkbook())).sheets[0]!.indentReadOnlyReason).toBeUndefined()
})
