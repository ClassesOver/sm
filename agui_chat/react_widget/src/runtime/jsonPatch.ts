import { clone } from './utils'

function pathSegments(path: string): string[] {
  return String(path || '')
    .split('/')
    .slice(1)
    .map((segment) => segment.replace(/~1/g, '/').replace(/~0/g, '~'))
}

function containerFor(document: unknown, path: string[]): { target: any; key: string } {
  let target = document as any
  for (let index = 0; index < path.length - 1; index += 1) {
    const segment = path[index]
    if (target[segment] === undefined || target[segment] === null) {
      target[segment] = /^\d+$/.test(path[index + 1]) ? [] : {}
    }
    target = target[segment]
  }
  return { target, key: path[path.length - 1] }
}

export function applyJsonPatch<T>(document: T, patch: unknown): T {
  if (!Array.isArray(patch)) {
    return document
  }
  const next = clone(document)
  patch.forEach((operation) => {
    if (!operation || typeof operation !== 'object') {
      return
    }
    const item = operation as { op?: string; path?: string; value?: unknown }
    const path = pathSegments(item.path || '')
    if (!path.length) {
      return
    }
    const { target, key } = containerFor(next, path)
    if (item.op === 'remove') {
      if (Array.isArray(target)) {
        target.splice(key === '-' ? target.length - 1 : Number(key), 1)
      } else {
        delete target[key]
      }
    } else if (item.op === 'add' || item.op === 'replace') {
      if (Array.isArray(target)) {
        if (key === '-') {
          target.push(item.value)
        } else {
          target[Number(key)] = item.value
        }
      } else {
        target[key] = item.value
      }
    }
  })
  return next
}

export function deepMerge(target: Record<string, unknown>, source: unknown): Record<string, unknown> {
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    return target
  }
  const next = { ...target }
  Object.entries(source as Record<string, unknown>).forEach(([key, value]) => {
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      next[key] &&
      typeof next[key] === 'object' &&
      !Array.isArray(next[key])
    ) {
      next[key] = deepMerge(next[key] as Record<string, unknown>, value)
    } else {
      next[key] = value
    }
  })
  return next
}
