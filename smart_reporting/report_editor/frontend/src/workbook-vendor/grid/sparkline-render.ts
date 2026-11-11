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
interface SparklineWorksheet {
  getCell(row: number, column: number): { v?: unknown } | null | undefined
}
const sourceResolvers = new Map<string, (sheetName: string) => SparklineWorksheet | undefined>()
/** Resolver 绑定具体 unit；由宿主按稳定 sheet 身份解析当前真实 worksheet。 */
export function setSparklineWorkbookResolver(
  unitId: string,
  resolver: ((sheetName: string) => SparklineWorksheet | undefined) | undefined,
): void {
  if (resolver) sourceResolvers.set(unitId, resolver)
  else sourceResolvers.delete(unitId)
}


/// diagnostics handle (same spirit as __sheetsWebRuntime): lets browser tests
/// verify the store contents and whether draw() fires; no secrets involved
;(window as unknown as { __sheetsWebSparklines?: unknown }).__sheetsWebSparklines = {
  store,
  draws: 0,
  lastSkip: null as string | null,
  targetBounds: new Map<string, { startX: number; endX: number; startY: number; endY: number }>(),
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
        const source = spec.sourceSheet === undefined ? worksheet : sourceResolvers.get(worksheet.getUnitId())?.(spec.sourceSheet)
        if (!source) { noteSkip(`找不到来源工作表：${spec.sourceSheet ?? ''}`); continue }
        const diagnostics = (window as unknown as { __sheetsWebSparklines?: { lastSource?: unknown } }).__sheetsWebSparklines
        if (diagnostics) diagnostics.lastSource = { unitId: worksheet.getUnitId(), hostSheetId: worksheet.getSheetId(), ...(spec.sourceSheet !== undefined ? { sourceSheet: spec.sourceSheet } : {}) }
        const bounds = parseRange(spec.source)
        const values: number[] = []
        for (let row = bounds.startRow; row <= bounds.endRow; row += 1) {
          for (let column = bounds.startColumn; column <= bounds.endColumn; column += 1) {
            const raw = source.getCell(row, column)
            const numeric = numberOrSkip(raw?.v)
            if (numeric !== null) values.push(numeric)
          }
        }
        if (values.length < 2) {
          noteSkip(`values=${JSON.stringify(values)} raw0=${JSON.stringify(source.getCell(bounds.startRow, bounds.startColumn))}`)
          continue
        }
        // only 1-D sources draw (a single row or column of data)
        const singleRow = bounds.endRow === bounds.startRow
        const singleColumn = bounds.endColumn === bounds.startColumn
        if (!singleRow && !singleColumn) continue

        const target = parseRange(spec.target)
        const cell = skeleton.getCellWithCoordByIndex(target.startRow, target.startColumn, false)
        const targetBounds = (window as unknown as { __sheetsWebSparklines?: { targetBounds?: Map<string, { startX: number; endX: number; startY: number; endY: number }> } }).__sheetsWebSparklines?.targetBounds
        targetBounds?.set(`${worksheet.getUnitId()}::${worksheet.getSheetId()}::${spec.target}`, { startX: cell.startX, endX: cell.endX, startY: cell.startY, endY: cell.endY })
        const x0 = cell.startX + 2
        const x1 = cell.endX - 2
        const y0 = cell.startY + 2
        const y1 = cell.endY - 2
        const width = x1 - x0
        const height = y1 - y0
        if (width <= 0 || height <= 0) continue
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
          // 柱形值域包含零；盈亏图仅按符号各占中线一侧的半高。
          const isWinLoss = spec.kind === 'winLoss'
          const columnWidth = width / values.length
          const gap = Math.min(1, columnWidth / 2)
          const minimum = Math.min(0, min), maximum = Math.max(0, max)
          const span = maximum - minimum || 1
          const baseline = isWinLoss ? y0 + height / 2 : y1 - height * (0 - minimum) / span
          values.forEach((value, index) => {
            if (value === 0) return
            const valueY = isWinLoss ? baseline - Math.sign(value) * height / 2 : y1 - height * (value - minimum) / span
            ctx.fillRect(
              x0 + columnWidth * index + gap / 2,
              Math.min(baseline, valueY),
              columnWidth - gap,
              Math.abs(valueY - baseline),
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
