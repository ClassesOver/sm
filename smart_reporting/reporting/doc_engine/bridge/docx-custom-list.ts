import type { CustomNumberingLevel } from '../packages/docx-engine/src/blank.ts'

export interface DocxCustomListDefinition { id: string; levels: CustomNumberingLevel[] }
const levelKeys = new Set(['numFmt', 'customFormat', 'lvlText', 'indentLeft', 'hanging', 'start', 'suff', 'lvlJc', 'tabStop', 'font', 'szHalfPoints', 'color', 'bold', 'italic', 'pStyle', 'isLgl', 'lvlRestart'])
function invalid(): never { throw new Error('多级列表定义无效') }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  return value as Record<string, unknown>
}
function string(value: unknown, limit: number, empty = false): string {
  if (typeof value !== 'string' || (!empty && !value.length) || value.length > limit || /[\x00-\x08\x0b-\x1f\ufffe\uffff]/.test(value)) invalid()
  return value
}
/** 只接受源对话框的结构化值；真实 numId 由保存桥分配，不接受 XML、路径或图片身份。 */
export function normalizeDocxCustomList(value: unknown): DocxCustomListDefinition {
  const input = record(value)
  if (Object.keys(input).some(key => !['id', 'levels'].includes(key))) invalid()
  const id = string(input.id, 100)
  if (!/^[A-Za-z0-9_-]+$/.test(id) || !Array.isArray(input.levels) || input.levels.length < 1 || input.levels.length > 9) invalid()
  const levels = input.levels.map((raw, ilvl) => {
    const level = record(raw)
    if (Object.keys(level).some(key => !levelKeys.has(key))) invalid()
    const normalized: Record<string, unknown> = {
      numFmt: string(level.numFmt, 64), lvlText: string(level.lvlText, 256, true), indentLeft: level.indentLeft,
    }
    if (!/^[A-Za-z][A-Za-z0-9]*$/.test(normalized.numFmt as string)) invalid()
    const limits: Record<string, [number, number]> = { indentLeft: [0, 31680], hanging: [0, 31680], start: [0, 2147483647], tabStop: [0, 31680], szHalfPoints: [2, 800], lvlRestart: [0, ilvl] }
    for (const [key, [min, max]] of Object.entries(limits)) {
      const entry = level[key]
      if (entry === undefined && key !== 'indentLeft') continue
      if (typeof entry !== 'number' || !Number.isSafeInteger(entry) || entry < min || entry > max) invalid()
      normalized[key] = entry
    }
    for (const key of ['customFormat', 'font', 'pStyle'] as const) if (level[key] !== undefined) normalized[key] = string(level[key], key === 'customFormat' ? 2048 : 200)
    for (const key of ['bold', 'italic', 'isLgl'] as const) if (level[key] !== undefined) {
      if (typeof level[key] !== 'boolean') invalid()
      normalized[key] = level[key]
    }
    if (level.color !== undefined) {
      if (typeof level.color !== 'string' || !/^(?:[0-9A-Fa-f]{6}|auto)$/.test(level.color)) invalid()
      normalized.color = level.color
    }
    for (const [key, allowed] of [['suff', ['tab', 'space', 'nothing']], ['lvlJc', ['left', 'center', 'right']]] as const) if (level[key] !== undefined) {
      if (!allowed.includes(level[key] as never)) invalid()
      normalized[key] = level[key]
    }
    return normalized as unknown as CustomNumberingLevel
  })
  return { id, levels }
}
export function customListLevel(definition: DocxCustomListDefinition, ilvl: unknown) {
  if (typeof ilvl !== 'number' || !Number.isInteger(ilvl) || !definition.levels[ilvl]) invalid()
  return { kind: definition.levels[ilvl]!.numFmt === 'bullet' ? 'bullet' as const : 'ordered' as const, numId: `native-custom-${definition.id}`, ilvl }
}
