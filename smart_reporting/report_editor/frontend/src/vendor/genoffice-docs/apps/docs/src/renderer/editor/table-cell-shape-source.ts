// Extracted unchanged from genoffice f8c17004fb730df11f0f743164ffd8b4281bb38c
// apps/docs/src/renderer/editor/table-ops.ts:113–374 (split helper closure).
import type { Fragment, Node as PmNode, Schema } from '@tiptap/pm/model'
import type { Command, Transaction } from '@tiptap/pm/state'
import { TextSelection } from '@tiptap/pm/state'
import { CellSelection, TableMap, isInTable, mergeCells, selectedRect } from '@tiptap/pm/tables'

interface GridCell {
  node: PmNode
  top: number
  left: number
  rowspan: number
  colspan: number
}

interface Grid {
  map: TableMap
  cells: GridCell[]
  rows: PmNode[]
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.floor(n)))

/** split `total` into `parts` near-equal integers, the remainder going to the first ones */
const partition = (total: number, parts: number): number[] =>
  Array.from({ length: parts }, (_, i) => Math.floor(total / parts) + (i < total % parts ? 1 : 0))

function gridOf(table: PmNode): Grid {
  const map = TableMap.get(table)
  const cells: GridCell[] = []
  const seen = new Set<number>()
  for (const pos of map.map) {
    if (seen.has(pos)) continue
    seen.add(pos)
    const r = map.findCell(pos)
    cells.push({
      node: table.nodeAt(pos)!,
      top: r.top,
      left: r.left,
      rowspan: r.bottom - r.top,
      colspan: r.right - r.left,
    })
  }
  const rows: PmNode[] = []
  table.forEach((row) => rows.push(row))
  return { map, cells, rows }
}

function buildTable(
  table: PmNode,
  rows: PmNode[],
  cells: GridCell[],
  attrs: Record<string, unknown> = table.attrs,
): PmNode {
  const byRow: GridCell[][] = rows.map(() => [])
  for (const c of cells) byRow[c.top]?.push(c)
  return table.type.create(
    attrs,
    rows.map((row, i) =>
      row.type.create(
        row.attrs,
        byRow[i]
          .sort((a, b) => a.left - b.left)
          .map((c) =>
            c.node.type.create(
              { ...c.node.attrs, colspan: c.colspan, rowspan: c.rowspan },
              c.node.content,
            ),
          ),
      ),
    ),
  )
}

/** an empty paragraph shaped like the cell's first one (Word keeps the paragraph format) */
function blankCellContent(schema: Schema, like: PmNode): Fragment | PmNode {
  const first = like.firstChild
  const attrs =
    first?.type.name === 'docParagraph' ? { ...first.attrs, docxIndex: null } : { docxIndex: null }
  return schema.nodes.docParagraph.create(attrs)
}

function cellWidths(cell: GridCell): number[] | null {
  const w = cell.node.attrs.colwidth as number[] | null
  return Array.isArray(w) && w.length === cell.colspan && w.every((v) => v > 0) ? w : null
}

const blankRowAttrs = (row: PmNode): Record<string, unknown> => ({
  ...row.attrs,
  heightTwips: null,
  heightRule: null,
  repeatHeader: false,
  repeatHeaderEdited: false,
  // the copied cantSplit has no raw trPr behind it: mark it edited so the save writes it
  cantSplitEdited: true,
  rawTrPr: null,
  rowRevision: null,
})

/**
 * Split the cell covering (row, col) into R×C cells. Extra columns widen the
 * grid inside the cell's span (other rows' cells spanning it grow their
 * colspan and keep their width); extra rows are inserted after the cell's
 * bottom edge (neighbours ending there grow their rowspan).
 */
