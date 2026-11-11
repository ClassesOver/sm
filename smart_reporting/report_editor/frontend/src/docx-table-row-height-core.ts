import type { Node as PmNode } from '@tiptap/pm/model'
import { TableMap } from '@tiptap/pm/tables'
export { Schema } from '@tiptap/pm/model'
export type TableRowHeightStep = { top: number; bottom: number; heightTwips: number | null } | { kind: 'distributeTableRows'; top: number; bottom: number; heightTwips: number }
function fail(): never { throw new Error('docx_table_row_height_invalid') }
const positive = (n: unknown): n is number => Number.isSafeInteger(n) && Number(n) > 0
/** 固定源Ribbon设置保留exact；distributeRowsEvenly强制atLeast；清除归null，其余不变。 */
export function applyTableRowHeightSteps(table: PmNode, maxHeightTwips: number, steps: readonly TableRowHeightStep[]) {
  if (!positive(maxHeightTwips) || maxHeightTwips > 31680 || !Array.isArray(steps) || !steps.length || steps.length > 50 || table.type.spec.tableRole !== 'table' || !table.childCount || table.childCount > 100) fail()
  let cells = 0
  table.forEach(row => {
    if (row.type.spec.tableRole !== 'row' || row.childCount > 30 || row.attrs.heightTwips != null && !positive(row.attrs.heightTwips) || ![null, undefined, 'exact', 'atLeast'].includes(row.attrs.heightRule)) fail()
    row.forEach(cell => { if (!positive(cell.attrs.colspan) || cell.attrs.colspan > 30 || !positive(cell.attrs.rowspan) || cell.attrs.rowspan > 100 || cell.attrs.gridGap || ++cells > 1000) fail() })
  })
  table.check()
  const map = TableMap.get(table)
  if (map.problems?.length || map.width < 1 || map.width > 30 || map.width * map.height > 1000) fail()
  const heights: (number | null)[] = [], rules: ('exact' | 'atLeast' | null)[] = []
  table.forEach(row => { heights.push(row.attrs.heightTwips ?? null); rules.push(row.attrs.heightTwips == null ? null : row.attrs.heightRule === 'exact' ? 'exact' : 'atLeast') })
  const touched = new Set<number>()
  for (const step of steps) {
    const distribute = step && 'kind' in step && step.kind === 'distributeTableRows'
    if (!step || typeof step !== 'object' || Array.isArray(step) || Object.keys(step).length !== (distribute ? 4 : 3) || Object.keys(step).some(k => !['top', 'bottom', 'heightTwips', ...(distribute ? ['kind'] : [])].includes(k)) || distribute && (step.heightTwips === null || step.heightTwips > 31680) || !Number.isSafeInteger(step.top) || !Number.isSafeInteger(step.bottom) || step.top < 0 || step.bottom <= step.top || step.bottom > table.childCount || step.heightTwips !== null && !positive(step.heightTwips)) fail()
    for (let r = step.top; r < step.bottom; r++) { heights[r] = step.heightTwips === null ? null : distribute ? step.heightTwips : Math.min(step.heightTwips, maxHeightTwips); rules[r] = heights[r] === null ? null : !distribute && rules[r] === 'exact' ? 'exact' : 'atLeast'; touched.add(r) }
  }
  const rows: PmNode[] = []
  table.forEach((row, _offset, r) => rows.push(touched.has(r) ? row.type.create({ ...row.attrs, heightTwips: heights[r], heightRule: rules[r] }, row.content, row.marks) : row))
  return { table: table.type.create(table.attrs, rows, table.marks), rowHeightsTwips: heights, rowHeightRules: rules }
}
