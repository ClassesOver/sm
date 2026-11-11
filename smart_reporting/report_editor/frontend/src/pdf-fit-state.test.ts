import { expect, it } from 'vitest'
import { fitPdfRows, PDF_ROW_GAP } from './pdf-fit-state'
import { spreadRows } from './genoffice-pdf-spread'
const page = (width: number,height: number) => ({width,height,chromeWidth:10,chromeHeight:36})
it('fits every surviving page, so a smaller selected page cannot hide a wider page', () => {
  const pages=[page(300,400),page(900,600),page(500,1400)]
  expect(fitPdfRows(pages,1,'width',910,1000)).toBe(1)
  expect(fitPdfRows(pages,1,'page',910,736)).toBe(.5)
  expect(fitPdfRows([pages[0],pages[2]],1,'width',910,1000)).toBe(1.8)
})
it('pairs adjacent visible pages with independent row widths rather than per-column maxima', () => {
  const pages=[page(900,500),page(100,500),page(100,500),page(900,500),page(600,500)]
  const scale=fitPdfRows(pages,2,'width',1036,1000)!
  expect(PDF_ROW_GAP).toBe(16);expect(scale).toBe(1)
  for(const row of spreadRows(pages.map((_,i)=>i),2)) expect(row.reduce((n,i)=>n+pages[i].width*scale+10,0)+(row.length-1)*16).toBeLessThanOrEqual(1036)
  expect(spreadRows([4,1,8],2)).toEqual([[4,1],[8]])
})
it('keeps borders, headings and gutters unscaled at fractional fit values', () => {
  const pages=[page(600,800),page(400,1000)]
  const scale=fitPdfRows(pages,2,'page',536,536)!
  expect(scale).toBe(.5)
  expect(1000*scale+2*10+16).toBe(536)
  expect(1000*scale+36).toBe(536)
})
it('reacts to viewport dimensions and rotated/display-unit page bounds without changing inputs', () => {
  const pages=[page(1200,400),page(400,800)], before=structuredClone(pages)
  expect(fitPdfRows(pages,1,'width',610,800)).toBe(.5)
  expect(fitPdfRows(pages,1,'width',1210,800)).toBe(1)
  expect(fitPdfRows(pages,1,'page',1210,436)).toBe(.5)
  expect(pages).toEqual(before)
})
it('defers hidden/empty layouts and rejects nonfinite or invalid page geometry', () => {
  expect(fitPdfRows([],1,'width',500,500)).toBeNull()
  expect(fitPdfRows([page(300,400)],1,'width',0,500)).toBeNull()
  expect(()=>fitPdfRows([page(0,400)],1,'width',500,500)).toThrow()
  expect(()=>fitPdfRows([page(300,400)],1,'width',Infinity,500)).toThrow()
})
it('retains pinned 10–800 percent limits when the available space cannot fit', () => {
  expect(fitPdfRows([page(1000,1000)],1,'page',1,1)).toBe(.1)
  expect(fitPdfRows([page(1,1)],1,'width',10000,10000)).toBe(8)
})
it('handles large page inventories without spreading unbounded arguments', () => {
  expect(fitPdfRows(Array.from({length:150000},()=>page(400,600)),2,'page',836,636)).toBe(1)
})
