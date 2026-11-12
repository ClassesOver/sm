/**
 * 固定源 Design ▸ Page Color（ribbon-design-tab.tsx onPageColor → 保存时 SaveOptions.pageColor）：
 * 整篇文档一个 <w:background w:color>，设置时引擎同时写 settings 的 <w:displayBackgroundShape/>。
 * 原生桥接只接受“无背景”或“单个纯色 w:color 背景”的来源；主题色、VML 填充等复杂背景保持只读，
 * 以免引擎改写时丢失原有效果。修改按背景 XML 摘要绑定来源，写后独立回读。
 */
import { createHash } from 'node:crypto'

export interface DocxPageColorModel {
  /** 当前页面颜色（6 位大写十六进制，无 #）；null = 无页面颜色 */
  color: string | null
  editable: boolean
  readOnlyReason: string | null
  /** 来源 w:background 原文（无则为空串）的 SHA-256 */
  expectedBackgroundSha256: string
}

export interface DocxPageColorOperation {
  kind: 'setPageColor'
  expectedBackgroundSha256: string
  color: string | null
}

const BACKGROUND = /<w:background\b[^>]*\/>|<w:background\b[^>]*>[\s\S]*?<\/w:background>/g
const HEX = /^[0-9A-F]{6}$/
const sha256 = (value: string) => createHash('sha256').update(value).digest('hex')

export function inspectDocxPageColor(documentXml: string, protectedSource: boolean): DocxPageColorModel {
  const backgrounds = documentXml.match(BACKGROUND) ?? []
  const expectedBackgroundSha256 = sha256(backgrounds.join(''))
  const readonly = (reason: string, color: string | null = null): DocxPageColorModel => ({ color, editable: false, readOnlyReason: reason, expectedBackgroundSha256 })
  if (protectedSource) return readonly('文档受保护，页面颜色保持原样')
  if (!backgrounds.length) return { color: null, editable: true, readOnlyReason: null, expectedBackgroundSha256 }
  if (backgrounds.length > 1) return readonly('来源含多个页面背景，保持原样')
  const element = backgrounds[0]!
  const attributes = [...element.matchAll(/\s([\w:]+)\s*=\s*"([^"]*)"/g)]
  const color = attributes.find(([, name]) => name === 'w:color')?.[2]?.toUpperCase() ?? null
  if (!element.endsWith('/>') || attributes.some(([, name]) => name !== 'w:color') || !color || !HEX.test(color)) {
    return readonly('页面背景含主题色、图片或渐变填充，保持原样', color && HEX.test(color) ? color : null)
  }
  return { color, editable: true, readOnlyReason: null, expectedBackgroundSha256 }
}

/** 整批先验：至多一条，来源可编辑、摘要一致、颜色为 6 位大写十六进制或 null，且与当前值不同。返回要写入的值（undefined = 不写）。 */
export function validateDocxPageColorOperations(operations: Record<string, unknown>[], model: DocxPageColorModel): string | null | undefined {
  if (!operations.length) return undefined
  if (operations.length !== 1) throw new Error('docx_page_color_batch_conflict')
  const op = operations[0]!
  if (Object.keys(op).sort().join() !== 'color,expectedBackgroundSha256,kind' || op.kind !== 'setPageColor') throw new Error('docx_page_color_operation_invalid')
  if (!model.editable) throw new Error('docx_page_color_source_unsupported')
  if (op.expectedBackgroundSha256 !== model.expectedBackgroundSha256) throw new Error('docx_page_color_anchor_invalid')
  if (op.color !== null && (typeof op.color !== 'string' || !HEX.test(op.color))) throw new Error('docx_page_color_operation_invalid')
  if (op.color === model.color) throw new Error('docx_page_color_unchanged')
  return op.color as string | null
}

/** 写后独立回读：document.xml 的背景与 settings 的显示开关都与请求一致。 */
export function assertDocxPageColorWritten(documentXml: string, settingsXml: string, color: string | null): void {
  const backgrounds = documentXml.match(BACKGROUND) ?? []
  const ok = color === null
    ? backgrounds.length === 0
    : backgrounds.length === 1 && backgrounds[0] === `<w:background w:color="${color}"/>` && /<w:displayBackgroundShape\b/.test(settingsXml)
  if (!ok) throw new Error('docx_page_color_write_not_applied')
}
