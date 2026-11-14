/**
 * 固定源 Design ▸ Page Borders（ribbon-design-tab.tsx + PageBorderDialog.tsx）：
 * 页面边框是节属性，草稿写为 setSectionLayout.values 的 pageBorder / pageBorderProps，
 * 由固定引擎 applySectionSettings 写回；“整篇文档”= 每节一条（固定源 onPageBorderAll），“本节”= 当前节。
 * 取值表与固定源 PageBorderDialog 的 LINE_STYLES / LINE_WIDTHS / ART_NAMES 一致（桥接 page-border-presets.json，由测试守卫同步）。
 * 模型与换算（settingOf / modelOf / sideOf / pageBorderPropsOf）逐项移植固定源。
 */
import type { SectionSettings } from '@genoffice/docx-engine'

export const PAGE_BORDER_LINE_STYLES = ["single", "dotted", "dashSmallGap", "dashed", "dotDash", "dotDotDash", "double", "triple", "thinThickSmallGap", "thickThinSmallGap", "thinThickThinSmallGap", "thinThickMediumGap", "thickThinMediumGap", "thinThickThinMediumGap", "thinThickLargeGap", "thickThinLargeGap", "thinThickThinLargeGap", "wave", "doubleWave", "dashDotStroked", "threeDEmboss", "threeDEngrave", "outset", "inset"] as const
export const PAGE_BORDER_WIDTHS = [0.25, 0.5, 0.75, 1, 1.5, 2.25, 3, 4.5, 6] as const
export const PAGE_BORDER_ART_NAMES: readonly string[] = ["apples", "archedScallops", "babyPacifier", "babyRattle", "balloons3Colors", "balloonsHotAir", "basicBlackDashes", "basicBlackDots", "basicBlackSquares", "basicThinLines", "basicWhiteDashes", "basicWhiteDots", "basicWhiteSquares", "basicWideInline", "basicWideMidline", "basicWideOutline", "bats", "birds", "birdsFlight", "cabins", "cakeSlice", "candyCorn", "celticKnotwork", "certificateBanner", "chainLink", "champagneBottle", "checkedBarBlack", "checkedBarColor", "checkered", "christmasTree", "circlesLines", "circlesRectangles", "classicalWave", "clocks", "compass", "confetti", "confettiGrays", "confettiOutline", "confettiStreamers", "confettiWhite", "cornerTriangles", "couponCutoutDashes", "couponCutoutDots", "crazyMaze", "creaturesButterfly", "creaturesFish", "creaturesInsects", "creaturesLadyBug", "crossStitch", "cup", "decoArch", "decoArchColor", "decoBlocks", "diamondsGray", "doubleD", "doubleDiamonds", "earth1", "earth2", "eclipsingSquares1", "eclipsingSquares2", "eggsBlack", "fans", "film", "firecrackers", "flowersBlockPrint", "flowersDaisies", "flowersModern1", "flowersModern2", "flowersPansy", "flowersRedRose", "flowersRoses", "flowersTeacup", "flowersTiny", "gems", "gingerbreadMan", "gradient", "handmade1", "handmade2", "heartBalloon", "heartGray", "hearts", "heebieJeebies", "holly", "houseFunky", "hypnotic", "iceCreamCones", "lightBulb", "lightning1", "lightning2", "mapPins", "mapleLeaf", "mapleMuffins", "marquee", "marqueeToothed", "moons", "mosaic", "musicNotes", "northwest", "ovals", "packages", "palmsBlack", "palmsColor", "paperClips", "papyrus", "partyFavor", "partyGlass", "pencils", "people", "peopleHats", "peopleWaving", "poinsettias", "postageStamp", "pumpkin1", "pushPinNote1", "pushPinNote2", "pyramids", "pyramidsAbove", "quadrants", "rings", "safari", "sawtooth", "sawtoothGray", "scaredCat", "seattle", "shadowedSquares", "shapes1", "shapes2", "sharksTeeth", "shorebirdTracks", "skyrocket", "snowflakeFancy", "snowflakes", "sombrero", "southwest", "stars", "stars3d", "starsBlack", "starsShadowed", "starsTop", "sun", "swirligig", "tornPaper", "tornPaperBlack", "trees", "triangle1", "triangle2", "triangleCircle1", "triangleCircle2", "triangleParty", "triangles", "tribal1", "tribal2", "tribal3", "tribal4", "tribal5", "tribal6", "twistedLines1", "twistedLines2", "vine", "waveline", "weavingAngles", "weavingBraid", "weavingRibbon", "weavingStrips", "whiteFlowers", "woodwork", "xIllusions", "zanyTriangles", "zigZag", "zigZagStitch"]

