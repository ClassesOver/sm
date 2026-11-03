import { describe, expect, it } from 'vitest'

import {
  applyPageSetupState,
  applyPrintAreas,
  applyProtectedRanges,
  applySheetProtection,
  applyWorkbookProtection,
  buildHeaderFooterXml,
  PageSetupError,
  SheetProtectionError,
} from '../src'

const SHEET_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
  '<sheetViews><sheetView workbookViewId="0"/></sheetViews>' +
  '<sheetFormatPr defaultRowHeight="15"/>' +
  '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>v</t></is></c></row></sheetData>' +
  '</worksheet>'

const WORKBOOK_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
  '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>' +
  '</workbook>'

describe('sheet/workbook protection', () => {
  it('toggles sheetProtection idempotently and strips it on unprotect', () => {
    const protectedOnce = applySheetProtection(SHEET_XML, true)
    expect(protectedOnce).toContain('<sheetProtection sheet="1" objects="1" scenarios="1"/>')
    expect(protectedOnce.indexOf('</sheetData>')).toBeLessThan(
      protectedOnce.indexOf('<sheetProtection'),
    ) // schema order: right after sheetData
    // idempotent
    expect(applySheetProtection(protectedOnce, true)).toBe(protectedOnce)
    // unprotect removes it
    expect(applySheetProtection(protectedOnce, false)).toBe(SHEET_XML)
  })

  it('fails closed on password-protected sheets and ranges', () => {
    const withPassword = SHEET_XML.replace(
      '</sheetData>',
      '</sheetData><sheetProtection sheet="1" password="AB12"/>',
    )
    expect(() => applySheetProtection(withPassword, false)).toThrow(SheetProtectionError)
    const withHashRanges = SHEET_XML.replace(
      '</sheetData>',
      '</sheetData><protectedRanges><protectedRange password="AB12" sqref="A1" name="R1"/></protectedRanges>',
    )
    expect(() => applyProtectedRanges(withHashRanges, [])).toThrow(/not supported/)
  })

  it('locks workbook structure in workbook.xml and strips lock on unlock', () => {
    const locked = applyWorkbookProtection(WORKBOOK_XML, true)
    expect(locked).toContain('<workbookProtection lockStructure="1"/>')
    expect(locked.indexOf('<workbookProtection')).toBeLessThan(locked.indexOf('<sheets'))
    expect(applyWorkbookProtection(locked, true)).toBe(locked)
    expect(applyWorkbookProtection(locked, false)).toBe(WORKBOOK_XML)
    // a password-protected structure refuses unlock
    const pw =
      WORKBOOK_XML.replace('<sheets>', '<workbookProtection workbookPassword="AB" lockStructure="1"/><sheets>')
    expect(() => applyWorkbookProtection(pw, false)).toThrow(SheetProtectionError)
  })

  it('replaces allow-edit ranges and removes the element when empty', () => {
    const withRanges = applyProtectedRanges(SHEET_XML, [
      { name: 'Input', sqref: 'B2:C4' },
    ])
    expect(withRanges).toContain('<protectedRanges><protectedRange sqref="B2:C4" name="Input"/>')
    expect(applyProtectedRanges(withRanges, [])).toBe(SHEET_XML)
  })
})

