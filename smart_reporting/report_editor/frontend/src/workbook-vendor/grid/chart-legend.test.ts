import { expect, it } from 'vitest'
import { chartLegendName } from './chart-legend'

it('resolves only same-sheet single-cell names, preserves literals and falls back to source caches', () => {
 const worksheet={getName:()=>"Owner's Data!",getCell:()=>({v:'Live heading'})}
 expect(chartLegendName({nameRef:"'Owner''s Data!'!$B$1",nameCache:'Stale',valuesRef:'B2:B3'},0,worksheet)).toBe('Live heading')
 expect(chartLegendName({name:'Sheet1!B1',valuesRef:'B2:B3'},0,worksheet)).toBe('Sheet1!B1')
 for(const nameRef of ['Other!B1',"'[book.xlsx]Sheet1'!B1",'INDIRECT("B1")','B1:B2']) {
  expect(chartLegendName({nameRef,nameCache:'Cached heading',valuesRef:'B2:B3'},0,worksheet)).toBe('Cached heading')
 }
 expect(chartLegendName({nameRef:'Other!B1',valuesRef:'B2:B3'},1,worksheet)).toBe('系列 2')
})
