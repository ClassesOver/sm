import { diffLines } from 'diff'

export interface ConflictLine {
  kind: 'base' | 'local' | 'remote'
  text: string
}

export function conflictLines(base: string, local: string, remote: string): ConflictLine[] {
  const lines: ConflictLine[] = []
  const append = (kind: ConflictLine['kind'], value: string) => {
    value.split('\n').forEach((text) => {
      if (text) lines.push({ kind, text })
    })
  }
  diffLines(base, local).forEach((part) => append(part.added ? 'local' : 'base', part.value))
  diffLines(base, remote).forEach((part) => append(part.added ? 'remote' : 'base', part.value))
  return lines
}