export function splitGridCell(
  table: PmNode,
  at: { row: number; col: number },
  rowsN: number,
  colsN: number,
): { table: PmNode; focus: { top: number; left: number } } | null {
  const R = clamp(rowsN, 1, 50)
  const C = clamp(colsN, 1, 50)
  const g = gridOf(table)
  const T = g.cells.find(
    (c) =>
      c.top <= at.row &&
      at.row < c.top + c.rowspan &&
      c.left <= at.col &&
      at.col < c.left + c.colspan,
  )
  if (!T || T.node.attrs.gridGap || (R === 1 && C === 1)) return null
  const { colspan: cs, rowspan: rs } = T

  // ---- columns: k[i] new grid columns per old column i of the cell's span
  const extraCols = Math.max(0, C - cs)
  const k = extraCols > 0 ? partition(C, cs) : Array.from({ length: cs }, () => 1)
  const prefix = (i: number) => k.slice(0, i).reduce((a, b) => a + b, 0)
  const newCol = (x: number) =>
    x <= T.left ? x : x < T.left + cs ? T.left + prefix(x - T.left) : x + extraCols
  const remapWidths = (cell: GridCell): number[] | null => {
    const w = cellWidths(cell)
    if (!w) return null
    const out: number[] = []
    for (let x = cell.left; x < cell.left + cell.colspan; x++) {
      const inSpan = x >= T.left && x < T.left + cs
      const kk = inSpan ? k[x - T.left] : 1
      for (let j = 0; j < kk; j++) out.push(w[x - cell.left] / kk)
    }
    return out
  }
  const placed: GridCell[] = g.cells
    .filter((c) => c !== T)
    .map((c) => {
      const left = newCol(c.left)
      const colspan = newCol(c.left + c.colspan) - left
      const colwidth = remapWidths(c)
      const node =
        colwidth || c.node.attrs.colwidth
          ? c.node.type.create({ ...c.node.attrs, colwidth }, c.node.content)
          : c.node
      return { ...c, node, left, colspan }
    })

  // ---- rows
  const extraRows = Math.max(0, R - rs)
  const insertAt = T.top + rs
  const rows = [...g.rows]
  for (let i = 0; i < extraRows; i++) {
    const template = g.rows[insertAt - 1]
    rows.splice(insertAt, 0, template.type.create(blankRowAttrs(template)))
  }
  for (const c of placed) {
    if (c.top >= insertAt) c.top += extraRows
    else if (c.top + c.rowspan >= insertAt) c.rowspan += extraRows
  }

  // ---- the pieces
  const spans = partition(Math.max(cs, C), C)
  const heights = partition(Math.max(rs, R), R)
  const tW = cellWidths(T)
  const regionWidths = tW
    ? k.flatMap((kk, i) => Array.from({ length: kk }, () => tW[i] / kk))
    : null
  const blank = blankCellContent(table.type.schema, T.node)
  let top = T.top
  for (let ri = 0; ri < R; ri++) {
    let left = T.left
    let cursor = 0
    for (let ci = 0; ci < C; ci++) {
      const span = spans[ci]
      const colwidth = regionWidths ? regionWidths.slice(cursor, cursor + span) : null
      const node = T.node.type.create(
        { ...T.node.attrs, colwidth },
        ri === 0 && ci === 0 ? T.node.content : blank,
      )
      placed.push({ node, top, left, rowspan: heights[ri], colspan: span })
      left += span
      cursor += span
    }
    top += heights[ri]
  }

  const attrs = { ...table.attrs }
  const pct = table.attrs.colWidthsPct as number[] | null
  if (pct && pct.length === g.map.width) {
    attrs.colWidthsPct = pct.flatMap((p, x) =>
      x >= T.left && x < T.left + cs
        ? Array.from({ length: k[x - T.left] }, () => p / k[x - T.left])
        : [p],
    )
  }
  return { table: buildTable(table, rows, placed, attrs), focus: { top: T.top, left: T.left } }
}

function caretIntoCell(
  tr: Transaction,
  tablePos: number,
  table: PmNode,
  top: number,
  left: number,
) {
  const map = TableMap.get(table)
  const pos = tablePos + 1 + map.map[top * map.width + left]
  tr.setSelection(TextSelection.near(tr.doc.resolve(pos + 1)))
}

/** Split Cells… dialog: the selection's top-left cell (or the merged selection) becomes rows × cols */
export function splitCellsInto(rows: number, cols: number, mergeFirst: boolean): Command {
  return (state, dispatch) => {
    if (!isInTable(state)) return false
    const rect = selectedRect(state)
    const tablePos = rect.tableStart - 1
    let tr = state.tr
    // a caret inside an already merged cell also spans several grid columns: only a
    // real multi-cell selection is merged first
    const sel = state.selection
    if (mergeFirst && sel instanceof CellSelection && sel.ranges.length > 1) {
      const captured: { tr?: Transaction } = {}
      if (!mergeCells(state, (t) => (captured.tr = t)) || !captured.tr) return false
      tr = captured.tr
    }
    const table = tr.doc.nodeAt(tablePos)
    if (!table) return false
    // without the merge every selected cell is split; bottom-right first, so the
    // grid growth of one split never moves a cell still waiting its turn
    const targets: Array<{ row: number; col: number }> = []
    if (sel instanceof CellSelection && !tr.docChanged) {
      const map = TableMap.get(table)
      const seen = new Set<number>()
      for (let r = rect.top; r < rect.bottom; r++) {
        for (let c = rect.left; c < rect.right; c++) {
          const pos = map.map[r * map.width + c]
          if (seen.has(pos)) continue
          seen.add(pos)
          const cellRect = map.findCell(pos)
          targets.push({ row: cellRect.top, col: cellRect.left })
        }
      }
      targets.sort((a, b) => b.row - a.row || b.col - a.col)
    } else {
      targets.push({ row: rect.top, col: rect.left })
    }
    let current = table
    let focus: { top: number; left: number } | null = null
    for (const target of targets) {
      const result = splitGridCell(current, target, rows, cols)
      if (!result) continue
      current = result.table
      focus = result.focus
    }
    if (!focus || current === table) return false
    tr.replaceWith(tablePos, tablePos + table.nodeSize, current)
    caretIntoCell(tr, tablePos, current, focus.top, focus.left)
    dispatch?.(tr.scrollIntoView())
    return true
  }
}

