import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const registry = vi.hoisted(() => ({ extensions: [] as Array<new () => { draw(...args: unknown[]): void }> }))
vi.mock('@univerjs/engine-render', () => ({
  SheetExtension: class {},
  SpreadsheetExtensionRegistry: { add: (extension: typeof registry.extensions[number]) => registry.extensions.push(extension) },
}))
import { setCharts } from './chart-render'

type Rect = { x: number; y: number; width: number; height: number; color: string }
function paint(kind: 'bar' | 'column', series: Array<Array<unknown>>) {
  const fills: Rect[] = []
  const ctx = {
    fillStyle: '', strokeStyle: '', lineWidth: 1,
    save: vi.fn(), restore: vi.fn(), strokeRect: vi.fn(), fillText: vi.fn(),
    fillRect(x: number, y: number, width: number, height: number) {
      fills.push({ x, y, width, height, color: this.fillStyle })
    },
  }
  const specs: ChartReadSpec[] = [{ chartPath: 'xl/charts/chart1.xml', kind,
    anchor: { fromRow: 0, fromColumn: 0, toRow: 9, toColumn: 9 },
    series: series.map((_, index) => ({ valuesRef: String.fromCharCode(65 + index) + '1:' + String.fromCharCode(65 + index) + series[index]!.length })),
  }]
  setCharts('test-unit', 'test-sheet', specs)
  const extension = new registry.extensions[0]!()
  extension.draw(ctx, {}, {
    worksheet: { getUnitId: () => 'test-unit', getSheetId: () => 'test-sheet',
      getCell: (row: number, column: number) => ({ v: series[column]?.[row] }) },
    getCellWithCoordByIndex: (row: number, column: number) => ({
      startX: column * 40, endX: (column + 1) * 40, startY: row * 20, endY: (row + 1) * 20,
    }),
  })
  expect(ctx.restore).toHaveBeenCalledOnce()
  return fills.filter(rect => rect.color !== '#ffffff')
}

beforeEach(() => setCharts('test-unit', 'test-sheet', undefined))

describe.each(['bar', 'column'] as const)('%s actual registered canvas extension', kind => {
  it('draws positive/negative values on opposite sides of one zero line', () => {
    const [positive, negative] = paint(kind, [[3, -5]])
    expect(positive).toBeDefined(); expect(negative).toBeDefined()
    if (kind === 'bar') {
      expect(negative!.x + negative!.width).toBeCloseTo(positive!.x)
      expect(negative!.width / positive!.width).toBeCloseTo(5 / 3)
      expect(positive!.width).toBeGreaterThan(positive!.height)
    } else {
      expect(positive!.y + positive!.height).toBeCloseTo(negative!.y)
      expect(negative!.height / positive!.height).toBeCloseTo(5 / 3)
    }
    for (const rect of [positive!, negative!]) {
      expect(rect.x).toBeGreaterThanOrEqual(8); expect(rect.x + rect.width).toBeLessThanOrEqual(392)
      expect(rect.y).toBeGreaterThanOrEqual(8); expect(rect.y + rect.height).toBeLessThanOrEqual(192)
    }
  })

  it('does not invent a visible magnitude for zero, missing, or non-finite values', () => {
    const bars = paint(kind, [[0, null, undefined, 'text', NaN, Infinity, -Infinity]])
    expect(bars).toEqual([])
  })

  it('keeps missing category slots and longer later-series values aligned', () => {
    const bars = paint(kind, [[10, null, 20], [5, 8, 15, 7]])
    expect(bars).toHaveLength(6)
    const first = bars.filter(bar => bar.color === '#4472c4')
    const second = bars.filter(bar => bar.color === '#ed7d31')
    expect(first).toHaveLength(2); expect(second).toHaveLength(4)
    if (kind === 'bar') {
      expect(first[1]!.y - first[0]!.y).toBeCloseTo(2 * (second[1]!.y - second[0]!.y))
      expect(first[1]!.width / first[0]!.width).toBeCloseTo(2)
      expect(second[3]!.y + second[3]!.height).toBeLessThanOrEqual(192)
    } else {
      expect(first[1]!.x - first[0]!.x).toBeCloseTo(2 * (second[1]!.x - second[0]!.x))
      expect(first[1]!.height / first[0]!.height).toBeCloseTo(2)
      expect(second[3]!.x + second[3]!.width).toBeLessThanOrEqual(392)
    }
  })

  it('keeps all-negative bars inside the plot with zero at its far edge', () => {
    const bars = paint(kind, [[-10, -20]])
    expect(bars).toHaveLength(2)
    if (kind === 'bar') {
      expect(bars[0]!.x + bars[0]!.width).toBeCloseTo(392)
      expect(bars[1]!.x).toBeCloseTo(8)
    } else {
      expect(bars[0]!.y).toBeCloseTo(8)
      expect(bars[1]!.y + bars[1]!.height).toBeCloseTo(192)
    }
  })

  it('uses finite geometry even when the raw numeric span overflows', () => {
    const bars = paint(kind, [[Number.MAX_VALUE, -Number.MAX_VALUE]])
    expect(bars).toHaveLength(2)
    expect(bars.every(rect => [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite))).toBe(true)
    const extents = bars.map(rect => kind === 'bar' ? rect.width : rect.height)
    expect(extents[0]).toBeCloseTo(extents[1]!)
  })
})
