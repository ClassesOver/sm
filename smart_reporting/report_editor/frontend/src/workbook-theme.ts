/**
 * 固定源 Page Layout ▸ Themes / Colors / Fonts（apps/sheets/src/renderer/page-layout-actions.ts
 * `case 'theme' | 'theme-colors' | 'theme-fonts'`）：选预设后改写工作簿主题部件 xl/theme/theme1.xml。
 * - 没有主题部件时整组不可用（固定源 appThemeNeedsThemePart）；
 * - 主题没有可改写的 fontScheme 时，“字体”不可用，“主题”只换配色（固定源：避免毒化后续保存）。
 * 写入经引擎 setThemePart；预览由真实引擎重放，主题色引用的单元格样式与重开结果一致。
 */
import { createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { COLOR_SCHEMES, FONT_SCHEMES, THEME_PRESETS } from './workbook-vendor/core/themes'

export const THEME_PART = 'xl/theme/theme1.xml'
export type ThemeCommandKind = 'theme' | 'theme-colors' | 'theme-fonts'
export interface WorkbookThemeSource {
  /** 文件含可改写配色的主题部件 */
  readonly available: boolean
  /** 主题含可改写的 fontScheme（major/minor latin） */
  readonly fontsAvailable: boolean
  /** 当前 clrScheme / fontScheme 名称（来自实际字节） */
  readonly colorName?: string
  readonly fontName?: string
  readonly reason?: string
}
export interface ThemeOperation {
  kind: 'setThemePart'
  themePath: typeof THEME_PART
  state: { colors?: { name: string; values: string[] }; fonts?: { name: string; major: string; minor: string } }
}

const SLOTS = ['dk1', 'lt1', 'dk2', 'lt2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink']
const attribute = (xml: string, pattern: RegExp) => pattern.exec(xml)?.[1]?.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')

/** 与引擎 applyThemeState 的前置条件一致：12 个配色槽位齐全才可改写配色，major/minor latin 齐全才可改写字体。 */
export function themeSourceFromXml(xml: string | undefined): WorkbookThemeSource {
  if (xml === undefined) return { available: false, fontsAvailable: false, reason: '工作簿没有主题部件，无法应用主题' }
  const colors = SLOTS.every(slot => new RegExp(`<a:${slot}>[\\s\\S]*?</a:${slot}>`).test(xml))
  const fonts = /<a:majorFont>[\s\S]*?<a:latin[^>]*typeface="/.test(xml) && /<a:minorFont>[\s\S]*?<a:latin[^>]*typeface="/.test(xml)
  return {
    available: colors,
    fontsAvailable: colors && fonts,
    colorName: attribute(xml, /<a:clrScheme name="([^"]*)"/),
    fontName: attribute(xml, /<a:fontScheme name="([^"]*)"/),
    ...(colors ? {} : { reason: '主题缺少完整的配色方案，无法应用主题' }),
  }
}

/** 读取失败只让主题菜单不可用并说明原因，绝不阻断工作簿加载。 */
export async function readWorkbookThemeSource(bytes: Uint8Array): Promise<WorkbookThemeSource> {
  try {
    const source = await createBufferEntrySource(bytes)
    return themeSourceFromXml(await source.has(THEME_PART) ? await source.readText(THEME_PART) : undefined)
  } catch {
    return { available: false, fontsAvailable: false, reason: '无法读取工作簿主题部件，主题暂不可用' }
  }
}

/** 当前命令对应的写入操作；不可用或未知预设时抛出带原因的错误。 */
export function themeOperation(kind: ThemeCommandKind, id: string, source: WorkbookThemeSource): { operation: ThemeOperation; name: string } {
  if (!source.available) throw new Error(source.reason ?? '工作簿没有主题部件，无法应用主题')
  if (kind === 'theme-fonts' && !source.fontsAvailable) throw new Error('主题没有可改写的字体方案')
  const colors = kind === 'theme-fonts' ? undefined : (kind === 'theme' ? THEME_PRESETS.find(item => item.id === id)?.colors : COLOR_SCHEMES.find(item => item.id === id))
  const fonts = kind === 'theme-colors' || !source.fontsAvailable ? undefined
    : kind === 'theme' ? THEME_PRESETS.find(item => item.id === id)?.fonts : FONT_SCHEMES.find(item => item.id === id)
  if (colors === undefined && fonts === undefined) throw new Error('未知的主题预设')
  const state: ThemeOperation['state'] = {}
  if (colors) state.colors = { name: colors.name, values: [...colors.values] }
  if (fonts) state.fonts = { name: fonts.name, major: fonts.major, minor: fonts.minor }
  const name = kind === 'theme' ? THEME_PRESETS.find(item => item.id === id)!.name : (colors ?? fonts)!.name
  return { operation: { kind: 'setThemePart', themePath: THEME_PART, state }, name }
}

export const THEME_MENU_OPTIONS: Record<ThemeCommandKind, readonly { id: string; label: string }[]> = {
  'theme': THEME_PRESETS.map(item => ({ id: item.id, label: item.name })),
  'theme-colors': COLOR_SCHEMES.map(item => ({ id: item.id, label: item.name })),
  'theme-fonts': FONT_SCHEMES.map(item => ({ id: item.id, label: item.name })),
}