export type DocxPageBorderProps = NonNullable<SectionSettings['pageBorderProps']>
type SideSpec = NonNullable<NonNullable<DocxPageBorderProps['sides']>['top']>
export type PageBorderSideName = 'top' | 'bottom' | 'left' | 'right'
export type PageBorderSetting = 'none' | 'box' | 'shadow' | '3d' | 'custom'
export type PageBorderScope = 'whole' | 'section'
export type PageBorderDisplay = 'all' | 'firstPage' | 'notFirstPage'
/** 写入草稿的节级取值：pageBorder:false 去掉；true + props:null 为“方框(单实线)”。 */
export type DocxPageBorderValue = { pageBorder: false } | { pageBorder: true; pageBorderProps: DocxPageBorderProps | null }
export const PAGE_BORDER_SIDES: readonly PageBorderSideName[] = ['top', 'bottom', 'left', 'right']

export interface PageBorderModel {
  setting: PageBorderSetting
  val: string
  art: string | null
  widthPt: number
  color: string | null
  on: Record<PageBorderSideName, boolean>
  space: Record<PageBorderSideName, number>
  offsetFrom: 'page' | 'text'
  zOrderBack: boolean
  scope: PageBorderScope
  display: PageBorderDisplay
}

/** 固定源 artLabel：驼峰名转显示名。 */
export const pageBorderArtLabel = (name: string): string => name.replace(/([a-z])([A-Z0-9])/g, '$1 $2').replace(/^./, c => c.toUpperCase())

const DEFAULT_SPACE = { top: 24, bottom: 24, left: 24, right: 24 }

function settingOf(sides: DocxPageBorderProps['sides']): PageBorderSetting {
  const list = PAGE_BORDER_SIDES.map(s => sides?.[s]).filter((s): s is SideSpec => !!s)
  if (list.length === 0) return 'none'
  const first = list[0]!
  const same = list.every(s => s.val === first.val && s.widthPt === first.widthPt && s.color === first.color && !!s.shadow === !!first.shadow && !!s.frame === !!first.frame)
  if (list.length < 4 || !same) return 'custom'
  if (first.shadow) return 'shadow'
  if (first.frame) return '3d'
  return 'box'
}

/** 固定源 modelOf：由当前节设置得到对话框初值。 */
export function pageBorderModelOf(section: Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'>): PageBorderModel {
  const p = section.pageBorder ? section.pageBorderProps ?? undefined : undefined
  const sides = p?.sides
  const first = PAGE_BORDER_SIDES.map(s => sides?.[s]).find((s): s is SideSpec => !!s)
  const on = { top: false, bottom: false, left: false, right: false }
  const space = { ...DEFAULT_SPACE }
  for (const s of PAGE_BORDER_SIDES) if (sides?.[s]) { on[s] = true; space[s] = sides[s]!.spacePt }
  const setting = section.pageBorder ? (p ? settingOf(sides) : 'box') : 'none'
  if (setting !== 'none' && setting !== 'custom') for (const s of PAGE_BORDER_SIDES) on[s] = true
  return {
    setting, val: first && !first.art ? first.val : 'single', art: first?.art ? first.val : null,
    widthPt: first?.widthPt ?? (first?.art ? 16 : 0.5), color: first?.color ?? null, on, space,
    // 解析侧缺省 w:offsetFrom 即 text（pageBorderStyleOf）
    offsetFrom: p ? (p.offsetFrom ?? 'text') : 'page', zOrderBack: p?.zOrder === 'back',
    scope: p?.display ? 'section' : 'whole', display: p?.display ?? 'all',
  }
}

function sideOf(m: PageBorderModel, side: PageBorderSideName): SideSpec {
  return { val: m.art ?? m.val, widthPt: m.widthPt, spacePt: m.space[side], ...(!m.art && m.color ? { color: m.color } : {}),
    ...(m.art ? { art: true as const } : {}), ...(!m.art && m.setting === 'shadow' ? { shadow: true as const } : {}), ...(!m.art && m.setting === '3d' ? { frame: true as const } : {}) }
}

/** 固定源 pageBorderPropsOf：对话框结果；null 表示无边框。 */
export function pageBorderPropsOf(m: PageBorderModel): DocxPageBorderProps | null {
  const active = PAGE_BORDER_SIDES.filter(s => m.setting !== 'none' && m.on[s])
  if (active.length === 0) return null
  const sides: NonNullable<DocxPageBorderProps['sides']> = {}
  for (const s of active) sides[s] = sideOf(m, s)
  return {
    ...(m.display !== 'all' ? { display: m.display } : {}), offsetFrom: m.offsetFrom, ...(m.zOrderBack ? { zOrder: 'back' as const } : {}),
    spacePt: Math.max(...active.map(s => m.space[s])), widthPt: m.widthPt, ...(!m.art && m.color ? { color: m.color } : {}), sides,
  }
}

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const keysOk = (value: object, allowed: string[]) => Object.keys(value).every(key => allowed.includes(key))

