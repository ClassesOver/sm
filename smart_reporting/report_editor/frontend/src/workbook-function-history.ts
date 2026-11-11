export const HISTORY_LIMIT = 10

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

/** Recent inputs, newest first. Malformed or unavailable storage reads as empty. */
export function loadHistory(storage: StorageLike | undefined, key: string): string[] {
  try {
    const raw = storage?.getItem(key)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((entry): entry is string => typeof entry === 'string')
      .slice(0, HISTORY_LIMIT)
  } catch {
    return []
  }
}

/** Prepends a committed input, deduplicated, capped; returns the new list. */
export function pushHistory(
  storage: StorageLike | undefined,
  key: string,
  value: string,
): string[] {
  const trimmed = value.trim()
  const current = loadHistory(storage, key)
  if (trimmed === '') return current
  const next = [trimmed, ...current.filter((entry) => entry !== trimmed)].slice(0, HISTORY_LIMIT)
  try {
    storage?.setItem(key, JSON.stringify(next))
  } catch {
    // quota/private-mode failures just lose history persistence
  }
  return next
}