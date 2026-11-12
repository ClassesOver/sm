/**
 * 固定源 Design ▸ Page Color（ribbon-design-tab.tsx onPageColor + RibbonColorPalette）：
 * 选择主题/标准色或“无颜色”，保存时整篇写 w:background。原生草稿为一条文档级 setPageColor，
 * 按来源背景摘要绑定；与来源相同即撤回该修改。
 */
import type { NativeOperation } from './native-draft'

export interface DocxPageColorModel { color: string | null; editable: boolean; readOnlyReason: string | null; expectedBackgroundSha256: string }

const HEX = /^[0-9A-F]{6}$/
const SHA = /^[a-f0-9]{64}$/

export function docxPageColorModel(value: unknown): DocxPageColorModel | null {
  if (!value || typeof value !== 'object') return null
  const model = value as Record<string, unknown>
  if (typeof model.editable !== 'boolean' || typeof model.expectedBackgroundSha256 !== 'string' || !SHA.test(model.expectedBackgroundSha256)
    || (model.color !== null && (typeof model.color !== 'string' || !HEX.test(model.color)))) return null
  return { color: model.color as string | null, editable: model.editable, readOnlyReason: typeof model.readOnlyReason === 'string' ? model.readOnlyReason : null, expectedBackgroundSha256: model.expectedBackgroundSha256 }
}

/** 草稿中的页面颜色修改（恢复与提交前都按来源校验；不一致即抛错，原草稿保留）。 */
export function docxPageColorOperations(operations: NativeOperation[], model: DocxPageColorModel | null): NativeOperation[] {
  const found = operations.filter(operation => operation.kind === 'setPageColor')
  if (!found.length) return []
  if (found.length > 1 || !model) throw new Error('页面颜色草稿无效或来源未提供页面颜色能力；原草稿已保留')
  const operation = found[0]!
  if (Object.keys(operation).sort().join() !== 'color,expectedBackgroundSha256,kind' || operation.expectedBackgroundSha256 !== model.expectedBackgroundSha256
    || (operation.color !== null && (typeof operation.color !== 'string' || !HEX.test(operation.color))) || operation.color === model.color) throw new Error('页面颜色草稿与当前来源不一致；原草稿已保留')
  if (!model.editable) throw new Error(model.readOnlyReason ?? '此文档的页面颜色不能修改')
  return [{ ...operation }]
}

/** 生效中的页面颜色：草稿优先，否则来源值。 */
export function effectiveDocxPageColor(operations: NativeOperation[], model: DocxPageColorModel | null): string | null {
  const pending = operations.find(operation => operation.kind === 'setPageColor')
  return pending ? (pending.color as string | null) : model?.color ?? null
}

/** 选色后的完整非正文草稿：替换已有的 setPageColor；与来源相同则只撤回。 */
export function withDocxPageColor(operations: NativeOperation[], model: DocxPageColorModel | null, color: string | null): NativeOperation[] {
  if (!model) throw new Error('当前来源未提供页面颜色能力')
  if (!model.editable) throw new Error(model.readOnlyReason ?? '此文档的页面颜色不能修改')
  const next = color === null ? null : color.toUpperCase()
  if (next !== null && !HEX.test(next)) throw new Error('页面颜色须为 6 位十六进制颜色')
  const others = operations.filter(operation => operation.kind !== 'setPageColor')
  return next === model.color ? others : [...others, { kind: 'setPageColor', expectedBackgroundSha256: model.expectedBackgroundSha256, color: next }]
}
