export interface DocxDropCap { type: 'drop' | 'margin'; lines: number }
/** 固定源 InsertTab 的 drop/margin 首字下沉；行数沿原生模型保留。 */
export function normalizeDocxDropCap(value: unknown): DocxDropCap | null {
  if (value === null) return null
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some(key => !['type', 'lines'].includes(key))) throw new Error('首字下沉字段无效')
  const cap = value as DocxDropCap
  if (!['drop', 'margin'].includes(cap.type) || !Number.isSafeInteger(cap.lines) || cap.lines < 1 || cap.lines > 10) throw new Error('首字下沉类型或行数无效')
  return { type: cap.type, lines: cap.lines }
}
export function docxDropCapAttribute(value: unknown): DocxDropCap | null {
  if (value == null) return null
  if (typeof value !== 'string') throw new Error('首字下沉属性无效')
  return normalizeDocxDropCap(JSON.parse(value))
}
