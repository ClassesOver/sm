// 固定 GenOffice f8c17004 的公式文本引用 collector 与官方范围浮层；来源见专项调查。
import { createElement as h, type ComponentType } from 'react'
import { FORMULA_REFERENCE_PATTERN, qualifierMatches } from '@sheets-web/xlsx-engine/structural'
interface ParsedToken {
  readonly startRow: number | null
  readonly endRow: number | null
  readonly startColumn: number | null
  readonly endColumn: number | null
}

function lettersToColumn(letters: string): number {
  let column = 0
  for (const character of letters) {
    column = column * 26 + character.charCodeAt(0) - 64
  }
  return column - 1
}

/// Null bounds mean "whole axis" (A:A or 1:5 references), clamped to the
/// target sheet's used range by the caller.
function parseReferenceToken(token: string): ParsedToken | null {
  const wholeColumn = /^\$?([A-Z]{1,3}):\$?([A-Z]{1,3})$/.exec(token)
  if (wholeColumn) {
    const start = lettersToColumn(wholeColumn[1] ?? 'A')
    const end = lettersToColumn(wholeColumn[2] ?? 'A')
    return {
      startRow: null,
      endRow: null,
      startColumn: Math.min(start, end),
      endColumn: Math.max(start, end),
    }
  }
  const wholeRow = /^\$?([0-9]+):\$?([0-9]+)$/.exec(token)
  if (wholeRow) {
    const start = Number(wholeRow[1]) - 1
    const end = Number(wholeRow[2]) - 1
    return {
      startRow: Math.min(start, end),
      endRow: Math.max(start, end),
      startColumn: null,
      endColumn: null,
    }
  }
  const cells = token.split(':').map((part) => /^\$?([A-Z]{1,3})\$?([0-9]+)$/.exec(part))
  if (cells.some((cell) => cell === null)) return null
  const rows = cells.map((cell) => Number(cell?.[2]) - 1)
  const columns = cells.map((cell) => lettersToColumn(cell?.[1] ?? 'A'))
  return {
    startRow: Math.min(...rows),
    endRow: Math.max(...rows),
    startColumn: Math.min(...columns),
    endColumn: Math.max(...columns),
  }
}

interface FormulaReference {
  readonly qualifier: string | undefined
  readonly token: ParsedToken
}

export function parseFormulaReferences(formula: string): FormulaReference[] {
  const references: FormulaReference[] = []
  const segments = formula.split('"')
  for (let index = 0; index < segments.length; index += 2) {
    for (const match of (segments[index] ?? '').matchAll(FORMULA_REFERENCE_PATTERN)) {
      const token = parseReferenceToken(match[3] ?? '')
      if (token) references.push({ qualifier: match[2], token })
    }
  }
  return references
}

const EXTERNAL_WORKBOOK_PATTERN = /\[(?:\d+|[^[\]]*\.xl\w*)\]/i
/// Excel error literals (`=D2*#REF!` after a deleted column). They are values
/// the engine evaluates, not names; left in place their letters read as a
/// defined name and the formula is wrongly pinned to its (often absent) cache.
/// A sheet qualifier (`Sheet1!#REF!`) goes with it, or it would dangle.
const ERROR_LITERAL_PATTERN =
  /(?:'(?:[^']|'')*'!|[\p{L}\p{N}_.]+!)?#(?:NULL!|DIV\/0!|VALUE!|REF!|NAME\?|NUM!|N\/A|SPILL!|CALC!|GETTING_DATA)/gu

