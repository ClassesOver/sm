import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addChart, createBlankPptx, openPptx, savePptx } from '../../packages/pptx-engine/src/index.ts'
import { applyChartEdits, inspectChartEdit, validateChartEdits, NATIVE_CHART_KINDS } from '../pptx-chart-edit.ts'

async function fixture() {
  const opened = await openPptx(await createBlankPptx())
  addChart(opened, 0, {kind:'bar',categories:['1','2'],series:[{name:'10',values:[1,2]},{name:'20',values:[3,4]}],pointColors:[['#FF0000']],offset:{x:1,y:2,cx:4000000,cy:3000000}})
  const source = await openPptx(await savePptx(opened))
  return { opened: source, elementId: source.deck.slides[0]!.elements[0]!.id }
}

test('design colors and widths preserve all 13 types, data and supported point overrides', async () => {
  for (const kind of NATIVE_CHART_KINDS) {
    const {opened,elementId}=await fixture()
    applyChartEdits(opened,validateChartEdits(opened,[{slideIndex:0,elementId,kind}]))
    const source=await openPptx(await savePptx(opened)),id=source.deck.slides[0]!.elements[0]!.id
    const before=inspectChartEdit(source,0,id)
    applyChartEdits(source,validateChartEdits(source,[{slideIndex:0,elementId:id,colorScheme:'warm',gapWidthPct:50}]))
    const back=await openPptx(await savePptx(source)),el=back.deck.slides[0]!.elements[0]!
    const actual=inspectChartEdit(back,0,el.id)
    assert.equal(actual.chartKind,kind)
    assert.deepEqual(actual.chartCategories,before.chartCategories)
    assert.deepEqual(actual.chartSeries,before.chartSeries)
    if(el.type!=='chart')throw Error('chart missing')
    assert.deepEqual(el.chart.series.map(s=>s.color),['#ED7D31','#FFC000'],kind)
    if(['bar','barH','bar3D','barStacked','barPercentStacked','comboBarLine'].includes(kind))assert.equal(el.chart.gapWidthPct,50,kind)
    if(kind!=='scatter')assert.equal(el.chart.series[0]!.pointColors?.[0],'#FF0000',kind)
  }
})

test('theme-derived palettes follow first-slide theme, rotate and tint pinned accents', async()=>{
  const {opened,elementId}=await fixture()
  const path=opened.archive.resolveSlideChain(opened.deck.slides[0]!.path).themePath!
  const xml=opened.archive.readText(path)!.replace(/(<a:accent1><a:srgbClr val=")[^"]+/, '$1123456')
  opened.archive.entries.set(path,Buffer.from(xml))
  const state=inspectChartEdit(opened,0,elementId)
  assert.equal(state.chartColorSchemes!.find(s=>s.key==='colorful')!.colors[0],'#123456')
  assert.equal(state.chartColorSchemes!.find(s=>s.key==='mono-accent1')!.colors[0],'#0E2741')
  applyChartEdits(opened,validateChartEdits(opened,[{slideIndex:0,elementId,colorScheme:'colorful'}]))
  const back=await openPptx(await savePptx(opened)),el=back.deck.slides[0]!.elements[0]!
  if(el.type!=='chart')throw Error('chart missing')
  assert.equal(el.chart.series[0]!.color,'#123456')
})

test('malformed palettes and gap values reject without changing archive', async()=>{
  const {opened,elementId}=await fixture(),before=new Map(opened.archive.entries)
  for(const patch of [{colorScheme:null},{colorScheme:''},{colorScheme:['#123456']},{colorScheme:'other'},{gapWidthPct:null},{gapWidthPct:true},{gapWidthPct:-1},{gapWidthPct:501},{gapWidthPct:1.5}])assert.throws(()=>validateChartEdits(opened,[{slideIndex:0,elementId,...patch}]))
  assert.deepEqual(opened.archive.entries,before)
})
