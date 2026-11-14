import { normalizeDocxCustomList, type DocxCustomListDefinition } from './docx-custom-list'

/** 原始num身份或尚未保存的自定义定义；覆盖仍交给源restartNums writer。 */
export interface DocxNumberingBinding {
  id: string
  sourceNumId?: string
  custom?: DocxCustomListDefinition
  defaultNumbering?: { id: string; kind: 'bullet' | 'ordered' }
  startOverrides?: Record<string, number>
}
export function normalizeDocxNumberingBinding(raw: unknown): DocxNumberingBinding {
  const fail = (): never => { throw new Error('编号值绑定无效') }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail()
  const value = raw as Record<string, unknown>
  if (Object.keys(value).some(key => !['id', 'sourceNumId', 'custom', 'defaultNumbering', 'startOverrides'].includes(key))
    || typeof value.id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(value.id)
    || [value.sourceNumId, value.custom, value.defaultNumbering].filter(v => v !== undefined).length !== 1) fail()
  const binding: DocxNumberingBinding = { id: value.id as string }
  if (value.sourceNumId !== undefined) {
    if (typeof value.sourceNumId !== 'string' || !/^[1-9][0-9]{0,31}$/.test(value.sourceNumId)) fail()
    binding.sourceNumId = value.sourceNumId as string
  } else if (value.custom !== undefined) binding.custom = normalizeDocxCustomList(value.custom)
  else {
    const item = value.defaultNumbering as Record<string, unknown> | null
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(k => !['id', 'kind'].includes(k))
      || typeof item.id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(item.id) || !['bullet', 'ordered'].includes(String(item.kind))) fail()
    binding.defaultNumbering = { id: item!.id as string, kind: item!.kind as 'bullet' | 'ordered' }
  }
  if (value.startOverrides !== undefined) {
    if (!value.startOverrides || typeof value.startOverrides !== 'object' || Array.isArray(value.startOverrides)) fail()
    const entries = Object.entries(value.startOverrides as Record<string, unknown>)
    if (!entries.length || entries.some(([level, start]) => !/^[0-8]$/.test(level) || typeof start !== 'number' || !Number.isInteger(start) || start < 0 || start > 32767)) fail()
    binding.startOverrides = Object.fromEntries(entries) as Record<string, number>
  }
  return binding
}
export function docxNumberingBindingId(binding: DocxNumberingBinding): string {
  return binding.startOverrides ? `native-value-${binding.id}` : binding.sourceNumId ?? (binding.custom ? `native-custom-${binding.custom.id}` : `native-default-${binding.defaultNumbering!.id}`)
}

/** 与源 createNumberingDef 相同的五级即时编号覆盖层；持久化仍调用默认 newDefs writer。 */
export function docxDefaultNumberingLevels(kind: 'bullet' | 'ordered') {
  return Object.fromEntries(Array.from({ length: 5 }, (_, i) => [i, {
    numFmt: kind === 'bullet' ? 'bullet' : 'decimal', lvlText: kind === 'bullet' ? '' : `%${i + 1}.`,
    start: 1, indentLeft: 720 * (i + 1), hanging: 360,
  }]))
}
