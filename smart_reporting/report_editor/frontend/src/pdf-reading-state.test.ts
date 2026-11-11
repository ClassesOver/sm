import { expect, it } from 'vitest'
import { nativeDraftKey } from './native-draft'
import { pdfReadingKey, capturePdfReading, restorePdfReading, pdfReadingRows } from './pdf-reading-state'
import { loadViewState, saveViewState, VIEW_STATE_KEY, MAX_VIEW_ENTRIES } from './genoffice-pdf-reading-state'
const identity = { documentId: 'doc', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
const view = { page: 2, frac: .35, scale: 1.25, fitMode: null }
it('isolates reading entries by all immutable source/scope fields without sharing the draft key', () => {
  const key = pdfReadingKey(identity)
  expect(key).not.toBe(nativeDraftKey(identity))
  for (const field of ['documentId','revision','sourceSha256'] as const) expect(pdfReadingKey({ ...identity, [field]: 'different' } as typeof identity)).not.toBe(key)
  for (const field of ['database','companyId','userId','threadId']) expect(pdfReadingKey({ ...identity, scope: { ...identity.scope, [field]: 'different' } })).not.toBe(key)
})
it('uses source sanitization and best-effort storage without breaking reads or writes', () => {
  const storage = { getItem: () => { throw Error('blocked') }, setItem: () => { throw Error('quota') } }
  expect(loadViewState('doc',storage)).toBeNull(); expect(() => saveViewState('doc',view,storage)).not.toThrow()
  const data = { doc: { ...view, page: 2.9, frac: 9, at: 1 } }, valid = { getItem: () => JSON.stringify(data), setItem() {} }
  expect(loadViewState('doc',valid)).toMatchObject({ page: 2, frac: 1 })
  expect(loadViewState('doc',{ ...valid, getItem: () => '{bad' })).toBeNull()
  expect(loadViewState('doc',{ ...valid, getItem: () => JSON.stringify({doc:{ ...view,fitMode:'unknown' }}) })).toBeNull()
})
it('retains the source 100-entry least-recently-saved pruning bound', () => {
  let encoded: string | null = null
  const storage = { getItem: () => encoded, setItem: (_: string,v: string) => {encoded=v} }
  for (let i=0;i<=MAX_VIEW_ENTRIES;i++) saveViewState(`doc${i}`,view,storage,i)
  expect(Object.keys(JSON.parse(encoded!))).toHaveLength(100)
  expect(loadViewState('doc0',storage)).toBeNull(); expect(loadViewState('doc100',storage)).toEqual(view)
  expect(VIEW_STATE_KEY).toBe('genoffice-pdf-view-state')
})
function fixture(ids=['b','a','c']) {
  const viewport=document.createElement('div');document.body.replaceChildren(viewport)
  let factor=1, spread=false
  viewport.getBoundingClientRect=()=>new DOMRect(20,100,600,500)
  for(const [i,id] of ids.entries()){
    const page=document.createElement('section');page.className='pdf-page';page.dataset.pageId=id;viewport.append(page)
    page.getBoundingClientRect=()=>new DOMRect(20,100+(16+(spread?Math.floor(i/2):i)*1020)*factor-viewport.scrollTop,300,(id==='a'?1100:1000)*factor)
  }
  return {viewport,resize:()=>{factor=2},spread:()=>{spread=true}}
}
it('captures original page identity through reordered DOM and restores proportional geometry after resize', () => {
  const f=fixture();f.viewport.scrollTop=16+350
  const saved=capturePdfReading(f.viewport,['a','b','c'],1.25,null)!
  expect(saved).toEqual(view)
  f.resize();f.viewport.scrollTop=0
  expect(restorePdfReading(f.viewport,['a','b','c'],saved)).toBe('b')
  expect(f.viewport.scrollTop).toBe(32+700)
})
it('groups spread rows by actual DOM top and preserves the right-page target in its row', () => {
  const f=fixture(['a','b','c']);f.spread();f.viewport.scrollTop=500
  expect(pdfReadingRows(f.viewport,['a','b','c'])).toHaveLength(2)
  expect(pdfReadingRows(f.viewport,['a','b','c'])[0].height).toBe(1100)
  expect(restorePdfReading(f.viewport,['a','b','c'],view)).toBe('a')
  expect(f.viewport.scrollTop).toBe(16+.35*1100)
})
it('falls back to the first surviving row without borrowing a deleted page fraction', () => {
  const f=fixture(['a','c']);f.viewport.scrollTop=500
  expect(restorePdfReading(f.viewport,['a','b','c'],view)).toBe('a');expect(f.viewport.scrollTop).toBe(0)
})
it('does not invent a position for empty or unmeasurable layouts', () => {
  const f=fixture([]);f.viewport.scrollTop=8
  expect(capturePdfReading(f.viewport,['a'],1,null)).toBeNull()
  expect(restorePdfReading(f.viewport,['a'],view)).toBeNull();expect(f.viewport.scrollTop).toBe(8)
})
