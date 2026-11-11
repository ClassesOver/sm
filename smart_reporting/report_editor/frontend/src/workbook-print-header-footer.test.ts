import { describe, expect, it } from 'vitest'
import { buildSheetPrintHtml, type SheetPrintSetup, type SheetPrintSource } from './workbook-print'

const source: SheetPrintSource = { name: 'Sheet <A>', cells: { A1: { value: 'one' }, A2: { value: 'two' }, A3: { value: 'three' } }, merges: [], columnWidths: {}, rowHeights: {}, hiddenRows: new Set(), hiddenColumns: new Set() }
const setup: SheetPrintSetup = { orientation: 'portrait', paperSize: 9, scale: 100, fitToPage: false, fitToWidth: 0, fitToHeight: 0, margins: { left: 0.7, right: 0.7, top: 0.75, bottom: 0.75 }, printGridlines: false, printHeadings: false, printArea: null, printTitles: null, rowBreaks: [1, 2], colBreaks: [] }
const now = new Date(2026, 10, 11, 13, 14, 15)
const render = (headerFooter: SheetPrintSetup['headerFooter'], options: Partial<SheetPrintSetup> = {}) => new DOMParser().parseFromString(buildSheetPrintHtml(source, { ...setup, ...options, headerFooter }, { fileName: 'File <book>.xlsx', now })!, 'text/html')
const texts = (doc: Document, selector: string) => [...doc.querySelectorAll(selector)].map(node => node.textContent)

describe('print file header/footer text', () => {
  it('renders actual page and total fields into independent left/center/right sections', () => {
    const doc = render({ oddHeader: '&LLeft&CPage &P of &N&R&A', oddFooter: '&C&F && &[Page]+2/&[Pages] &Q' })
    expect(doc.querySelectorAll('.page')).toHaveLength(3)
    expect(texts(doc, '.page:nth-child(2) .hf-header span')).toEqual(['Left', 'Page 2 of 3', 'Sheet <A>'])
    expect(texts(doc, '.page:nth-child(3) .hf-footer span')).toEqual(['', 'File <book>.xlsx & 5/3 &Q', ''])
  })

  it('chooses first page before parity and keeps explicitly blank variants blank', () => {
    const doc = render({ oddHeader: '&COdd &P', oddFooter: '&CDefault', differentFirst: true, firstHeader: '&CFirst &P', differentOddEven: true, evenFooter: '&CEven &P' })
    expect(texts(doc, '.page:nth-child(1) .hf-header')).toEqual(['First 1'])
    expect(doc.querySelector('.page:nth-child(1) .hf-footer')).toBeNull()
    expect(doc.querySelector('.page:nth-child(2) .hf-header')).toBeNull()
    expect(texts(doc, '.page:nth-child(2) .hf-footer')).toEqual(['Even 2'])
    expect(texts(doc, '.page:nth-child(3) .hf-header')).toEqual(['Odd 3'])
  })

  it('ignores stored variants when flags are disabled and counts pages across print areas', () => {
    const doc = render({ oddHeader: '&P/&N', firstHeader: 'hidden first', evenHeader: 'hidden even' }, { printArea: 'A1:A1,A3:A3', rowBreaks: [] })
    expect(texts(doc, '.hf-header')).toEqual(['1/2', '2/2'])
    expect(doc.body.textContent).not.toContain('hidden')
  })

  it('expands date/time once per job, strips source formatting controls and omits pictures', () => {
    const doc = render({ oddHeader: '&L&"Arial,Bold"&12&BDate &D &T&C&G&Z&R&&P &P-1' })
    expect(texts(doc, '.page:first-child .hf-header span')).toEqual([`Date ${now.toLocaleDateString()} ${now.toLocaleTimeString()}`, '', '&P 0'])
    expect(doc.querySelector('.hf img')).toBeNull()
  })

  it('escapes raw text and expanded fields without treating them as markup or code', () => {
    const doc = render({ oddHeader: '&L<script>throw 1</script>&C&F&R&A' })
    expect(texts(doc, '.page:first-child .hf-header span')).toEqual(['<script>throw 1</script>', 'File <book>.xlsx', 'Sheet <A>'])
    expect(doc.querySelectorAll('script, book')).toHaveLength(0)
  })

  it('uses file header/footer distances and document scale unless fixed-size is requested', () => {
    for (const scaleWithDoc of [undefined, false]) {
      const doc = render({ oddHeader: 'Top', oddFooter: 'Bottom', scaleWithDoc }, { scale: 50, margins: { left: 0.4, right: 0.6, top: 0.75, bottom: 0.75, header: 0.2, footer: 0.25 } })
      const header = doc.querySelector<HTMLElement>('.hf-header')!
      const footer = doc.querySelector<HTMLElement>('.hf-footer')!
      expect(header.style.top).toBe('0.2in')
      expect(footer.style.bottom).toBe('0.25in')
      expect(header.style.left).toBe('0.4in')
      expect(header.style.right).toBe('0.6in')
      expect(header.style.fontSize).toBe(scaleWithDoc === false ? '9pt' : '4.5pt')
    }
  })

  it('leaves documents without file header/footer free of empty strips', () => {
    expect(render(undefined).querySelector('.hf')).toBeNull()
    expect(render({ oddHeader: '&G' }).querySelector('.hf img')).toBeNull()
  })
})
