// GenOffice f8c17004 StylesPane / StyleDialog 的受限字段协议；定义仍交给原生 StyleUpsert 写入。
import type { StyleInfo } from '../packages/docx-engine/src/types'
import { pendingHeadingLevel, type StyleUpsert } from '../packages/docx-engine/src/style-upsert'

const record = (value: unknown): Record<string, any> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('docx_style_definition_invalid')
  return value as Record<string, any>
}
const keys = (value: Record<string, any>, allowed: string[]) => {
  if (Object.keys(value).some(key => !allowed.includes(key))) throw new Error('docx_style_definition_field_invalid')
}
const label = (value: unknown, max = 255): value is string => typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f\x7f]/.test(value)
export function validateStylesPaneUpserts(values: unknown[], styles: ReadonlyMap<string, StyleInfo>): StyleUpsert[] {
  if (values.length > 200) throw new Error('docx_style_definition_limit')
  const byId = new Map<string, StyleUpsert>()
  for (const value of values) {
    const up = record(value); keys(up, ['styleId', 'type', 'name', 'basedOn', 'rPr', 'pPr'])
    if (!label(up.styleId) || byId.has(up.styleId)) throw new Error('docx_style_definition_id_invalid')
    const old = styles.get(up.styleId), type = old?.type ?? up.type
    if (!['paragraph', 'character'].includes(type) || old?.linkedCharShell || up.type !== undefined && up.type !== type || !old && !label(up.name)) throw new Error('docx_style_definition_type_invalid')
    if (up.name !== undefined && !label(up.name)) throw new Error('docx_style_definition_name_invalid')
    if (up.basedOn !== undefined && up.basedOn !== null && !label(up.basedOn)) throw new Error('docx_style_definition_base_invalid')
    if (up.rPr !== undefined) {
      const r = record(up.rPr); keys(r, ['font', 'eastAsiaFont', 'sizeHalfPoints', 'bold', 'italic', 'color'])
      for (const key of ['font', 'eastAsiaFont']) if (r[key] !== undefined && r[key] !== null && !label(r[key], 128)) throw new Error('docx_style_definition_font_invalid')
      if (r.sizeHalfPoints !== undefined && r.sizeHalfPoints !== null && (!Number.isInteger(r.sizeHalfPoints) || r.sizeHalfPoints < 2 || r.sizeHalfPoints > 3276)) throw new Error('docx_style_definition_size_invalid')
      for (const key of ['bold', 'italic']) if (r[key] !== undefined && typeof r[key] !== 'boolean') throw new Error('docx_style_definition_boolean_invalid')
      if (r.color !== undefined && r.color !== null && (typeof r.color !== 'string' || !/^[A-F\d]{6}$/i.test(r.color))) throw new Error('docx_style_definition_color_invalid')
    }
    if (up.pPr !== undefined) {
      const p = record(up.pPr); keys(p, ['align', 'spaceBeforeTwips', 'spaceAfterTwips', 'lineSpacing'])
      if (type !== 'paragraph') throw new Error('docx_style_definition_paragraph_invalid')
      if (p.align !== undefined && p.align !== null && !['left', 'center', 'right', 'justify'].includes(p.align)) throw new Error('docx_style_definition_alignment_invalid')
      for (const key of ['spaceBeforeTwips', 'spaceAfterTwips']) if (p[key] !== undefined && p[key] !== null && (!Number.isInteger(p[key]) || p[key] < 0 || p[key] > 31680)) throw new Error('docx_style_definition_spacing_invalid')
      if (p.lineSpacing !== undefined && p.lineSpacing !== null && ![1, 1.15, 1.5, 2, 2.5, 3].includes(p.lineSpacing)) throw new Error('docx_style_definition_line_invalid')
    }
    byId.set(up.styleId, JSON.parse(JSON.stringify(up)))
  }
  const effective = (id: string) => {
    const old = styles.get(id), up = byId.get(id)
    return old || up ? { type: old?.type ?? up?.type, name: up?.name ?? old?.name ?? id, basedOn: up?.basedOn === undefined ? old?.basedOn : up.basedOn, linkedCharShell: old?.linkedCharShell } : undefined
  }
  const names = new Map<string, string>()
  for (const id of new Set([...styles.keys(), ...byId.keys()])) {
    const item = effective(id)!
    // 来源本身允许同名；只约束本次新增/改名，不能让无关旧定义阻断编辑。
    const name = item.name.toLowerCase(), previous = names.get(name)
    if (previous && previous !== id && (byId.get(id)?.name !== undefined || byId.get(previous)?.name !== undefined)) throw new Error('docx_style_definition_name_taken')
    names.set(name, id)
    if (!byId.has(id)) continue
    const seen = new Set<string>(); let cursor: string | null | undefined = id
    while (cursor) {
      if (seen.has(cursor)) throw new Error('docx_style_definition_inheritance_cycle')
      seen.add(cursor); const parent = effective(cursor)
      if (!parent || parent.type !== item.type || parent.linkedCharShell) throw new Error('docx_style_definition_inheritance_invalid')
      cursor = parent.basedOn
    }
  }
  return [...byId.values()]
}

/** 同步元数据只用于协议/标题节点投影；显示继承由 previewFontSettings 原生解析。 */
export function stylesPaneCatalog(styles: ReadonlyMap<string, StyleInfo>, upserts: StyleUpsert[]): Map<string, StyleInfo> {
  const result = new Map(styles), pending = new Map(upserts.map(up => [up.styleId, up]))
  for (const up of upserts) {
    const old = styles.get(up.styleId)
    result.set(up.styleId, { ...old, styleId: up.styleId, type: old?.type ?? up.type ?? 'paragraph', name: up.name ?? old?.name ?? up.styleId,
      basedOn: up.basedOn === undefined ? old?.basedOn : up.basedOn ?? undefined,
      headingLevel: pendingHeadingLevel(up.styleId, id => pending.get(id), id => styles.get(id)) })
  }
  return result
}