/// True when the formula uses an identifier that is not a function call —
/// a defined name or an external reference the closure cannot resolve.
export function containsUnresolvedNames(formula: string): boolean {
  const segments = formula.split('"')
  for (let index = 0; index < segments.length; index += 2) {
    // [n]Sheet!ref / '[n]Sheet name'!ref / 'C:\dir\[Book.xlsx]Sheet'!ref is
    // an external-workbook reference: the reference pattern would swallow it
    // as an ordinary sheet reference, but the closure can never resolve
    // another workbook.
    if (EXTERNAL_WORKBOOK_PATTERN.test(segments[index] ?? '')) return true
    // Strip references (and their qualifiers) so ref letters don't register.
    const stripped = (segments[index] ?? '')
      .replace(ERROR_LITERAL_PATTERN, ' ')
      .replace(FORMULA_REFERENCE_PATTERN, (_full, lead: string) => `${lead} `)
    for (const match of stripped.matchAll(/[\p{L}_][\p{L}\p{N}_.]*/gu)) {
      const before = match.index === 0 ? '' : (stripped[match.index - 1] ?? '')
      if (/[\p{L}\p{N}_.$'!]/u.test(before)) continue
      const name = match[0]
      if (name === 'TRUE' || name === 'FALSE') continue
      const rest = stripped.slice(match.index + name.length)
      if (!/^\s*\(/.test(rest)) return true
    }
  }
  return false
}

export interface CellArea {
  readonly startRow: number
  readonly endRow: number
  readonly startColumn: number
  readonly endColumn: number
}

export interface CellPoint {
  readonly row: number
  readonly column: number
}

export interface SheetBounds {
  readonly lastRow: number
  readonly lastColumn: number
  readonly maxRows: number
  readonly maxColumns: number
}

export interface PrecedentResult {
  /// Same-sheet referenced ranges, deduped, in formula order.
  readonly areas: CellArea[]
  /// References that resolve to another sheet — counted, not drawn.
  readonly offSheet: number
}

export function collectPrecedents(
  formula: string,
  sheetName: string,
  bounds: SheetBounds,
): PrecedentResult {
  const areas: CellArea[] = []
  const seen = new Set<string>()
  let offSheet = 0
  for (const reference of parseFormulaReferences(formula)) {
    if (reference.qualifier !== undefined && !qualifierMatches(reference.qualifier, sheetName)) {
      offSheet += 1
      continue
    }
    // Whole row/column references clamp to the used range so the overlay
    // stays finite; explicit refs clamp only to the sheet extent.
    const area = {
      startRow: Math.max(reference.token.startRow ?? 0, 0),
      endRow: Math.min(reference.token.endRow ?? Math.max(bounds.lastRow, 0), bounds.maxRows - 1),
      startColumn: Math.max(reference.token.startColumn ?? 0, 0),
      endColumn: Math.min(
        reference.token.endColumn ?? Math.max(bounds.lastColumn, 0),
        bounds.maxColumns - 1,
      ),
    }
    if (area.endRow < area.startRow || area.endColumn < area.startColumn) continue
    const key = `${area.startRow}:${area.startColumn}:${area.endRow}:${area.endColumn}`
    if (seen.has(key)) continue
    seen.add(key)
    areas.push(area)
  }
  return { areas, offSheet }
}

type CellDataMatrix = Record<
  number,
  | Record<
      number,
      | {
          readonly f?: unknown
        }
      | null
      | undefined
    >
  | null
  | undefined
>

export interface DependentsSource {
  readonly sheets: Record<
    string,
    | {
        readonly name?: string | undefined
        readonly cellData?: CellDataMatrix | undefined
      }
    | undefined
  >
}

export interface DependentResult {
  /// Formula cells on the active sheet that read the target cell.
  readonly cells: CellPoint[]
  /// Dependent formulas living on other sheets — counted, not drawn.
  readonly offSheet: number
}

export function collectDependents(
  source: DependentsSource,
  activeSheetName: string,
  target: CellPoint,
): DependentResult {
  const cells: CellPoint[] = []
  let offSheet = 0
  for (const sheet of Object.values(source.sheets)) {
    if (!sheet?.cellData) continue
    const onActiveSheet = sheet.name === activeSheetName
    for (const [rowKey, rowCells] of Object.entries(sheet.cellData)) {
      for (const [columnKey, cell] of Object.entries(rowCells ?? {})) {
        const formula = cell?.f
        if (typeof formula !== 'string' || !formula.startsWith('=')) continue
        const row = Number(rowKey)
        const column = Number(columnKey)
        if (onActiveSheet && row === target.row && column === target.column) continue
        if (!formulaReadsCell(formula, onActiveSheet, activeSheetName, target)) continue
        if (onActiveSheet) cells.push({ row, column })
        else offSheet += 1
      }
    }
  }
  return { cells, offSheet }
}

function formulaReadsCell(
  formula: string,
  onActiveSheet: boolean,
  activeSheetName: string,
  target: CellPoint,
): boolean {
  for (const reference of parseFormulaReferences(formula)) {
    const targetsActiveSheet =
      reference.qualifier === undefined
        ? onActiveSheet
        : qualifierMatches(reference.qualifier, activeSheetName)
    if (!targetsActiveSheet) continue
    const { token } = reference
    if (
      (token.startRow ?? 0) <= target.row &&
      target.row <= (token.endRow ?? Number.MAX_SAFE_INTEGER) &&
      (token.startColumn ?? 0) <= target.column &&
      target.column <= (token.endColumn ?? Number.MAX_SAFE_INTEGER)
    ) {
      return true
    }
  }
  return false
}

export interface TraceArrow {
  readonly from: CellPoint
  readonly to: CellPoint
}


export interface FormulaTracePlan {
  arrows: readonly TraceArrow[]
  highlights: readonly CellArea[]
  issues: readonly string[]
  message: string
}
export type FormulaTraceKind = 'precedents' | 'dependents'
const INCOMPLETE = '追踪仅解析公式中的直接单元格引用；名称、表格结构化引用及动态引用未展开，结果不代表完整依赖。'
function complexFormula(formula: string) {
  return containsUnresolvedNames(formula) || /\b(?:INDIRECT|OFFSET)\s*\(/i.test(formula.split('"').filter((_, i) => i % 2 === 0).join(' '))
}
/** 有界读取真实snapshot，遇复杂引用如实说明，不把空解析结果当作没有依赖。 */
export function planFormulaTrace(source: DependentsSource, sheetName: string, target: CellPoint, kind: FormulaTraceKind, bounds: SheetBounds): FormulaTracePlan {
  const issues: string[] = [], arrows: TraceArrow[] = [], highlights: CellArea[] = []
  const sheet = Object.values(source.sheets).find(sheet => sheet?.name === sheetName)
  if (!sheet) throw new Error('工作表已变化，请重新追踪。')
  let offSheet = 0
  if (kind === 'precedents') {
    const formula = sheet.cellData?.[target.row]?.[target.column]?.f
    if (typeof formula !== 'string' || !formula) return { arrows, highlights, issues, message: '请选择含公式的单元格。' }
    if (complexFormula(formula)) return { arrows, highlights, issues: [INCOMPLETE], message: `该公式包含未展开的引用，未绘制追踪箭头。 ${INCOMPLETE}` }
    const result = collectPrecedents(formula, sheetName, bounds)
    highlights.push(...result.areas); offSheet = result.offSheet
    arrows.push(...result.areas.map(area => ({ from: { row: area.startRow, column: area.startColumn }, to: target })))
  } else {
    let count = 0
    const safeSource: DependentsSource = { sheets: {} }
    for (const [id, candidate] of Object.entries(source.sheets)) {
      if (!candidate) continue
      const cellData: Record<number, Record<number, { f: string }>> = {}
      for (const [rowKey, row] of Object.entries(candidate.cellData ?? {})) for (const [columnKey, cell] of Object.entries(row ?? {})) {
        if (++count > 20000) throw new Error('从属追踪超过 20000 个已存储单元格预算，请缩小工作簿。')
        if (typeof cell?.f !== 'string') continue
        if (complexFormula(cell.f)) { if (!issues.length) issues.push(INCOMPLETE); continue }
        ;(cellData[Number(rowKey)] ??= {})[Number(columnKey)] = { f: cell.f }
      }
      safeSource.sheets[id] = { name: candidate.name, cellData }
    }
    const result = collectDependents(safeSource, sheetName, target); offSheet = result.offSheet
    arrows.push(...result.cells.map(cell => ({ from: target, to: cell })))
  }
  if (arrows.length + highlights.length > 200) throw new Error('追踪超过 200 个浮层预算，未绘制部分结果。')
  for (const area of highlights) if (area.endRow - area.startRow + 1 > 20000 || area.endColumn - area.startColumn + 1 > 2000) throw new Error('追踪区域超过 20000 行或 2000 列，未绘制部分结果。')
  for (const { from, to } of arrows) if (Math.abs(from.row - to.row) + 1 > 20000 || Math.abs(from.column - to.column) + 1 > 2000) throw new Error('追踪范围超过 20000 行或 2000 列，未绘制部分结果。')
  if (offSheet) issues.push(`另有 ${offSheet} 个跨工作表引用，仅计数，未绘制跨表箭头。`)
  const count = kind === 'precedents' ? highlights.length : arrows.length
  const message = count ? `已追踪 ${count} 个${kind === 'precedents' ? '引用区域' : '从属单元格'}。` : issues.length ? '未找到可绘制的直接引用。' : kind === 'precedents' ? '公式没有直接单元格引用。' : '没有直接引用该单元格的公式。'
  return { arrows, highlights, issues, message: [message, ...(count ? ['视口外端点不绘制箭头；滚动至可见区域后显示。'] : []), ...issues].join(' ') }
}
interface OverlaySheet<R> {
  getRange(row: number, column: number, rows: number, columns: number): R
  addFloatDomToRange(range: R, layer: { componentKey: string; allowTransform: boolean; eventPassThrough: boolean }, layout: { width?: number; height?: number }, key: string): { dispose(): void } | null | undefined | void
  getColumnWidth(index: number): number
  getRowHeight(index: number): number
  getFreeze?(): {startRow: number; startColumn: number; xSplit: number; ySplit: number}
  isMergedCell?(row: number, column: number): boolean
}
export function installFormulaTraceOverlay<R>(runtime: { univerAPI: { registerComponent(key: string, component: ComponentType): { dispose(): void } } }, sheet: OverlaySheet<R>, plan: FormulaTracePlan, prefix: string, rtl = false) {
  const layers: { dispose(): void }[] = []
  const dispose = () => { for (const layer of layers.splice(0).reverse()) { try { layer.dispose() } catch { /* 工作簿可能已销毁，继续释放其余注册。 */ } } }
  const install = (area: CellArea, key: string, component: ComponentType) => {
    layers.push(runtime.univerAPI.registerComponent(key, component))
    // 官方 RTL 多列范围会计算负宽；用视觉左上单格锚点并保留官方缩放、滚动跟随。
    const range = rtl ? sheet.getRange(area.startRow, area.endColumn, 1, 1) : sheet.getRange(area.startRow, area.startColumn, area.endRow - area.startRow + 1, area.endColumn - area.startColumn + 1)
    const extent = (start: number, end: number, size: (index: number) => number) => { let total = 0; for (let i = start; i <= end; i++) total += Math.max(size(i), 0); return total }
    const layout = rtl ? { width: extent(area.startColumn, area.endColumn, i => sheet.getColumnWidth(i)), height: extent(area.startRow, area.endRow, i => sheet.getRowHeight(i)) } : {}
    const floating = sheet.addFloatDomToRange(range, { componentKey: key, allowTransform: false, eventPassThrough: true }, layout, key)
    if (!floating) throw new Error('追踪浮层未能注册，请重试。')
    layers.push(floating)
  }
  try {
    // 隐藏轴没有可见端点；合并主格会被官方浮层扩成 mergeInfo，不能冒充精确箭头。
    const areas = [...plan.highlights, ...plan.arrows.map(({from,to}) => ({startRow:Math.min(from.row,to.row),endRow:Math.max(from.row,to.row),startColumn:Math.min(from.column,to.column),endColumn:Math.max(from.column,to.column)}))]
    for (const area of areas) {
      let width = 0, height = 0
      for (let i = area.startColumn; i <= area.endColumn; i++) width += Math.max(sheet.getColumnWidth(i), 0)
      for (let i = area.startRow; i <= area.endRow; i++) height += Math.max(sheet.getRowHeight(i), 0)
      if (!width || !height) throw new Error('追踪范围完全隐藏，未绘制箭头。')
      if (sheet.isMergedCell?.(area.startRow, rtl ? area.endColumn : area.startColumn)) throw new Error('追踪锚点涉及合并单元格，未绘制可能错位的箭头。')
    }
    if (plan.arrows.some(({from,to}) => sheet.isMergedCell?.(from.row,from.column) || sheet.isMergedCell?.(to.row,to.column))) throw new Error('追踪端点涉及合并单元格，未绘制可能错位的箭头。')
    const freeze = sheet.getFreeze?.()
    const highlightParts = plan.highlights.flatMap(area => {
      const rows = freeze?.ySplit && freeze.startRow > area.startRow && freeze.startRow <= area.endRow ? [area.startRow,freeze.startRow,area.endRow+1] : [area.startRow,area.endRow+1]
      const columns = freeze?.xSplit && freeze.startColumn > area.startColumn && freeze.startColumn <= area.endColumn ? [area.startColumn,freeze.startColumn,area.endColumn+1] : [area.startColumn,area.endColumn+1]
      return rows.slice(0,-1).flatMap((startRow,r)=>columns.slice(0,-1).map((startColumn,c)=>({startRow,endRow:rows[r+1]!-1,startColumn,endColumn:columns[c+1]!-1})))
    })
    highlightParts.forEach((area, index) => install(area, `${prefix}-box-${index}`, () => h('div', { className: 'workbook-formula-trace-box', 'aria-hidden': true, style: { width: '100%', height: '100%', boxSizing: 'border-box', border: '2px solid #1f5aa8', pointerEvents: 'none' } })))
    plan.arrows.forEach(({ from, to }, index) => {
      if (from.row === to.row && from.column === to.column) return
      const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg')
      svg.classList.add('workbook-formula-trace-arrow'); svg.setAttribute('aria-hidden', 'true')
      Object.assign(svg.style, { position: 'fixed', inset: '0', width: '100vw', height: '100vh', pointerEvents: 'none', overflow: 'hidden', zIndex: '30' })
      const circle = document.createElementNS(ns, 'circle'), line = document.createElementNS(ns, 'line'), head = document.createElementNS(ns, 'polygon')
      circle.setAttribute('r', '3'); circle.setAttribute('fill', '#1f5aa8'); line.setAttribute('stroke', '#1f5aa8'); line.setAttribute('stroke-width', '1.5'); head.setAttribute('fill', '#1f5aa8')
      svg.append(circle, line, head); document.body.append(svg)
      const endpoints: (HTMLElement | null)[] = [null, null], observers: (MutationObserver | undefined)[] = []
      let frame = 0, removed = false
      // 官方单格浮层负责pane/RTL/scroll/zoom；只读取其可见裁剪矩形，禁止重算viewport坐标。
      const visibleBounds = (element: HTMLElement | null) => {
        if (!element?.isConnected) return null
        let left = -Infinity, top = -Infinity, right = Infinity, bottom = Infinity
        for (let node: HTMLElement | null = element.parentElement; node; node = node.parentElement) {
          const rect = node.getBoundingClientRect(), style = getComputedStyle(node)
          if (style.display === 'none' || style.visibility === 'hidden') return null
          if (node === element.parentElement || ['hidden', 'clip', 'auto', 'scroll'].includes(style.overflow)) {
            left = Math.max(left, rect.left); top = Math.max(top, rect.top); right = Math.min(right, rect.right); bottom = Math.min(bottom, rect.bottom)
          }
        }
        return right > left && bottom > top ? { x: (left + right) / 2, y: (top + bottom) / 2 } : null
      }
      const update = () => {
        frame = 0
        if (removed) return
        const origin = visibleBounds(endpoints[0]), tip = visibleBounds(endpoints[1])
        svg.style.display = origin && tip ? '' : 'none'
        if (!origin || !tip) return
        svg.setAttribute('viewBox', `0 0 ${window.innerWidth} ${window.innerHeight}`)
        const { x: x1, y: y1 } = origin, { x: x2, y: y2 } = tip
        const length = Math.hypot(x2-x1,y2-y1)||1, ux=(x2-x1)/length, uy=(y2-y1)/length, size=Math.min(9,length/2), half=size*.42, bx=x2-ux*size, by=y2-uy*size
        circle.setAttribute('cx',String(x1)); circle.setAttribute('cy',String(y1)); line.setAttribute('x1',String(x1)); line.setAttribute('y1',String(y1)); line.setAttribute('x2',String(bx)); line.setAttribute('y2',String(by))
        head.setAttribute('points',`${x2},${y2} ${bx-uy*half},${by+ux*half} ${bx+uy*half},${by-ux*half}`)
      }
      const schedule = () => { if (!removed && !frame) frame = requestAnimationFrame(update) }
      window.addEventListener('resize', schedule)
      layers.push({ dispose() { removed = true; cancelAnimationFrame(frame); observers.forEach(observer=>observer?.disconnect()); window.removeEventListener('resize',schedule); svg.remove() } })
      for (const [endpoint, point] of [from,to].entries()) {
        const area = {startRow:point.row,endRow:point.row,startColumn:point.column,endColumn:point.column}
        install(area, `${prefix}-endpoint-${index}-${endpoint}`, () => h('div', { 'aria-hidden': true, style: { width: '100%', height: '100%', pointerEvents: 'none' }, ref: (element: HTMLDivElement | null) => {
          observers[endpoint]?.disconnect(); observers[endpoint] = undefined
          endpoints[endpoint] = element
          if (element) {
            const observer = new MutationObserver(schedule); observers[endpoint] = observer
            // 仅监听当前官方float的祖先style，不扫描全页，也不常驻逐帧轮询。
            for (let node = element.parentElement; node && node !== document.body; node = node.parentElement) observer.observe(node,{attributes:true,attributeFilter:['style','class']})
          }
          schedule()
        } }))
      }
      schedule()
    })
    return { dispose }
  } catch (error) { dispose(); throw error }
}
