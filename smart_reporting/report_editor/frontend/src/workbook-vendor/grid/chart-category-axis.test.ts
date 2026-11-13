import {expect,it} from 'vitest'
import {chartCategoryLabels} from './chart-category-axis'

it('resolves a quoted one-row reference with apostrophe and exclamation in the actual sheet name',()=>{
 const values=['North',null,'South']
 const sheet={getName:()=>"O'Brien! Q",getCell:(row:number,column:number)=>({v:row===1?values[column]:undefined})}
 expect(chartCategoryLabels({valuesRef:'A1:A3',categoriesRef:"'O''Brien! Q'!$A$2:$C$2",categories:['OLD','OLD','OLD']},sheet,3)).toEqual(values)
})
it('does not flatten a two-dimensional source and does not invent ordinals for an unreadable category block',()=>{
 const sheet={getName:()=> 'Sheet',getCell:()=>({v:'WRONG'})}
 expect(chartCategoryLabels({valuesRef:'A1:A3',categoriesRef:'Sheet!A1:B2',categories:[]},sheet,3)).toEqual([null,null,null])
 expect(chartCategoryLabels({valuesRef:'A1:A3'},sheet,3)).toEqual(['1','2','3'])
})
it('does not revive stale labels when live cells become empty or a label reference is shorter than the data',()=>{
 const sheet={getName:()=> 'Sheet',getCell:()=>({v:''})}
 expect(chartCategoryLabels({valuesRef:'B1:B3',categoriesRef:'Sheet!A1:A2',categories:['OLD','OLD','OLD']},sheet,3)).toEqual([null,null,null])
})
