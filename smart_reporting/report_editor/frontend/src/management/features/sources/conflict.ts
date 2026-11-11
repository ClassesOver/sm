/** 仅比较公开表单字段，调用方必须排除 DSN 等敏感字段。 */
export function mergeDraft<T extends Record<string, string | null>>(
  base: T,
  local: T,
  latest: T,
): { values: T; conflicts: (keyof T)[] } {
  const values = { ...latest },
    conflicts: (keyof T)[] = []
  for (const field of Object.keys(base) as (keyof T)[]) {
    if (local[field] === base[field]) continue
    values[field] = local[field]
    if (latest[field] !== base[field] && latest[field] !== local[field])
      conflicts.push(field)
  }
  return { values, conflicts }
}
