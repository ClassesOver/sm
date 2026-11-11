import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

const MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
async function workbookWithWorksheet(xml: string) {
  return (await assemblePackage(await createBlankWorkbook(), {
    replaced: new Map([['xl/worksheets/sheet1.xml', xml]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: ['xl/worksheets/sheet1.xml'],
  })).buffer
}

it('reads all header/footer variants with XML and OOXML escapes decoded exactly once', async () => {
  const bytes = await workbookWithWorksheet(`<worksheet xmlns="${MAIN}"><sheetData/><headerFooter differentFirst="1" differentOddEven="true" scaleWithDoc="false"><oddHeader>&amp;L&lt;title&gt;&amp;C&amp;P/&amp;N_x000A_中文_x005F_x0041_ &amp;amp;</oddHeader><oddFooter>&amp;F &amp;A</oddFooter><firstHeader/><firstFooter>first</firstFooter><evenHeader>even</evenHeader><evenFooter><![CDATA[&Craw <text>]]></evenFooter></headerFooter></worksheet>`)
  expect((await readWorkbook(bytes)).sheets[0]).toHaveProperty('headerFooter', {
    differentFirst: true, differentOddEven: true, scaleWithDoc: false,
    oddHeader: '&L<title>&C&P/&N' + String.fromCharCode(10) + '中文_x0041_ &amp;', oddFooter: '&F &A',
    firstHeader: '', firstFooter: 'first', evenHeader: 'even', evenFooter: '&Craw <text>',
  })
})

it('accepts alias main prefixes but ignores foreign and nested lookalikes', async () => {
  const bytes = await workbookWithWorksheet(`<s:worksheet xmlns:s="${MAIN}" xmlns:f="urn:foreign"><s:sheetData/><f:headerFooter differentFirst="1"><f:oddHeader>foreign</f:oddHeader></f:headerFooter><s:extLst><s:ext uri="foreign"><s:headerFooter><s:oddHeader>nested</s:oddHeader></s:headerFooter></s:ext></s:extLst><s:headerFooter differentFirst="0" scaleWithDoc="1"><f:oddHeader>wrong namespace</f:oddHeader><s:oddHeader>&amp;CReal</s:oddHeader><s:oddFooter>&amp;T</s:oddFooter></s:headerFooter></s:worksheet>`)
  expect((await readWorkbook(bytes)).sheets[0]).toHaveProperty('headerFooter', { differentFirst: false, scaleWithDoc: true, oddHeader: '&CReal', oddFooter: '&T' })
})

it('omits missing flags and preserves raw XML on unrelated actual workbook edits', async () => {
  const header = '<headerFooter><oddHeader>&amp;C&amp;P</oddHeader><evenFooter/></headerFooter>'
  const bytes = await workbookWithWorksheet(`<worksheet xmlns="${MAIN}"><sheetData/>${header}</worksheet>`)
  expect((await readWorkbook(bytes)).sheets[0]).toHaveProperty('headerFooter', { oddHeader: '&C&P', evenFooter: '' })
  const changed = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'unrelated' } }])
  expect(await (await createBufferEntrySource(changed)).readText('xl/worksheets/sheet1.xml')).toContain(header)
  expect((await readWorkbook(await createBlankWorkbook())).sheets[0]).not.toHaveProperty('headerFooter')
})

it('does not invent file headers from extensions or foreign namespaces', async () => {
  const bytes = await workbookWithWorksheet(`<worksheet xmlns="${MAIN}" xmlns:f="urn:foreign"><sheetData/><f:headerFooter><oddHeader>foreign parent</oddHeader></f:headerFooter><extLst><ext uri="foreign"><headerFooter><oddHeader>nested</oddHeader></headerFooter></ext></extLst></worksheet>`)
  expect((await readWorkbook(bytes)).sheets[0]).not.toHaveProperty('headerFooter')
})
