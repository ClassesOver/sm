import assert from 'node:assert/strict'
import {test} from 'node:test'
import {tableGridOptions} from '../vendor/pdf2docx/src/rebuild-pptx/table'
import type {TableBlock} from '../vendor/pdf2docx/src/ir'
for(const [alignment,x0,x1,inset]of [['left',10,60,10],['center',75,125,0],['right',140,195,5]] as const){
 test('table '+alignment+' anchor retains cell flow space instead of glyph-ink width',()=>{
  const box={x0:0,y0:0,x1:200,y1:35},ink={x0,y0:12,x1,y1:23}
  const block={kind:'text',box:ink,align:'left',dir:'ltr',lines:[{box:ink,spans:[{text:'12345.67',fontSize:11,fontFamily:'Arial',color:'000000',script:'latin'}]}]}
  const table={kind:'table',box,colWidthsPt:[200],rows:[[{box,gridSpan:1,blocks:[block]}]]} as unknown as TableBlock
  const result=tableGridOptions(table,{rect:()=>({x:0,y:0,cx:200,cy:35}),len:value=>value,scale:1}),cell=result.cells[0]![0]!
  assert.equal(cell.marginsEmu?.l,inset);assert.equal(cell.marginsEmu?.r,inset)
  assert.ok(200-cell.marginsEmu!.l-cell.marginsEmu!.r>=180)
  assert.equal(cell.paragraphs?.[0]?.align,alignment==='left'?undefined:alignment)
 })
}
