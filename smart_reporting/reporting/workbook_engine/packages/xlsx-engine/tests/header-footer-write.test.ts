import { describe, expect, it } from 'vitest'
import { applyPageSetupState, applyPageSetups } from '../src/page-setup'
import { createBlankWorkbook } from '../src/blank'
import { readWorkbook } from '../src/workbook-read'

const NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

describe('header/footer surgical write', () => {
  it('round-trips literal XLSX escapes and control text through a real package', async () => {
    const text = 'Literal _x0041_ and control \u0001'
    const bytes = await applyPageSetups(await createBlankWorkbook(), [{ sheetName: 'Sheet1', header: { center: text } }])
    expect((await readWorkbook(bytes)).sheets[0]!.headerFooter?.oddHeader).toBe('&C' + text)
  })

  it('edits prefixed odd text and preserves first/even, flags and unedited codes verbatim', () => {
    const before = `<m:worksheet xmlns:m="${NS}"><m:sheetData/><m:headerFooter differentFirst="1" differentOddEven="1" scaleWithDoc="0"><m:oddHeader>&amp;COLD</m:oddHeader><m:oddFooter>&amp;L&amp;"Arial,Bold"&amp;12&amp;KFF0000&amp;Z&amp;F</m:oddFooter><m:evenHeader>&amp;CEVEN</m:evenHeader><m:firstFooter>&amp;CFIRST</m:firstFooter></m:headerFooter><m:rowBreaks/></m:worksheet>`
    expect(applyPageSetupState(before, { sheetName: 'Sheet1', header: { center: 'New &P' } })).toBe(before.replace('<m:oddHeader>&amp;COLD</m:oddHeader>', '<m:oddHeader>&amp;CNew &amp;P</m:oddHeader>'))
  })

  it('ignores nested and foreign same-name nodes and inserts in the worksheet namespace', () => {
    const foreign = '<headerFooter xmlns="urn:foreign"><oddHeader>FOREIGN</oddHeader></headerFooter>'
    const nested = '<m:extLst><m:ext uri="test"><m:headerFooter><m:oddHeader>NESTED</m:oddHeader></m:headerFooter></m:ext></m:extLst>'
    const before = `<m:worksheet xmlns:m="${NS}"><m:sheetData/>${foreign}${nested}</m:worksheet>`
    const expected = before.replace(nested, '<m:headerFooter><m:oddHeader>&amp;CNEW</m:oddHeader></m:headerFooter>' + nested)
    expect(applyPageSetupState(before, { sheetName: 'Sheet1', header: { center: 'NEW' } })).toBe(expected)
  })

  it('preserves foreign children and clears only the real direct odd header', () => {
    const before = `<worksheet xmlns="${NS}"><sheetData/><headerFooter differentFirst="1"><oddHeader xmlns="urn:foreign">KEEP</oddHeader><oddHeader>&amp;COLD</oddHeader><firstHeader>&amp;CFIRST</firstHeader></headerFooter></worksheet>`
    expect(applyPageSetupState(before, { sheetName: 'Sheet1', header: null })).toBe(before.replace('<oddHeader>&amp;COLD</oddHeader>', ''))
  })
})
