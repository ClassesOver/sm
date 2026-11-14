import { expect, it } from 'vitest'
import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { paintPieDataLabels } from './chart-pie-data-labels'

const plot = { left: 0, top: 0, right: 400, bottom: 300 }
const geometry = { cx: 200, cy: 150, radius: 80, innerRadius: 0 }
const worksheet = { getName: () => 'Sheet1', getCell: () => null }
function chart(dataLabels: unknown, overrides: Record<string, unknown> = {}): ChartReadSpec {
  return { kind: 'pie', chartPath: 'xl/charts/chart1.xml', anchor: { fromRow: 0, fromColumn: 0, toRow: 10, toColumn: 10 },
    dataLabels, series: [{ valuesRef: 'B2:B3', categories: ['甲', '乙'], ...overrides }] } as ChartReadSpec
}
function canvas() {
  const labels: { text: string; x: number; y: number; font: string; color: string }[] = []
  const lines: number[][] = []
  const ctx = { font: '', fillStyle: '', strokeStyle: '', lineWidth: 1, textAlign: '', textBaseline: '',
    save() {}, restore() {}, beginPath() {}, rect() {}, clip() {}, stroke() {},
    moveTo(x: number, y: number) { lines.push([x, y]) }, lineTo(x: number, y: number) { lines.push([x, y]) },
    measureText(text: string) { return { width: text.length * 6 } },
    fillText(text: string, x: number, y: number) { labels.push({ text, x, y, font: this.font, color: this.fillStyle }) },
  }
  return { ctx: ctx as never, labels, lines }
}

it('draws live category and integer percent on each visible slice', () => {
  const c = canvas()
  paintPieDataLabels(c.ctx, chart({ showCategory: true, showPercent: true }), [25, 75], worksheet, geometry, plot)
  expect(c.labels.map(label => label.text)).toEqual(['甲', '25%', '乙', '75%'])
  expect(c.labels[0]!.x).toBeCloseTo(200 + Math.SQRT1_2 * 80 * 0.62)
})
it('moves labels with the same point explosion and actual doughnut hole',()=>{const base=canvas(),moved=canvas();const c={...chart({showValue:true,position:'center'}),kind:'doughnut' as const};paintPieDataLabels(base.ctx,c,[1,1],worksheet,{...geometry,innerRadius:56},plot);paintPieDataLabels(moved.ctx,{...c,series:[{...c.series[0]!,pointExplosions:{0:50}}]},[1,1],worksheet,{...geometry,innerRadius:56},plot);expect(moved.labels[0]!.x-base.labels[0]!.x).toBeCloseTo(16);expect(moved.labels[1]!.x).toBe(base.labels[1]!.x)})

it('formats percents from shares with explicit label formats and never source currency', () => {
  const c = canvas()
  paintPieDataLabels(c.ctx, chart({ showPercent: true, numberFormat: '0.0%' }, { numberFormat: '"￥"0.00' }), [1, 3], worksheet, geometry, plot)
  expect(c.labels.map(label => label.text)).toEqual(['25.0%', '75.0%'])
  const defaults = canvas()
  paintPieDataLabels(defaults.ctx, chart({ showPercent: true }, { numberFormat: '"￥"0.00' }), [1, 3], worksheet, geometry, plot)
  expect(defaults.labels.map(label => label.text)).toEqual(['25%', '75%'])
})

it('inherits value format and point style while preserving blank value/category indices', () => {
  const c = canvas()
  const spec = chart({ showValue: true, style: { color: '#123456', sizePt: 12 }, points: { 2: { style: { bold: true } } } }, {
    categoriesRef: 'Sheet1!A2:A4', categories: ['旧甲', '旧乙', '旧丙'], numberFormat: '"￥"0.0',
  })
  const live = { getName: () => 'Sheet1', getCell: (row: number) => ({ v: ['新甲', '', '新丙'][row - 1] }) }
  paintPieDataLabels(c.ctx, spec, [1, null, 3], live, geometry, plot)
  expect(c.labels.map(label => label.text)).toEqual(['￥1.0', '￥3.0'])
  expect(c.labels[1]).toMatchObject({ font: 'bold 16px system-ui', color: '#123456' })
  const names = canvas()
  paintPieDataLabels(names.ctx, { ...spec, dataLabels: { showCategory: true } }, [1, null, 3], live, geometry, plot)
  expect(names.labels.map(label => label.text)).toEqual(['新甲', '新丙'])
})

it('places doughnut labels in the ring and small slices outside with leader lines', () => {
  const c = canvas()
  paintPieDataLabels(c.ctx, { ...chart({ showPercent: true }), kind: 'doughnut' }, [1, 1], worksheet, { ...geometry, innerRadius: 40 }, plot)
  expect(c.labels[0]!.x).toBeCloseTo(260)
  const small = canvas()
  paintPieDataLabels(small.ctx, chart({ showPercent: true }), [1, 19], worksheet, geometry, plot)
  expect(small.labels.map(label => label.text)).toEqual(['5%', '95%'])
  expect(small.lines.length).toBeGreaterThanOrEqual(3)
})

it('omits invisible slivers, deleted points, unsupported custom labels and labels that cannot fit', () => {
  for (const settings of [undefined, { showPercent: true, deleted: true }, { showPercent: true, unsupported: true }]) {
    const c = canvas()
    paintPieDataLabels(c.ctx, chart(settings), [1, 9], worksheet, geometry, plot)
    expect(c.labels).toEqual([])
  }
  const c = canvas()
  paintPieDataLabels(c.ctx, chart({ showPercent: true, points: { 1: { deleted: true } } }), [0.004, 0.096, 0.9], worksheet, geometry, plot)
  expect(c.labels.map(label => label.text)).toEqual(['90%'])
  const tiny = canvas()
  paintPieDataLabels(tiny.ctx, chart({ showPercent: true, style: { sizePt: 300 } }), [1, 1], worksheet, geometry, plot)
  expect(tiny.labels).toEqual([])
})
