import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addChart, createBlankPptx, openPptx, savePptx } from '../../packages/pptx-engine/src/index.ts'
import { applyChartEdits, inspectChartEdit, validateChartEdits, NATIVE_CHART_KINDS } from '../pptx-chart-edit.ts'

const style = { title: '收入😀 <&>', catAxisTitle: '月份', valAxisTitle: '万元', legendPos: 'r', dataLabels: true, gridlines: false }
async function fixture() {
  const opened = await openPptx(await createBlankPptx())
  addChart(opened, 0, { kind: 'bar', categories: ['1', '2'], series: [{ name: '收入', values: [42, 17] }, { name: '成本', values: [3, 4] }], offset: { x: 1, y: 2, cx: 4000000, cy: 3000000 } })
  const source = await openPptx(await savePptx(opened))
  return { opened: source, elementId: source.deck.slides[0]!.elements[0]!.id }
}

test('style-only patches preserve each pinned chart type and its data after reopening', async () => {
  for (const kind of NATIVE_CHART_KINDS) {
    const { opened, elementId } = await fixture()
    applyChartEdits(opened, validateChartEdits(opened, [{ slideIndex: 0, elementId, kind }]))
    const source = await openPptx(await savePptx(opened)), id = source.deck.slides[0]!.elements[0]!.id
    const before = inspectChartEdit(source, 0, id)
    applyChartEdits(source, validateChartEdits(source, [{ slideIndex: 0, elementId: id, ...style }]))
    const back = await openPptx(await savePptx(source)), actual = inspectChartEdit(back, 0, back.deck.slides[0]!.elements[0]!.id)
    assert.equal(actual.chartKind, kind)
    assert.deepEqual(actual.chartCategories, before.chartCategories)
    assert.deepEqual(actual.chartSeries, before.chartSeries)
    assert.equal(actual.chartStyle!.title, style.title)
    assert.equal(actual.chartStyle!.legendPos, 'r')
    if (!['pie', 'pie3D', 'doughnut'].includes(kind)) {
      assert.equal(actual.chartStyle!.catAxisTitle, '月份')
      assert.equal(actual.chartStyle!.valAxisTitle, '万元')
    }
  }
})

test('invalid style fields fail as a batch before mutating chart bytes', async () => {
  const { opened, elementId } = await fixture(), before = new Map(opened.archive.entries)
  for (const patch of [{ title: null }, { title: 'x'.repeat(1001) }, { title: '\ud800' }, { title: '\ufffe' }, { legendPos: 'tr' }, { dataLabels: 1 }, { gridlines: null }]) {
    assert.throws(() => validateChartEdits(opened, [{ slideIndex: 0, elementId, ...patch }]))
  }
  assert.deepEqual(opened.archive.entries, before)
})