describe('page setup', () => {
  it('merges pageSetup attrs, margins, and print options in schema order', () => {
    const xml = applyPageSetupState(SHEET_XML, {
      sheetName: 'Sheet1',
      orientation: 'landscape',
      scale: 80,
      margins: 'narrow',
      printGridlines: true,
    })
    expect(xml).toContain('<pageSetup orientation="landscape" scale="80"/>')
    expect(xml).toContain(
      '<pageMargins left="0.25" right="0.25" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>',
    )
    expect(xml).toContain('<printOptions gridLines="1"/>')
    // printOptions precedes pageMargins precedes pageSetup
    expect(xml.indexOf('<printOptions')).toBeLessThan(xml.indexOf('<pageMargins'))
    expect(xml.indexOf('<pageMargins')).toBeLessThan(xml.indexOf('<pageSetup'))
  })

  it('drops default values (scale=100, fitToWidth=1) and toggles fitToPage via sheetPr', () => {
    const withPr = applyPageSetupState(SHEET_XML, { sheetName: 'Sheet1', fitToPage: true, fitToWidth: 2 })
    expect(withPr).toContain('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
    expect(withPr).toContain('<pageSetup fitToWidth="2"/>')
    // fitToWidth=1 is the default: nothing to write in pageSetup
    const defaultWidth = applyPageSetupState(SHEET_XML, { sheetName: 'Sheet1', fitToPage: true, fitToWidth: 1 })
    expect(defaultWidth).not.toContain('<pageSetup')
    const back = applyPageSetupState(withPr, { sheetName: 'Sheet1', fitToPage: false })
    expect(back).not.toContain('fitToPage') // the flag is stripped; an empty <pageSetUpPr/> shell may remain (upstream parity)
    const defaults = applyPageSetupState(SHEET_XML, { sheetName: 'Sheet1', scale: 100 })
    expect(defaults).toBe(SHEET_XML) // nothing left to write
  })

  it('writes header/footer with escaped field codes and clears on null', () => {
    const xml = applyPageSetupState(SHEET_XML, {
      sheetName: 'Sheet1',
      header: { center: '第 &P 页' },
      footer: { left: 'Sheet && 1' },
    })
    expect(xml).toContain('<headerFooter><oddHeader>&amp;C第 &amp;P 页</oddHeader>' +
      '<oddFooter>&amp;LSheet &amp;&amp; 1</oddFooter></headerFooter>')
    const cleared = applyPageSetupState(xml, { sheetName: 'Sheet1', header: null, footer: null })
    expect(cleared).not.toContain('<headerFooter')
  })

  it('rewrites manual page breaks and frozen panes', () => {
    const xml = applyPageSetupState(SHEET_XML, {
      sheetName: 'Sheet1',
      rowBreaks: [3, 1, 3],
      colBreaks: [2],
      frozenRows: 1,
      frozenColumns: 0,
    })
    expect(xml).toContain('<rowBreaks count="2" manualBreakCount="2"><brk id="1" max="16383" man="1"/><brk id="3" max="16383" man="1"/></rowBreaks>')
    expect(xml).toContain('<colBreaks count="1" manualBreakCount="1"><brk id="2" max="1048575" man="1"/></colBreaks>')
    expect(xml).toContain('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>')
    // clearing breaks removes the elements
    const cleared = applyPageSetupState(xml, { sheetName: 'Sheet1', rowBreaks: [], colBreaks: [] })
    expect(cleared).not.toContain('<rowBreaks')
    expect(cleared).not.toContain('<colBreaks')
  })

  it('maintains sheet-scoped Print_Area / Print_Titles defined names', () => {
    const workbook = applyPrintAreas(WORKBOOK_XML, [
      { sheetName: 'Sheet1', printArea: 'A1:C10', printTitles: '1:2' },
    ])
    expect(workbook).toContain(
      '<definedName name="_xlnm.Print_Area" localSheetId="0">\'Sheet1\'!$A$1:$C$10</definedName>',
    )
    expect(workbook).toContain(
      '<definedName name="_xlnm.Print_Titles" localSheetId="0">\'Sheet1\'!$1:$2</definedName>',
    )
    // clearing both drops the whole section
    const cleared = applyPrintAreas(workbook, [
      { sheetName: 'Sheet1', printArea: null, printTitles: null },
    ])
    expect(cleared).not.toContain('<definedNames')
    // invalid input fails closed
    expect(() =>
      applyPrintAreas(WORKBOOK_XML, [{ sheetName: 'Nope', printArea: 'A1:B2' }]),
    ).toThrow(PageSetupError)
    expect(() =>
      applyPrintAreas(WORKBOOK_XML, [{ sheetName: 'Sheet1', printTitles: '5:2' }]),
    ).toThrow(PageSetupError)
  })

  it('encodes header/footer field codes via the standalone builder', () => {
    expect(buildHeaderFooterXml({ center: '&A' }, null)).toBe(
      '<headerFooter><oddHeader>&amp;C&amp;A</oddHeader></headerFooter>',
    )
    expect(buildHeaderFooterXml(undefined, undefined)).toBe('')
  })
})
