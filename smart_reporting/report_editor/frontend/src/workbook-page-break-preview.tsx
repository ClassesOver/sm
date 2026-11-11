// 固定 GenOffice f8c17004 page-break-preview.tsx 的官方范围浮层；分页真值复用宿主打印 planner。
import type { ComponentType } from 'react'
import { planSheetPrint, type PrintArea, type SheetPrintPlan, type SheetPrintSetup, type SheetPrintSource } from './workbook-print'
import './workbook-page-break-preview.css'

export interface PageBreakLayer {
  readonly kind: 'outline' | 'row' | 'column' | 'page'
  readonly range: PrintArea
  readonly manual?: boolean
  readonly page?: number
}
export type PageBreakPreviewPlan = { readonly status: 'unavailable'; readonly reason: string } | {
  readonly status: 'ready'
  readonly printPlan: SheetPrintPlan
  readonly layers: readonly PageBreakLayer[]
  readonly issues: readonly string[]
}

/** 输入必须是当前同一版本的页面设置和实时 geometry；此模块不拥有 journal 或坐标映射。 */
export function planPageBreakPreview(source: SheetPrintSource, setup: SheetPrintSetup): PageBreakPreviewPlan {
  const printPlan = planSheetPrint(source, setup)
  if (!printPlan) return { status: 'unavailable', reason: '没有可预览的打印内容，或打印区域超过 50000 单元格预算。' }
  const layers: PageBreakLayer[] = [], issues: string[] = []
  const seen = new Set<string>()
  let rows = 0, columns = 0
  for (const area of printPlan.areas) {
    rows = Math.max(rows, area.endRow - area.startRow + 1)
    columns = Math.max(columns, area.endColumn - area.startColumn + 1)
  }
  // 与来源保持有界渲染；拒绝超 extent，不画一个貌似完整但截断的纸张外框。
  if (rows > 20000 || columns > 2000) return { status: 'unavailable', reason: '分页预览最多覆盖每个打印区域 20000 行、2000 列；请缩小打印区域。' }
  for (const area of printPlan.areas.slice(0, 60)) layers.push({ kind: 'outline', range: area })
  if (printPlan.areas.length > 60) issues.push(`共有 ${printPlan.areas.length} 个打印区域，仅显示前 60 个区域外框。`)
  const starts = new Map<number, { row: number; column: number }>()
  for (const page of printPlan.pages) {
    const previous = starts.get(page.area)
    starts.set(page.area, { row: Math.min(previous?.row ?? page.rowStart, page.rowStart), column: Math.min(previous?.column ?? page.colStart, page.colStart) })
  }
  let rowLines = 0, columnLines = 0
  printPlan.pages.forEach((page, index) => {
    const area = printPlan.areas[page.area]!
    for (const kind of ['row', 'column'] as const) {
      const position = kind === 'row' ? page.rowStart : page.colStart
      // 标题行列重复出现在打印页，不在网格上复制；首body band并非新分页线。
      const first = kind === 'row' ? starts.get(page.area)!.row : starts.get(page.area)!.column
      const key = `${page.area}:${kind}:${position}`
      if (position === first || seen.has(key)) continue
      seen.add(key)
      if (kind === 'row' ? rowLines++ >= 200 : columnLines++ >= 200) continue
      const range = kind === 'row' ? { ...area, startRow: position, endRow: position } : { ...area, startColumn: position, endColumn: position }
      layers.push({ kind, range, manual: (kind === 'row' ? setup.rowBreaks : setup.colBreaks).includes(position) })
    }
    if (index < 60) layers.push({ kind: 'page', page: index + 1, range: { startRow: page.rowStart, endRow: page.rowEnd, startColumn: page.colStart, endColumn: page.colEnd } })
  })
  if (printPlan.pages.length > 60) issues.push(`共有 ${printPlan.pages.length} 页，仅显示前 60 个页码水印。`)
  if (rowLines > 200 || columnLines > 200) issues.push('每个方向最多显示 200 条分页线，其余分页线未显示。')
  if (printPlan.titleRows || printPlan.titleColumns) issues.push('重复打印标题仅在打印页中重复，网格预览不复制标题行列。')
  return { status: 'ready', printPlan, layers, issues }
}

interface Disposable { dispose(): void }
interface OverlayRuntime { univerAPI: { registerComponent(key: string, component: ComponentType): Disposable } }
interface OverlaySheet<Range> {
  getRange(row: number, column: number, rows: number, columns: number): Range
  addFloatDomToRange(range: Range, layer: { componentKey: string; allowTransform: boolean; eventPassThrough: boolean }, layout: Record<string, never>, key: string): Disposable | null | undefined | void
}

/** idPrefix 由宿主实例生成；返回的句柄必须在刷新、关闭、替换及销毁时释放。 */
export function installPageBreakOverlay<Range>(runtime: OverlayRuntime, sheet: OverlaySheet<Range>, plan: Extract<PageBreakPreviewPlan, { status: 'ready' }>, idPrefix: string, rtl = false): Disposable {
  const disposables: Disposable[] = []
  const dispose = () => { for (const item of disposables.splice(0).reverse()) { try { item.dispose() } catch { /* 某个浮层可能已随工作簿销毁，仍须释放其余注册。 */ } } }
  try {
    plan.layers.forEach((layer, index) => {
      const key = `${idPrefix}-${index}`, line = `2px ${layer.manual ? 'solid' : 'dashed'} #1f5aa8`
      const render = () => <div className={`workbook-page-break-preview workbook-page-break-${layer.kind}`} aria-hidden="true" style={{
        width: '100%', height: '100%', boxSizing: 'border-box', pointerEvents: 'none',
        ...(layer.kind === 'outline' ? { border: '2px solid #1f5aa8' } : {}),
        ...(layer.kind === 'row' ? { borderTop: line } : {}),
        ...(layer.kind === 'column' ? rtl ? { borderRight: line } : { borderLeft: line } : {}),
        ...(layer.kind === 'page' ? { display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: 28, fontWeight: 600, color: '#667085', opacity: .55, userSelect: 'none', overflow: 'hidden' } : {}),
      }}>{layer.kind === 'page' ? `第 ${layer.page} 页` : null}</div>
      disposables.push(runtime.univerAPI.registerComponent(key, render))
      const area = layer.range
      const floating = sheet.addFloatDomToRange(sheet.getRange(area.startRow, area.startColumn, area.endRow - area.startRow + 1, area.endColumn - area.startColumn + 1), { componentKey: key, allowTransform: false, eventPassThrough: true }, {}, key)
      if (!floating) throw new Error('分页预览浮层未能注册，请重试。')
      disposables.push(floating)
    })
    return { dispose }
  } catch (error) { dispose(); throw error }
}
