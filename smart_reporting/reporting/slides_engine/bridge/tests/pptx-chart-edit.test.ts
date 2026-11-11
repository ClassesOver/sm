import assert from 'node:assert/strict'
import { test } from 'node:test'
import JSZip from 'jszip'
import { spawnSync } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { addChart, createBlankPptx, duplicateSlide, openPptx, savePptx } from '../../packages/pptx-engine/src/index.ts'
import { applyChartEdits, inspectChartEdit, validateChartEdits } from '../pptx-chart-edit.ts'

async function fixture(kind = 'bar') {
  const opened = await openPptx(await createBlankPptx())
  addChart(opened, 0, { kind: kind as never, categories: ['甲', '乙'], series: [{ name: '收入', values: [1, 2] }, { name: '成本', values: [3, 4] }], offset: { x: 100, y: 200, cx: 4000000, cy: 3000000 } })!
  const back = await openPptx(await savePptx(opened))
  return { opened: back, elementId: back.deck.slides[0]!.elements.find(el => el.type === 'chart')!.id }
}

test('native edits update categories, series and the existing workbook while preserving unrelated ZIP parts', async () => {
  const { opened } = await fixture()
  const original = await openPptx(await savePptx(opened))
  const elementId = original.deck.slides[0]!.elements[0]!.id
  const before = new Map(original.archive.entries)
  const edit = { slideIndex: 0, elementId, categories: ['一月', '二月', '三月'], series: [{ name: '', values: [9, -2.5, 0] }], kind: 'line' }
  assert.equal(inspectChartEdit(original, 0, elementId).chartEditSafe, true)
  applyChartEdits(original, validateChartEdits(original, [edit]))
  const back = await openPptx(await savePptx(original))
  const state = inspectChartEdit(back, 0, back.deck.slides[0]!.elements[0]!.id)
  assert.equal(state.chartKind, 'line')
  assert.deepEqual(state.chartCategories, edit.categories)
  assert.deepEqual(state.chartSeries, edit.series)
  const changed = [...before].filter(([path, bytes]) => !Buffer.from(bytes).equals(Buffer.from(back.archive.entries.get(path)!))).map(([path]) => path)
  assert.equal(changed.filter(path => path.startsWith('ppt/embeddings/')).length, 1)
  assert.equal(changed.filter(path => path.startsWith('ppt/charts/chart') && path.endsWith('.xml')).length, 1)
  assert.ok(changed.every(path => path.startsWith('ppt/charts/') || path.startsWith('ppt/embeddings/')))
  const directory = await mkdtemp(join(tmpdir(), 'native-chart-edit-'))
  try {
    const sourcePath = join(directory, 'edited.pptx')
    await writeFile(sourcePath, await savePptx(original))
    const check = spawnSync('/home/junge/pros/smart_reporting/.venv/bin/python', ['-c', 'from pptx import Presentation; import sys, json; p=Presentation(sys.argv[1]); c=next(s.chart for s in p.slides[0].shapes if s.has_chart); print(json.dumps({"type": str(c.chart_type), "categories": [x.label for x in c.plots[0].categories], "series": [[v for v in x.values] for x in c.series]}))', sourcePath], { encoding: 'utf8' })
    assert.equal(check.status, 0, check.stderr)
    assert.deepEqual(JSON.parse(check.stdout), { type: 'LINE_MARKERS (65)', categories: ['一月', '二月', '三月'], series: [[9, -2.5, 0]] })
    const zip = await JSZip.loadAsync(await readFile(sourcePath))
    assert.ok(zip.file('ppt/embeddings/Microsoft_Excel_Worksheet1.xlsx'))
    const embedded = await JSZip.loadAsync(await zip.file('ppt/embeddings/Microsoft_Excel_Worksheet1.xlsx')!.async('uint8array'))
    const cells = await embedded.file('xl/worksheets/sheet1.xml')!.async('string')
    const strings = await embedded.file('xl/sharedStrings.xml')!.async('string')
    for (const text of ['一月', '二月', '三月']) assert.ok(strings.includes(text), `${text}: ${strings}`)
    for (const text of ['9', '-2.5']) assert.ok(cells.includes(text), `${text}: ${cells}`)
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('all pinned gallery types preserve their type through data-only editing', async () => {
  for (const kind of ['bar', 'bar3D', 'barStacked', 'barPercentStacked', 'barH', 'line', 'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine']) {
    const { opened, elementId } = await fixture()
    applyChartEdits(opened, validateChartEdits(opened, [{ slideIndex: 0, elementId, kind, ...(kind === 'scatter' ? { categories: ['1', '2'], series: [{ name: 'A', values: [1, 2] }, { name: 'B', values: [3, 4] }] } : {}) }]))
    const back = await openPptx(await savePptx(opened))
    const backId = back.deck.slides[0]!.elements[0]!.id
    assert.equal(inspectChartEdit(back, 0, backId).chartKind, kind)
    applyChartEdits(back, validateChartEdits(back, [{ slideIndex: 0, elementId: backId, categories: ['1', '2'], series: [{ name: 'A', values: [4, 5] }, { name: 'B', values: [6, 7] }] }]))
    const final = await openPptx(await savePptx(back))
    assert.equal(inspectChartEdit(final, 0, final.deck.slides[0]!.elements[0]!.id).chartKind, kind)
  }
})

test('external charts, extensions, malformed data and deleted targets fail before mutation', async () => {
  const { opened, elementId } = await fixture()
  for (const patch of [{}, { categories: ['x'] }, { categories: ['x'], series: [{ name: 'x', values: [NaN] }] }, { kind: 'bubble' }, { extra: 1, kind: 'line' }]) {
    assert.throws(() => validateChartEdits(opened, [{ slideIndex: 0, elementId, ...patch }]))
  }
  assert.throws(() => validateChartEdits(opened, [{ slideIndex: 0, elementId, kind: 'line' }], { deletedSlides: [0] }))
  assert.throws(() => validateChartEdits(opened, [{ slideIndex: 0, elementId, kind: 'line' }], { deletions: [{ slideIndex: 0, elementId }] }))
  const chart = opened.deck.slides[0]!.elements.find(el => el.id === elementId)!
  chart.descr = 'external chart'
  assert.equal(inspectChartEdit(opened, 0, elementId).chartEditSafe, false)
  assert.throws(() => validateChartEdits(opened, [{ slideIndex: 0, elementId, kind: 'line' }]), /source_unsupported/)
  chart.descr = 'aislides-chart'
  const path = [...opened.archive.entries.keys()].find(path => /^ppt\/charts\/chart\d+\.xml$/.test(path))!
  opened.archive.entries.set(path, Buffer.from(opened.archive.readText(path)!.replace('</c:chartSpace>', '<c:extLst/></c:chartSpace>')))
  assert.equal(inspectChartEdit(opened, 0, elementId).chartEditSafe, false)
})

test('shared chart parts and source labels outside the wire contract are read-only', async () => {
  const { opened, elementId } = await fixture()
  duplicateSlide(opened, 0)
  const shared = await openPptx(await savePptx(opened))
  const firstId = shared.deck.slides[0]!.elements[0]!.id
  assert.equal(inspectChartEdit(shared, 0, firstId).chartEditSafe, false)
  assert.throws(() => validateChartEdits(shared, [{ slideIndex: 0, elementId: firstId, kind: 'line' }]), /source_unsupported/)
  const fresh = await fixture()
  const chart = fresh.opened.deck.slides[0]!.elements[0]!
  if (chart.type !== 'chart') throw new Error('chart missing')
  for (const invalid of ['x'.repeat(101), '换\n行', 'DEL\x7f']) {
    chart.chart.categories[0] = invalid
    assert.equal(inspectChartEdit(fresh.opened, 0, fresh.elementId).chartEditSafe, false)
  }
  chart.chart.categories[0] = '甲'
  assert.throws(() => validateChartEdits(fresh.opened, Array.from({ length: 51 }, () => ({ slideIndex: 0, elementId, kind: 'line' }))), /edits_invalid/)
})
