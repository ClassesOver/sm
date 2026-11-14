/**
 * 固定源 Design ▸ Page Borders（ribbon-design-tab.tsx + PageBorderDialog.tsx）的严格写回边界：
 * 页面边框是节属性（w:sectPr/w:pgBorders），经现有 setSectionLayout 的 values.pageBorder / pageBorderProps
 * 交给固定引擎 applySectionSettings → pageBordersXml 写入，不另写 OOXML。
 * - pageBorder:true 且无 pageBorderProps：固定源“方框(单实线)”（引擎 legacy 单线框）。
 * - pageBorder:false：去掉边框。
 * - pageBorderProps：对话框结果；样式/宽度/艺术型取值表与固定源 LINE_STYLES/LINE_WIDTHS/ART_NAMES 一致（page-border-presets.json）。
 * 保存后按节独立回读，逐项核对。
 */
import type { SectionSettings } from '@genoffice/docx-engine'
import presets from './page-border-presets.json' with { type: 'json' }

export const PAGE_BORDER_LINE_STYLES: readonly string[] = presets.lineStyles
export const PAGE_BORDER_WIDTHS: readonly number[] = presets.lineWidths
export const PAGE_BORDER_ART_NAMES: readonly string[] = presets.artNames
const SIDES = ['top', 'left', 'bottom', 'right'] as const
type Props = NonNullable<SectionSettings['pageBorderProps']>
const fail = (code = 'page_border_invalid'): never => { throw new Error(code) }
const keysOk = (value: object, allowed: string[]) => Object.keys(value).every(key => allowed.includes(key))
const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)

/** 校验 setSectionLayout.values 中的页面边框字段（不含则跳过）。 */
export function validatePageBorderValues(values: Record<string, unknown>): void {
  if (!('pageBorder' in values) && !('pageBorderProps' in values)) return
  if (typeof values.pageBorder !== 'boolean') fail()
  if (!('pageBorderProps' in values)) return
  const props = values.pageBorderProps
  if (props === null) return
  if (!values.pageBorder || !isObject(props) || !keysOk(props, ['display', 'offsetFrom', 'zOrder', 'spacePt', 'widthPt', 'color', 'sides'])) fail()
  const p = props as Record<string, unknown>
  if (p.display !== undefined && !['firstPage', 'notFirstPage'].includes(p.display as string)) fail()
  if (!['page', 'text'].includes(p.offsetFrom as string)) fail()
  if (p.zOrder !== undefined && p.zOrder !== 'back') fail()
  if (p.color !== undefined && (typeof p.color !== 'string' || !/^[0-9A-F]{6}$/.test(p.color))) fail()
  if (!isObject(p.sides) || !Object.keys(p.sides).length || !keysOk(p.sides, [...SIDES])) fail()
  const sides = p.sides as Record<string, unknown>
  let maxSpace = 0, maxWidth = 0
  for (const name of Object.keys(sides)) {
    const side = sides[name]
    if (!isObject(side) || !keysOk(side, ['val', 'widthPt', 'spacePt', 'color', 'art', 'shadow', 'frame'])) fail()
    const s = side as Record<string, unknown>
    const art = s.art === true
    if (s.art !== undefined && s.art !== true) fail()
    if (typeof s.val !== 'string' || !(art ? PAGE_BORDER_ART_NAMES : PAGE_BORDER_LINE_STYLES).includes(s.val)) fail()
    if (typeof s.widthPt !== 'number' || (art ? !Number.isInteger(s.widthPt) || s.widthPt < 1 || s.widthPt > 31 : !PAGE_BORDER_WIDTHS.includes(s.widthPt))) fail()
    if (typeof s.spacePt !== 'number' || !Number.isInteger(s.spacePt) || s.spacePt < 0 || s.spacePt > 31) fail()
    if (s.color !== undefined && (typeof s.color !== 'string' || !/^[0-9A-F]{6}$/.test(s.color) || art)) fail()
    for (const flag of ['shadow', 'frame'] as const) if (s[flag] !== undefined && (s[flag] !== true || art)) fail()
    if (s.shadow && s.frame) fail()
    maxSpace = Math.max(maxSpace, s.spacePt as number); maxWidth = Math.max(maxWidth, s.widthPt as number)
  }
  if (p.spacePt !== maxSpace || p.widthPt !== maxWidth) fail()
}

/** 归一化后的期望/实际边框，便于独立回读比较；null = 无边框。 */
export function normalizedPageBorder(settings: { pageBorder?: boolean; pageBorderProps?: SectionSettings['pageBorderProps'] }, written = false): unknown {
  if (!settings.pageBorder) return null
  const props = settings.pageBorderProps
  // 固定源“方框(单实线)”：引擎写 legacy 单线框（四边 single 0.5pt、距页边 24pt、颜色 auto）
  const effective: Props = props ?? { offsetFrom: 'page', spacePt: 24, widthPt: 0.5, sides: Object.fromEntries(SIDES.map(side => [side, { val: 'single', widthPt: 0.5, spacePt: 24 }])) }
  const sides = Object.fromEntries(SIDES.filter(side => effective.sides?.[side]).map(side => {
    const s = effective.sides![side]!
    return [side, { val: s.val, widthPt: s.art ? Math.round(s.widthPt) : Math.round(s.widthPt * 8) / 8, spacePt: Math.round(s.spacePt), color: s.color?.toUpperCase() ?? null, art: !!s.art, shadow: !!s.shadow, frame: !!s.frame }]
  }))
  return { display: effective.display ?? null, offsetFrom: effective.offsetFrom ?? (written ? 'text' : 'text'), zOrder: effective.zOrder ?? null, sides }
}
