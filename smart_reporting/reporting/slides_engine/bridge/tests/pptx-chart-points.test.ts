import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addChart, createBlankPptx, openPptx, savePptx } from '../../packages/pptx-engine/src/index.ts'
import { applyChartEdits, inspectChartEdit, validateChartEdits } from '../pptx-chart-edit.ts'

async function fixture() {
  const opened = await openPptx(await createBlankPptx())
  addChart(opened, 0, {kind:'bar',categories:['甲','乙'],series:[{name:'收入',values:[1,2]}],pointColors:[['#FF0000']],offset:{x:1,y:2,cx:4000000,cy:3000000}})
  const source = await openPptx(await savePptx(opened))
  return { opened: source, elementId: source.deck.slides[0]!.elements[0]!.id }
}

test('visible point indices inverse-project before native swap and null removes only that override',async()=>{
  const {opened,elementId}=await fixture()
  applyChartEdits(opened,validateChartEdits(opened,[{slideIndex:0,elementId,switchRowCol:true,pointColors:{1:{0:'#123ABC'}}}]))
  const back=await openPptx(await savePptx(opened)), id=back.deck.slides[0]!.elements[0]!.id
  assert.deepEqual(inspectChartEdit(back,0,id).chartPointColors,[['#FF0000'],['#123ABC']])
  applyChartEdits(back,validateChartEdits(back,[{slideIndex:0,elementId:id,pointColors:{1:{0:null}}}]))
  const reset=await openPptx(await savePptx(back))
  assert.deepEqual(inspectChartEdit(reset,0,reset.deck.slides[0]!.elements[0]!.id).chartPointColors,[['#FF0000'],[null]])
})

test('all supported native types preserve explicit point colors without replacing chart data',async()=>{
  for(const kind of ['bar','barH','barStacked','barPercentStacked','bar3D','line','area','pie','pie3D','doughnut','radar','comboBarLine']){
    const {opened,elementId}=await fixture()
    const extra=kind==='comboBarLine'?{categories:['甲','乙'],series:[{name:'收入',values:[1,2]},{name:'成本',values:[3,4]}]}:{}
    applyChartEdits(opened,validateChartEdits(opened,[{slideIndex:0,elementId,kind,...extra,pointColors:{0:{1:'#123ABC'}}}]))
    const back=await openPptx(await savePptx(opened)),state=inspectChartEdit(back,0,back.deck.slides[0]!.elements[0]!.id)
    assert.equal(state.chartKind,kind)
    assert.deepEqual(state.chartPointColors?.[0],['#FF0000','#123ABC'])
    assert.deepEqual(state.chartSeries?.[0],{name:'收入',values:[1,2]})
  }
})

test('invalid or out-of-range point colors and unsupported scatter reject before any mutation',async()=>{
  const {opened,elementId}=await fixture(),before=new Map(opened.archive.entries)
  for(const patch of [{pointColors:{}},{pointColors:{0:{0:'red'}}},{pointColors:{0:{2:'#123456'}}},{pointColors:{1:{0:null}}},{pointColors:{'01':{0:'#123456'}}},{pointColors:{0:{0:'#123456'}},kind:'scatter'}]){
    assert.throws(()=>validateChartEdits(opened,[{slideIndex:0,elementId,...patch}]))
  }
  assert.deepEqual(opened.archive.entries,before)
})