/** 与桥接 validatePageBorderValues 同一规则；草稿恢复与提交前校验。 */
export function validDocxPageBorderValues(values: Record<string, unknown>): boolean {
  if (!('pageBorder' in values) && !('pageBorderProps' in values)) return true
  if (typeof values.pageBorder !== 'boolean') return false
  if (!('pageBorderProps' in values) || values.pageBorderProps === null) return true
  const p = values.pageBorderProps
  if (!values.pageBorder || !isObject(p) || !keysOk(p, ['display', 'offsetFrom', 'zOrder', 'spacePt', 'widthPt', 'color', 'sides'])) return false
  if ((p.display !== undefined && !['firstPage', 'notFirstPage'].includes(p.display as string)) || !['page', 'text'].includes(p.offsetFrom as string)
    || (p.zOrder !== undefined && p.zOrder !== 'back') || (p.color !== undefined && (typeof p.color !== 'string' || !/^[0-9A-F]{6}$/.test(p.color)))) return false
  if (!isObject(p.sides) || !Object.keys(p.sides).length || !keysOk(p.sides, [...PAGE_BORDER_SIDES])) return false
  let maxSpace = 0, maxWidth = 0
  for (const side of Object.values(p.sides)) {
    if (!isObject(side) || !keysOk(side, ['val', 'widthPt', 'spacePt', 'color', 'art', 'shadow', 'frame'])) return false
    const art = side.art === true
    if ((side.art !== undefined && !art) || typeof side.val !== 'string' || !(art ? PAGE_BORDER_ART_NAMES : PAGE_BORDER_LINE_STYLES as readonly string[]).includes(side.val)) return false
    if (typeof side.widthPt !== 'number' || (art ? !Number.isInteger(side.widthPt) || side.widthPt < 1 || side.widthPt > 31 : !(PAGE_BORDER_WIDTHS as readonly number[]).includes(side.widthPt))) return false
    if (typeof side.spacePt !== 'number' || !Number.isInteger(side.spacePt) || side.spacePt < 0 || side.spacePt > 31) return false
    if (side.color !== undefined && (typeof side.color !== 'string' || !/^[0-9A-F]{6}$/.test(side.color) || art)) return false
    for (const flag of ['shadow', 'frame'] as const) if (side[flag] !== undefined && (side[flag] !== true || art)) return false
    if (side.shadow && side.frame) return false
    maxSpace = Math.max(maxSpace, side.spacePt); maxWidth = Math.max(maxWidth, side.widthPt)
  }
  return p.spacePt === maxSpace && p.widthPt === maxWidth
}

/** 节级取值是否与来源一致（一致即撤回该节的边框修改）。 */
export function samePageBorder(source: Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'>, value: DocxPageBorderValue): boolean {
  if (!source.pageBorder || !value.pageBorder) return !source.pageBorder && !value.pageBorder
  return JSON.stringify(source.pageBorderProps ?? null) === JSON.stringify(value.pageBorderProps ?? null)
}

/**
 * 应用页面边框后的完整非正文草稿：对目标节写入（或在与来源一致时移除）边框取值，保留该节其他页面设置。
 * build 由宿主传入（docx-operations restoredDocxSectionOperation），以便沿用节身份与其余取值校验。
 */
export function withDocxPageBorder<Op extends { kind: string; sectionId?: unknown; values?: unknown }>(
  layoutOperations: Op[], targets: { sectionId: string; settings: Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'> }[], value: DocxPageBorderValue,
  build: (sectionId: string, values: Record<string, unknown>) => Op | undefined,
): Op[] {
  if (value.pageBorder && value.pageBorderProps && !validDocxPageBorderValues({ pageBorder: true, pageBorderProps: value.pageBorderProps })) throw new Error('页面边框设置无效')
  const ids = new Set(targets.map(target => target.sectionId))
  const kept = layoutOperations.filter(operation => !(operation.kind === 'setSectionLayout' && ids.has(String(operation.sectionId))))
  const next: Op[] = []
  for (const target of targets) {
    const previous = layoutOperations.find(operation => operation.kind === 'setSectionLayout' && operation.sectionId === target.sectionId)
    const { pageBorder: _border, pageBorderProps: _props, ...rest } = { ...(previous?.values as Record<string, unknown> | undefined) }
    const values: Record<string, unknown> = samePageBorder(target.settings, value) ? rest
      : value.pageBorder ? { ...rest, pageBorder: true, pageBorderProps: value.pageBorderProps } : { ...rest, pageBorder: false }
    const operation = Object.keys(values).length ? build(target.sectionId, values) : undefined
    if (operation) next.push(operation)
  }
  return [...kept, ...next]
}

/** 当前生效的节边框：草稿取值优先，否则来源设置。 */
export function effectiveDocxPageBorder(source: Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'>, pending?: Record<string, unknown>): Pick<SectionSettings, 'pageBorder' | 'pageBorderProps'> {
  if (!pending || !('pageBorder' in pending)) return { pageBorder: source.pageBorder, ...(source.pageBorderProps ? { pageBorderProps: source.pageBorderProps } : {}) }
  const props = pending.pageBorderProps as DocxPageBorderProps | null | undefined
  return { pageBorder: pending.pageBorder === true, ...(pending.pageBorder === true && props ? { pageBorderProps: props } : {}) }
}
