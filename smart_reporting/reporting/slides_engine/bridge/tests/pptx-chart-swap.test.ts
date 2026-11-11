import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addChart, createBlankPptx, openPptx, savePptx } from '../../packages/pptx-engine/src/index.ts'
import { applyChartEdits, inspectChartEdit, validateChartEdits, NATIVE_CHART_KINDS } from '../pptx-chart-edit.ts'

async function fixture(kind: typeof NATIVE_CHART_KINDS[number] = 'bar', categories = ['1', '2', '3'], names = ['10', '20']) {
  const opened = await openPptx(await createBlankPptx())
  addChart(opened, 0, { kind: kind === 'barH' ? 'bar' : kind, ...(kind === 'barH' ? {barDir:'bar' as const} : {}), categories, series: names.map((name, i) => ({ name, values: categories.map((_, j) => 10 * i + j + 1) })), pointColors: [['FF0000', undefined, '00FF00'], [undefined, '0000FF']], offset: {x:1,y:2,cx:4000000,cy:3000000} })
  const source = await openPptx(await savePptx(opened))
  return { opened: source, elementId: source.deck.slides[0]!.elements[0]!.id }
}

test('native row/column switch preserves 13 kinds, style and transposes point colors', async () => {
  for (const kind of NATIVE_CHART_KINDS) {
    const { opened, elementId } = await fixture(kind)
    assert.equal(inspectChartEdit(opened, 0, elementId).chartKind, kind, `source ${kind}`)
    const sourceElement = opened.deck.slides[0]!.elements[0]!
    if (sourceElement.type !== 'chart') throw Error('chart missing')
    const sourceColors = sourceElement.chart.series.map(series => series.pointColors)
    applyChartEdits(opened, validateChartEdits(opened, [{slideIndex:0,elementId,switchRowCol:true,title:'行列交换',legendPos:'t'}]))
    const back = await openPptx(await savePptx(opened)), el = back.deck.slides[0]!.elements[0]!
    const state = inspectChartEdit(back, 0, el.id)
    assert.equal(state.chartKind, kind)
    assert.deepEqual(state.chartCategories, ['10', '20'])
    assert.deepEqual(state.chartSeries, [{name:'1',values:[1,11]},{name:'2',values:[2,12]},{name:'3',values:[3,13]}])
    assert.equal(state.chartStyle!.title, '行列交换')
    assert.equal(state.chartStyle!.legendPos, 't')
    if (el.type !== 'chart') throw Error('chart missing')
    // Scatter's fixed builder does not write dPt; compare the actual source, not requested colors.
    for (let si = 0; si < 3; si++) for (let ci = 0; ci < 2; ci++) {
      assert.equal(el.chart.series[si]!.pointColors?.[ci], sourceColors[ci]?.[si], `${kind} point ${si}:${ci}`)
    }
  }
})

test('explicit data is final orientation while native switch retains matching point colors', async () => {
  const { opened, elementId } = await fixture()
  const data = {categories:['10','20'],series:[{name:'1',values:[99,11]},{name:'2',values:[2,12]},{name:'3',values:[3,13]}]}
  applyChartEdits(opened, validateChartEdits(opened, [{slideIndex:0,elementId,switchRowCol:true,...data}]))
  const back = await openPptx(await savePptx(opened)), el = back.deck.slides[0]!.elements[0]!
  const state = inspectChartEdit(back, 0, el.id)
  assert.deepEqual(state.chartCategories, data.categories)
  assert.deepEqual(state.chartSeries, data.series)
  if (el.type !== 'chart') throw Error('chart missing')
  assert.equal(el.chart.series[2]!.pointColors?.[0], '#00FF00')
})

test('invalid switches or resulting data reject before archive mutation', async () => {
  const { opened, elementId } = await fixture(), before = new Map(opened.archive.entries)
  for (const value of [null, 0, 1, 'true', [], {}]) assert.throws(() => validateChartEdits(opened, [{slideIndex:0,elementId,switchRowCol:value}]))
  assert.deepEqual(opened.archive.entries, before)
  for (const [kind, categories, names] of [
    ['bar', Array.from({length:21},(_,i)=>String(i)), ['Revenue']],
    ['scatter', ['1','2'], ['Revenue']],
    ['comboBarLine', ['1'], ['10','20']],
  ] as [typeof NATIVE_CHART_KINDS[number],string[],string[]][]) {
    const f = await fixture(kind, categories, names), bytes = new Map(f.opened.archive.entries)
    assert.throws(() => validateChartEdits(f.opened, [{slideIndex:0,elementId:f.elementId,switchRowCol:true}]))
    assert.deepEqual(f.opened.archive.entries, bytes)
  }
})
