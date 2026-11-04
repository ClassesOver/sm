/// Sparkline render extension for the Univer canvas: draws line / column /
/// winLoss mini-charts inside their target cells, the same way the CF preset's
/// DataBar extension works (a SheetExtension registered on the static
/// SpreadsheetExtensionRegistry). Specs arrive from the load bridge via a
/// module-level store keyed by unitId/sheetId.

import type { SparklineSpec } from '@sheets-web/xlsx-engine'
import { parseRange } from '@sheets-web/xlsx-engine'
import type { IRange, IScale } from '@univerjs/core'
import type { IDrawInfo, SpreadsheetSkeleton, UniverRenderingContext } from '@univerjs/engine-render'
import {
  SheetExtension,
  SpreadsheetExtensionRegistry,
} from '@univerjs/engine-render'

const store = new Map<string, ReadonlyArray<SparklineSpec>>()

/// diagnostics handle (same spirit as __sheetsWebRuntime): lets browser tests
/// verify the store contents and whether draw() fires; no secrets involved
;(window as unknown as { __sheetsWebSparklines?: unknown }).__sheetsWebSparklines = {
  store,
  draws: 0,
  lastSkip: null as string | null,
}

/// keyed store: the extension instance is created by the render engine, so
/// data flows through here rather than constructor injection
export function setSparklines(
  unitId: string,
  sheetId: string,
  specs: ReadonlyArray<SparklineSpec> | undefined,
): void {
  const key = `${unitId}::${sheetId}`
  if (specs === undefined || specs.length === 0) store.delete(key)
  else store.set(key, specs)
}

const SPARKLINE_UKEY = 'sheets-web-sparkline'
const EXTENSION_Z_INDEX = 30

interface SkeletonLike {
  worksheet?: {
    getUnitId?: () => string
    getSheetId?: () => string
    getCell(row: number, column: number): { v?: unknown } | null | undefined
  } | null
  getCellWithCoordByIndex(
    row: number,
    column: number,
    merge: boolean,
  ): { startX: number; endX: number; startY: number; endY: number }
}

const numberOrSkip = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

class SparklineExtension extends SheetExtension {
  uKey = SPARKLINE_UKEY
  Z_INDEX = EXTENSION_Z_INDEX

  draw(
    ctx: UniverRenderingContext,
    _parentScale: IScale,
    skeletonRaw: SpreadsheetSkeleton,
    _diffRanges?: IRange[],
    _more?: IDrawInfo,
  ): void {
    const diagnostics = (window as unknown as { __sheetsWebSparklines?: { draws: number } })
      .__sheetsWebSparklines
    if (diagnostics) diagnostics.draws += 1
    const skeleton = skeletonRaw as unknown as SkeletonLike
    const worksheet = skeleton.worksheet
    if (!worksheet?.getUnitId || !worksheet.getSheetId) return
    const specs = store.get(`${worksheet.getUnitId()}::${worksheet.getSheetId()}`)
    if (!specs || specs.length === 0) return

    for (const spec of specs) {
      const noteSkip = (reason: string) => {
        const d = (window as unknown as {
          __sheetsWebSparklines?: { lastSkip: string | null }
        }).__sheetsWebSparklines
        if (d) d.lastSkip = `${spec.target}: ${reason}`
      }
      try {
        const bounds = parseRange(spec.source)
        const values: number[] = []
        for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
          for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
            const raw = worksheet.getCell(row, column)
            const numeric = numberOrSkip(raw?.v)
            if (numeric !== null) values.push(numeric)
          }
        }
        if (values.length < 2) {
          noteSkip(`values=${JSON.stringify(values)} raw0=${JSON.stringify(worksheet.getCell(bounds.startRow, bounds.startColumn))}`)
          continue
        }
        // only 1-D sources draw (a single row or column of data)
        const singleRow = bounds.endRow === bounds.startRow
        const singleColumn = bounds.endColumn === bounds.startColumn
        if (!singleRow && !singleColumn) continue

        const target = parseRange(spec.target)
        const cell = skeleton.getCellWithCoordByIndex(target.startRow, target.startColumn, false)
        const x0 = cell.startX + 2
        const x1 = cell.endX - 2
        const y0 = cell.startY + 2
        const y1 = cell.endY - 2
        const width = Math.max(1, x1 - x0)
        const height = Math.max(1, y1 - y0)
        const min = Math.min(...values)
        const max = Math.max(...values)
        ctx.save()
        ctx.strokeStyle = spec.color ?? '#376092'
        ctx.fillStyle = spec.color ?? '#376092'
        ctx.lineWidth = 1
        if (spec.kind === 'line') {
          const span = max === min ? 1 : max - min
          ctx.beginPath()
          values.forEach((value, index) => {
            const x = x0 + (width * index) / (values.length - 1)
            const y = y1 - (height * (value - min)) / span
            if (index === 0) ctx.moveTo(x, y)
            else ctx.lineTo(x, y)
          })
          ctx.stroke()
          if (spec.markers) {
            values.forEach((value, index) => {
              const x = x0 + (width * index) / (values.length - 1)
              const y = y1 - (height * (value - min)) / span
              ctx.beginPath()
              ctx.arc(x, y, 1.5, 0, Math.PI * 2)
              ctx.fill()
            })
          }
        } else {
          // column / winLoss: bars scaled to the cell; winLoss normalizes
          // around zero (up = positive, down = negative, magnitude by |v|)
          const columnWidth = width / values.length
          const span = spec.kind === 'winLoss' ? 1 : max - min || 1
          const baseline =
            spec.kind === 'winLoss'
              ? y0 + height / 2
              : y1 - (height * (max - min)) / span + (height * (max - max)) / span // bottom for plain columns
          values.forEach((value, index) => {
            const normalized =
              spec.kind === 'winLoss' ? Math.sign(value) * Math.min(1, Math.abs(value)) : value - min
            const barHeight = Math.max(1, (height * Math.abs(normalized)) / span)
            const x = x0 + columnWidth * index + 0.5
            ctx.fillRect(
              x,
              normalized >= 0 ? baseline - barHeight : baseline,
              Math.max(1, columnWidth - 1),
              barHeight,
            )
          })
          if (spec.showAxis) {
            ctx.beginPath()
            ctx.moveTo(x0, baseline)
            ctx.lineTo(x1, baseline)
            ctx.stroke()
          }
        }
        ctx.restore()
      } catch (error) {
        const d = (window as unknown as {
          __sheetsWebSparklines?: { lastSkip: string | null }
        }).__sheetsWebSparklines
        if (d) d.lastSkip = `${spec.target}: throw ${error instanceof Error ? error.message : String(error)}`
        // address/coordinate variance: skip this sparkline, keep rendering
      }
    }
  }
}

SpreadsheetExtensionRegistry.add(SparklineExtension)
