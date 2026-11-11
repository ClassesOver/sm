import type { TableIdentity } from '../../api/contracts'
export const tableKey = (table: TableIdentity) =>
  JSON.stringify([table.database, table.name])
export function selectPage(
  selected: TableIdentity[],
  page: TableIdentity[],
  checked: boolean,
): TableIdentity[] {
  const entries = new Map(selected.map((t) => [tableKey(t), t]))
  for (const table of page) {
    if (checked)
      entries.set(tableKey(table), {
        database: table.database,
        name: table.name,
      })
    else entries.delete(tableKey(table))
  }
  return [...entries.values()]
}
export function tableChanges(
  published: TableIdentity[],
  selected: TableIdentity[],
) {
  const old = new Set(published.map(tableKey)),
    next = new Set(selected.map(tableKey))
  return {
    added: selected.filter((t) => !old.has(tableKey(t))),
    removed: published.filter((t) => !next.has(tableKey(t))),
  }
}
