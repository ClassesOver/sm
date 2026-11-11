import {inspectSlideNotes,prepareNotesEdits,applyNotesEdits,type NotesEdit} from './pptx-notes.ts'
import {inspectLinkCapabilities,prepareLinkEdits,applyLinkEdits,type LinkEdit} from './pptx-links.ts'
import {inspectClipboardCapabilities,prepareClipboardPastes,applyClipboardPastes,type ClipboardPaste} from './pptx-clipboard.ts'
import {inspectBrushSource} from './pptx-brush-source.ts'
import { inspectGroupCapabilities, validateGroupEdits, applyGroupEdits, type GroupEdit } from './pptx-groups.ts'
import { validateElementOrders, applyElementOrders, type ElementOrder } from './pptx-element-order.ts'
import { patchTransitionPreservingMetadata, transitionEditAvailability } from './pptx-transition.ts'
import {inspectClassicComments,validateClassicCommentEdits,applyClassicCommentEdits,type ClassicCommentEdit} from './pptx-comments.ts'
import { inspectPictureImages, validatePictureInsertions, validatePictureReplacements, applyPictureReplacements, type PictureInsertion, type PictureReplacement } from './pptx-images.ts'
import { inspectChartEdit, validateChartEdits, applyChartEdits, type NativeChartEdit } from './pptx-chart-edit.ts'
import { inspectPictureCrop, validatePictureCrops, applyPictureCrops, type PictureCrop } from './pptx-picture-crop.ts'
import { inspectBackgroundImage, validateBackgroundImages, applyBackgroundImages, type BackgroundImage } from './pptx-background-image.ts'
import { inspectPictureOpacity, validatePictureOpacities, applyPictureOpacities, type PictureOpacity } from './pptx-picture-opacity.ts'
import { findReplaceEditable } from './pptx-find-replace.ts'
import { XMLParser, XMLValidator } from 'fast-xml-parser'
import { patchSlideTransitionXml } from '../packages/pptx-engine/src/generate.ts'
import { readFile, writeFile } from 'node:fs/promises'
import shapePresets from './shape-presets.json' with { type: 'json' }
import { updateConnectorsForMoved, isConnectorXml, addChart, addElement, addPicture, addSection, addSmartArt, addTable, applyHeaderFooter, editTableCellText, editTableStyle, editTableStructure, ensureTableStylePart, TABLE_STYLE_PRESETS, getSections, readHeaderFooter, applyThemeToArchive, deleteElement, elementSpid, getSlideAnimations, getSlideHidden, getSlideTransition, deleteSlide, duplicateSlide, setElementFill, setShapePresetGeometry, strokePatchToModel, insertBlankSlide, insertSlideWithLayout, resetSlideLayout, listMasterParts, listSlideLayouts, moveSlide, openPptx, remapDeckColors, savePptx, setElementFont, setElementParagraphFormat, setSlideAnimations, setSlideBackground, setSlideHidden, setSlideLayout, setSlideSize, setSlideTransition, type TableElement, type SlideAnimation, type SlideTransitionKind, type ThemeSpec } from '@genoffice/pptx-engine'
import { applyEditParagraphs } from '../packages/pptx-ops/src/edit-text.ts'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'

type TextEdit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
} & { fontSizePt?: number; fontFamily?: string; color?: string; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean }
type Geometry = { x: number; y: number; width: number; height: number }
type TextBox = {
  slideIndex: number
  text: string
  geometry: Geometry
  fontSize?: number
  fontFamily?: string
  color?: string
  bold?: boolean
  rotation?: number
  /** 固定源 insertField：slidenum（幻灯片编号）或 datetime1（日期） */
  field?: 'slidenum' | 'datetime1'
  /** 固定源 insertWordArt：斜体、文字描边（EMU）与艺术字文本框（居中、不换行、随文字调整） */
  italic?: boolean
  outline?: { color: string; widthEmu: number }
  wordArt?: boolean
}
/** 固定源 Ribbon MOTION_PATHS（右直线、下直线、对角线、圆形、锯齿），坐标相对幻灯片宽高。 */
const MOTION_PATH_PRESETS: readonly string[] = [
  'M 0 0 L 0.25 0',
  'M 0 0 L 0 0.25',
  'M 0 0 L 0.25 0.25',
  'M 0 0 C 0.069 0 0.125 0.056 0.125 0.125 C 0.125 0.194 0.069 0.25 0 0.25 C -0.069 0.25 -0.125 0.194 -0.125 0.125 C -0.125 0.056 -0.069 0 0 0 Z',
  'M 0 0 L 0.12 -0.12 L 0.24 0.12 L 0.36 0',
]
type AnimationTiming = { trigger?: SlideAnimation['trigger']; durationMs?: number; delayMs?: number }
type AnimationSequenceItem =
  | ({ source: number; spid: number; effect: SlideAnimation['effect'] } & AnimationTiming)
  | { elementId: string; effect: SlideAnimation['effect']; trigger: SlideAnimation['trigger']; durationMs: number; delayMs: number; direction?: SlideAnimation['direction']; motionPath?: string; paragraph?: number }
const NEW_ANIMATION_EFFECTS = new Set(['appear', 'fade', 'flyIn', 'wipe', 'wipeDown', 'splitIn', 'bounce', 'flipIn', 'zoom', 'pulse', 'spin', 'grow', 'teeter', 'disappear', 'fadeOut', 'flyOut', 'wipeOut', 'shrink', 'zoomOut', 'motionPath'])
const validTiming = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 120000

type Input = {
  action: 'inspect' | 'edit'
  commentEdits?: ClassicCommentEdit[]
  /** 仅由 Python 宿主注入，外部 journal 不接受作者。 */
  commentAuthor?: '用户'
  input: string
  output?: string
  edits?: TextEdit[]
  order?: number[]
  /** 固定源 onAddSlide → addBlankSlide：每项新建一张空白页，沿用 layoutFrom 来源页的版式；新页索引为 来源页数 + k。 */
  newSlides?: ({ layoutFrom: number } | { duplicateOf: number } | { withLayout: string })[]
  /** 固定源 Insert ▸ Shapes（onPickShape）：预设形状，几何为 96dpi 像素；线条为 1pt 黑色连接符，其他为出厂填充色。 */
  shapes?: { slideIndex: number; kind: string; geometry: { x: number; y: number; width: number; height: number } }[]
  /** 固定源 Insert ▸ Table（insertTable + table-insert.ts）：行列数；位置按固定源规格由幻灯片尺寸计算。 */
  tables?: { slideIndex: number; rows: number; cols: number }[]
  /** 固定源 Shape Format ▸ Shape Fill / Shape Outline（setFill / setStroke）：纯色或无填充；描边颜色与线宽（pt）或无轮廓。 */
  shapeStyles?: { slideIndex: number; elementId: string; fill?: string; stroke?: { color: string; widthPt: number } | null }[]
  /** 固定源 Shape Format ▸ Change Shape（changeShape → setShapePresetGeometry）：仅形状（非线条、非文本框），保留位置、填充、轮廓与文字。 */
  shapeKinds?: { slideIndex: number; elementId: string; kind: string }[]
  /** 固定源 onAddSection（addSection）：在指定页（与 order 相同的编号）之前新增节；在重排与删页之后按最终位置执行。 */
  sections?: { slideIndex: number; name: string }[]
  /** 固定源 HeaderFooterDialog（applyHeaderFooter，应用于全部）：页脚文字、页码、日期（固定文字或自动更新）。 */
  headerFooter?: { footer: string | null; slideNum: boolean; date: string | null; dateAuto: boolean }
  /** 固定源表格上下文菜单（editTableStructure）：每来源页一次，按原始行列索引插入/删除。 */
  tableStructures?: { slideIndex: number; elementId: string; kind: 'insert-row' | 'delete-row' | 'insert-col' | 'delete-col'; index: number; before?: boolean }[]
  tableStyles?: { slideIndex: number; elementId: string; styleName?: string; firstRow?: boolean; lastRow?: boolean; firstCol?: boolean; lastCol?: boolean; bandRow?: boolean; bandCol?: boolean; rtl?: boolean; shadingColor?: string; borderPreset?: 'all' | 'none'; cellShadings?: { row: number; col: number; shadingColor: string }[] }[]
  /** 固定源表格单元格编辑（editTableCellText）：保留单元格首段与首个文字段的格式。 */
  tableCells?: { slideIndex: number; elementId: string; row: number; col: number; text: string }[]
  /** 固定源 Insert ▸ Chart（insertChart）：13 种图表类型与数据；位置为 2/3 宽、3:2、居中（graphicFrameInsertFrame）。 */
  charts?: { slideIndex: number; kind: string; categories: string[]; series: { name: string; values: number[] }[] }[]
  /** 固定源 Insert ▸ SmartArt（insertSmartArt）：7 种布局，1–8 个节点；位置同图表。 */
  smartArts?: { slideIndex: number; layout: string; items: string[] }[]
  /** 固定源 onResetLayout（resetSlideLayout）：占位符去掉显式位置，回到版式继承；最先执行，同批其他修改叠加其上。 */
  resetLayouts?: number[]
  /** 固定源缩略图删除（deleteSlide）：删除的来源页索引；同批不得再引用这些页。order 只列保留页。 */
  deletedSlides?: number[]
  theme?: 'executive' | 'clinical' | 'modern'
  slideSize?: { cx: number; cy: number }
  images?: {
    slideIndex: number
    bytesBase64: string
    extension: 'png' | 'jpg'
    geometry: { x: number; y: number; width: number; height: number }
    descr?: string
  }[]
  nativeImages?: PictureInsertion[]
  pictureReplacements?: PictureReplacement[]
  pictureCrops?: PictureCrop[]
  pictureOpacities?: PictureOpacity[]
  elementOrders?: ElementOrder[]
  notesEdits?: NotesEdit[]
  linkEdits?: LinkEdit[]
  clipboardPastes?: ClipboardPaste[]
  groupEdits?: GroupEdit[]
  chartEdits?: NativeChartEdit[]
  hiddenSlides?: { slideIndex: number; hidden: boolean }[]
  transitions?: { slideIndex: number; kind: SlideTransitionKind }[]
  animations?: {
    slideIndex: number
    elementId: string
    effect: SlideAnimation['effect']
    trigger: SlideAnimation['trigger']
    durationMs?: number
    delayMs?: number
    direction?: SlideAnimation['direction']
    append?: boolean
  }[]
  /**
   * 固定源 setAnimations：整页动画列表覆盖写（动画窗格移动/删除/计时、无、动作路径、按段）。
   * `source` 引用本页读取到的原有动画序号（原样保留，含无法建模的预设 XML）；其余为新增动画。
   */
  animationSequences?: { slideIndex: number; items: AnimationSequenceItem[] }[]
  slideLayouts?: { slideIndex: number; layoutPath: string }[]
  backgrounds?: { slideIndex: number; color: string }[]
  /** 固定源背景面板图片填充：一张图片应用到 slideIndices（来源页序号），拉伸或平铺。 */
  backgroundImages?: BackgroundImage[]
  textBoxes?: TextBox[]
  deletions?: { slideIndex: number; elementId: string }[]
  paragraphFormatting?: {
    slideIndex: number
    elementId: string
    bullet?: 'char' | 'number' | 'none'
    bulletChar?: string
    bulletFont?: string
    numType?: string
    startAt?: number
    bulletHangEmu?: number
    bulletSizePct?: number
    bulletColor?: string
    rtl?: boolean
    indentDelta?: 1 | -1
    align?: 'left' | 'center' | 'right' | 'justify'
    lineSpacingPct?: number
    spaceBeforePt?: number
    spaceAfterPt?: number
  }[]
}

const numberingTypes = ['arabicPeriod', 'arabicParenR', 'romanUcPeriod', 'alphaUcPeriod', 'alphaLcParenR', 'alphaLcPeriod', 'romanLcPeriod', 'circleNumDbPlain', 'ea1ChsPeriod']
const maxParagraphEmu = 51206400 // ECMA-376 ST_TextMargin/ST_TextIndent, 56 inches.
const colorPattern = /^#[0-9a-fA-F]{6}$/
const deletableTypes = new Set(['text', 'shape', 'picture'])
const validSlideIndex = (value: unknown, count: number): value is number =>
  Number.isInteger(value) && (value as number) >= 0 && (value as number) < count
const validGeometry = (value: Geometry | undefined) => !!value &&
  [value.x, value.y, value.width, value.height].every((item) => Number.isFinite(item) && item >= 0 && item <= 100000) &&
  value.width > 0 && value.height > 0

const themes: Record<NonNullable<Input['theme']>, ThemeSpec> = {
  executive: { name: 'Executive', colors: { dk1: '#183247', lt1: '#F4F6F8', dk2: '#566773', lt2: '#D5DEDF', accent1: '#147D75', accent2: '#307C8A', accent3: '#718B49', accent4: '#C45A3C', accent5: '#6C7180', accent6: '#8A6D3B', hlink: '#0563C1', folHlink: '#954F72' } },
  clinical: { name: 'Clinical', colors: { dk1: '#173B36', lt1: '#F5F8F7', dk2: '#5B706A', lt2: '#D9E5E1', accent1: '#287F70', accent2: '#4D8B78', accent3: '#6E9B88', accent4: '#B47A46', accent5: '#66818A', accent6: '#8E9B63', hlink: '#0563C1', folHlink: '#954F72' } },
  modern: { name: 'Modern', colors: { dk1: '#293846', lt1: '#F7F7F4', dk2: '#5F6B70', lt2: '#E1E3DF', accent1: '#C45A3C', accent2: '#3B8490', accent3: '#79864A', accent4: '#A66A87', accent5: '#4F6E87', accent6: '#AD8848', hlink: '#0563C1', folHlink: '#954F72' } },
}

const requestPath = process.argv[2]
if (!requestPath) throw new Error('input JSON path required')
const request = JSON.parse(await readFile(requestPath, 'utf8')) as Input
const opened = await openPptx(new Uint8Array(await readFile(request.input)))
const layouts = listSlideLayouts(opened.archive)

const textOf = (element: (typeof opened.deck.slides)[number]['elements'][number]) => {
  if (element.type !== 'text' && element.type !== 'shape') return ''
  return (element.text?.paragraphs ?? []).map((paragraph) =>
    paragraph.runs.map((run) => run.text).join(''),
  ).join('\n')
}

const transitionParser = new XMLParser({ preserveOrder: true, ignoreAttributes: false, processEntities: false })
function transitionApplyAllState(slide: (typeof opened.deck.slides)[number]) {
  const unsafe = { transitionApplyAllSafe: false, transitionApplyAllReason: 'pptx_transition_additional_settings' }
  try {
  const suffix = slide.bodySuffix
  if (/<(?:[\w.]+:)?AlternateContent\b/.test(suffix)) return unsafe
  if (/<(?!p:)[\w.]+:transition\b/.test(suffix)) return unsafe
  const blocks = suffix.match(/<p:transition\b[^>]*\/>|<p:transition\b[^>]*>[\s\S]*?<\/p:transition>/g) ?? []
  if (!blocks.length) return /<p:transition\b/.test(suffix) ? unsafe : { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  // AlternateContent or repeated containers need a separate preservation contract.
  if (blocks.length !== 1 || /<!--|<!\[CDATA\[|<\?/.test(blocks[0]!)) return unsafe
  const parsed = transitionParser.parse(blocks[0]!)?.[0]
  const attributes = parsed?.[':@'] ?? {}
  if (Object.keys(attributes).some(key => key !== '@_advTm') || (attributes['@_advTm'] !== undefined && (!/^\d+$/.test(String(attributes['@_advTm'])) || !Number.isSafeInteger(Number(attributes['@_advTm'])) || Number(attributes['@_advTm']) > 4294967295))) return unsafe
  const effect = parsed?.['p:transition'] ?? []
  const kind = getSlideTransition(slide)
  if (kind === 'none') return effect.length ? unsafe : { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  const canonical = patchSlideTransitionXml('</p:cSld>', kind).match(/<p:transition\b[^>]*>[\s\S]*?<\/p:transition>/)?.[0]
  const expected = canonical ? transitionParser.parse(canonical)?.[0]?.['p:transition'] : undefined
  if (effect.length !== 1 || !expected || expected.length !== 1) return unsafe
  const name = Object.keys(effect[0]).find(key => key !== ':@')
  const expectedName = Object.keys(expected[0]).find(key => key !== ':@')
  if (name !== expectedName || !name || effect[0][name]?.length) return unsafe
  const effectAttributes = effect[0][':@'] ?? {}
  // Only a generic kind or the pinned writer's default variant is modeled.
  if (Object.keys(effectAttributes).length && JSON.stringify(effectAttributes) !== JSON.stringify(expected[0][':@'] ?? {})) return unsafe
  return { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  } catch { return unsafe }
}

/** The fixed surgery reads canonical double-quoted EMU attributes. Refuse a
 * source whose merge/extension identities or geometry cannot be preserved. */
const structureSafe = (element: { type: string; anchor: { originalXml: string } }): boolean => {
  if (element.type !== 'table') return false
  const table = element as TableElement, xml = table.anchor.originalXml
  if (/\b(?:gridSpan|rowSpan|hMerge|vMerge)\s*=|<(?:\w+:)?extLst\b/.test(xml)) return false
  const positive = (n: number) => Number.isSafeInteger(n) && n > 0
  const rows = [...xml.matchAll(/<a:tr\b([^>]*)>/g)], columns = [...xml.matchAll(/<a:gridCol\b([^>]*)\/>/g)]
  if (!table.rows.length || table.rows.length > 75 || !table.colWidths.length || table.colWidths.length > 75 || table.rowHeights.length !== table.rows.length || rows.length !== table.rows.length || columns.length !== table.colWidths.length || table.rows.some(row => row.length !== table.colWidths.length)) return false
  if (rows.some((row,i) => Number(/\bh="(\d+)"/.exec(row[1]!)?.[1] ?? 0) !== table.rowHeights[i] || !positive(table.rowHeights[i]!)) || columns.some((col,i) => Number(/\bw="(\d+)"/.exec(col[1]!)?.[1] ?? 0) !== table.colWidths[i] || !positive(table.colWidths[i]!))) return false
  const frame = /<p:xfrm\b[^>]*>[\s\S]*?<a:ext\s([^>]*?)\/>/.exec(xml)?.[1]
  const width = Number(/\bcx="(\d+)"/.exec(frame ?? '')?.[1] ?? 0), height = Number(/\bcy="(\d+)"/.exec(frame ?? '')?.[1] ?? 0)
  return positive(width) && positive(height) && elementSpid(table) !== null && width === table.transform.offset.cx && height === table.transform.offset.cy && width === table.colWidths.reduce((sum,n) => sum+n,0) && height === table.rowHeights.reduce((sum,n) => sum+n,0)
}

const TABLE_FLAG_KEYS = ['firstRow','lastRow','firstCol','lastCol','bandRow','bandCol','rtl'] as const
const tableStyleParser = new XMLParser({ ignoreAttributes: false, processEntities: false })
const tableStylesType = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles'
const tableStylesContentType = 'application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml'
const list = <T>(value: T | T[] | undefined): T[] => value === undefined ? [] : Array.isArray(value) ? value : [value]
/** The fixed ensure helper uses string insertion / includes(styleId). Prove that
 * it will preserve an existing part and will not accept a colliding definition. */
function tableStylePartReason(): string | null {
  try {
    const typesXml = opened.archive.readText('[Content_Types].xml'), relsXml = opened.archive.readText('ppt/_rels/presentation.xml.rels')
    if (!typesXml || !relsXml || XMLValidator.validate(typesXml) !== true || XMLValidator.validate(relsXml) !== true || !typesXml.includes('</Types>') || !relsXml.includes('</Relationships>')) return '表格样式关系或内容类型无法确认'
    const types = tableStyleParser.parse(typesXml).Types, rels = tableStyleParser.parse(relsXml).Relationships
    if (!types || !rels || types['@_xmlns'] !== 'http://schemas.openxmlformats.org/package/2006/content-types' || rels['@_xmlns'] !== 'http://schemas.openxmlformats.org/package/2006/relationships') return '表格样式关系或内容类型无法确认'
    const relationships = list(rels.Relationship) as Record<string,unknown>[]
    const relationIds = relationships.map(entry => entry['@_Id'])
    if (relationIds.some(id => typeof id !== 'string' || !/^rId[1-9][0-9]*$/.test(id)) || new Set(relationIds).size !== relationIds.length || [...relsXml.matchAll(/<Relationship\b[^>]*\bId="rId[1-9][0-9]*"[^>]*\/>/g)].length !== relationships.length) return '表格样式来源关系标识无法确认'
    const entries = list(rels.Relationship).filter((entry: any) => entry['@_Type'] === tableStylesType)
    const overrides = list(types.Override).filter((entry: any) => entry['@_PartName'] === '/ppt/tableStyles.xml')
    if (entries.length > 1 || overrides.length > 1 || entries.some((entry: any) => entry['@_Target'] !== 'tableStyles.xml' || entry['@_TargetMode'] !== undefined) || overrides.some((entry: any) => entry['@_ContentType'] !== tableStylesContentType)) return '表格样式关系或内容类型无法确认'
    const xml = opened.archive.readText('ppt/tableStyles.xml')
    if (xml === undefined || xml === null) return entries.length || overrides.length ? '表格样式部件缺失或关系悬空' : null
    if (entries.length !== 1 || overrides.length !== 1 || XMLValidator.validate(xml) !== true || !/<a:tblStyleLst\b/.test(xml) || !(/<a:tblStyleLst[^>]*\/>/.test(xml) || xml.includes('</a:tblStyleLst>'))) return '此表格样式表的结构暂不支持安全修改'
    const root = tableStyleParser.parse(xml)['a:tblStyleLst']
    if (!root || root['@_xmlns:a'] !== 'http://schemas.openxmlformats.org/drawingml/2006/main' || Object.keys(root).some(key => !key.startsWith('@_') && key !== 'a:tblStyle' && key !== '#text')) return '此表格样式表的结构暂不支持安全修改'
    const definitions = [...xml.matchAll(/<a:tblStyle\b[^>]*\bstyleId="([^"<>]+)"[^>]*>[\s\S]*?<\/a:tblStyle>/g)]
    const ids = definitions.map(match => match[1]!)
    const parsedDefinitions = list(root['a:tblStyle']) as Record<string,unknown>[]
    if (parsedDefinitions.some((entry,index) => entry['@_styleId'] !== ids[index]) || definitions.length !== parsedDefinitions.length || new Set(ids).size !== ids.length) return '此表格样式表含无法确认或重复的定义'
    for (const preset of Object.values(TABLE_STYLE_PRESETS)) {
      if (!preset.styleId) continue
      const found = definitions.find(match => match[1] === preset.styleId)
      if ((found && found[0] !== preset.styleDefXml) || (!found && xml.includes(preset.styleId))) return '此文档的固定表格样式标识与来源定义冲突'
    }
    return null
  } catch { return '此表格样式表无法完整读取' }
}
const sourceStylePartReason = tableStylePartReason()
function tableStyleState(table: TableElement) {
  const xml = table.anchor.originalXml
  const matches = [...xml.matchAll(/<a:tblPr\b[^>]*?(?:\/>|>[\s\S]*?<\/a:tblPr>)/g)]
  const fragment = matches[0]?.[0] ?? '', opening = /^<a:tblPr\b([^>]*?)\/?>/.exec(fragment)
  const attributes = opening?.[1] ?? ''
  const pairs = [...attributes.matchAll(/\s+([A-Za-z_:][\w:.-]*)="([^"<>]*)"/g)]
  const flags = Object.fromEntries(TABLE_FLAG_KEYS.map(key => [key,pairs.some(pair => pair[1] === key && ['1','true'].includes(pair[2]!))])) as Record<(typeof TABLE_FLAG_KEYS)[number],boolean>
  const styleId = /<a:tableStyleId>([^<]*)<\/a:tableStyleId>/.exec(fragment)?.[1]
  const name = Object.entries(TABLE_STYLE_PRESETS).find(([,preset]) => preset.styleId !== undefined && preset.styleId === styleId)?.[0] ?? null
  const children = fragment.replace(/^<a:tblPr\b[^>]*>/,'').replace(/<\/a:tblPr>$/,'').trim()
  let reason = sourceStylePartReason
  const complexCellExtension = [...xml.matchAll(/<a:tcPr\b[^>]*>([\s\S]*?)<\/a:tcPr>/g)].some(cell => [...cell[1]!.matchAll(/<a:extLst\b[^>]*>([\s\S]*?)<\/a:extLst>/g)].some(extension => extension[1]!.trim() !== ''))
  if (complexCellExtension) reason = '此表格单元格含扩展内容，暂不能安全应用预设或选项'
  if (matches.length > 1 || (!fragment && !xml.includes('<a:tbl>')) || (fragment && (!opening || XMLValidator.validate(fragment) !== true || attributes.replace(/\s+[A-Za-z_:][\w:.-]*="[^"<>]*"/g,'').trim() || new Set(pairs.map(pair=>pair[1])).size !== pairs.length || pairs.some(pair => !(TABLE_FLAG_KEYS as readonly string[]).includes(pair[1]!) || !['0','1','true','false'].includes(pair[2]!)) || (!fragment.endsWith('/>') && children !== '' && !/^<a:tableStyleId>[^<]*<\/a:tableStyleId>$/.test(children))))) reason = '此表格含扩展、复杂或非规范属性，暂不能应用预设或选项'
  return { tableStyleFlags: flags, tableStyleName: reason === null ? name : null, tablePresetEditable: reason === null, tablePresetReason: reason }
}

/** The fixed cell helper addresses physical a:tc positions. Only expose a
 * source where those slots map one-to-one to the unmerged model grid. */
function cellShadingSource(table: TableElement, slidePath: string): string[][] | null {
  const xml = table.anchor.originalXml, slideXml = opened.archive.readText(slidePath) ?? ''
  const ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
  const slideRoot = tableStyleParser.parse(slideXml)['p:sld']
  if (slideRoot?.['@_xmlns:a'] !== ns || [...slideXml.matchAll(/xmlns:a=["']([^"']*)["']/g)].some(match => match[1] !== ns)
    || XMLValidator.validate(xml) !== true || /<!DOCTYPE|<!ENTITY|<!--|<\?|\b(?:gridSpan|rowSpan|hMerge|vMerge)\s*=|<(?:\w+:)?extLst\b/.test(xml)) return null
  const tables = [...xml.matchAll(/<a:tbl(?:\s[^>]*)?>[\s\S]*?<\/a:tbl>/g)]
  if (tables.length !== 1 || (xml.match(/<a:tbl[\s>]/g) ?? []).length !== 1) return null
  const body = tables[0]![0], rows = [...body.matchAll(/<a:tr(?:\s[^>]*)?>[\s\S]*?<\/a:tr>/g)]
  if (!table.rows.length || table.rows.length > 75 || !table.colWidths.length || table.colWidths.length > 75 || rows.length !== table.rows.length || table.rows.some(row => row.length !== table.colWidths.length || row.some(cell => cell.merged || cell.gridSpan && cell.gridSpan !== 1 || cell.rowSpan && cell.rowSpan !== 1))) return null
  const result: string[][] = []
  const allowedProperties = new Set(['a:lnL','a:lnR','a:lnT','a:lnB','a:lnTlToBr','a:lnBlToTr','a:solidFill','a:gradFill','a:pattFill','a:blipFill','a:noFill','a:grpFill'])
  for (const row of rows) {
    const rowBody = row[0].replace(/^<a:tr[^>]*>/,'').replace(/<\/a:tr>$/,'')
    const cells = [...rowBody.matchAll(/<a:tc(?:\s[^>]*)?>[\s\S]*?<\/a:tc>/g)].map(match => match[0])
    if (cells.length !== table.colWidths.length || rowBody.replace(/<a:tc(?:\s[^>]*)?>[\s\S]*?<\/a:tc>/g,'').trim()) return null
    for (const cell of cells) {
      if ((cell.match(/<a:txBody[\s>]/g) ?? []).length !== 1 || (cell.match(/<a:tcPr[\s/>]/g) ?? []).length > 1) return null
      const properties = /<a:tcPr[^>]*\/>|<a:tcPr[^>]*>[\s\S]*?<\/a:tcPr>/.exec(cell)?.[0]
      if (properties) {
        const parsed = tableStyleParser.parse(properties)['a:tcPr']
        if (parsed && (typeof parsed !== 'object' || Object.entries(parsed).some(([key,value]) => !key.startsWith('@_') && (!allowedProperties.has(key) || Array.isArray(value))))) return null
      }
    }
    result.push(cells)
  }
  return result
}
function cellShadingState(table: TableElement, slidePath: string) {
  const editable = cellShadingSource(table,slidePath) !== null
  return { tableCellShadingEditable: editable, tableCellShadingReason: editable ? null : '此表格含合并、扩展或无法确认的单元格映射，暂不能修改单格底纹' }
}
const withoutCellProperties = (xml: string) => xml.replace(/<a:tcPr[^>]*\/>|<a:tcPr[^>]*>[\s\S]*?<\/a:tcPr>/g,'')

if (request.action === 'inspect') {
  const comments=inspectClassicComments(opened)
  const pictureImages=inspectPictureImages(opened)
  process.stdout.write(JSON.stringify({
    size: opened.deck.size,
    masterParts: listMasterParts(opened.archive),
    layouts,
    // 现有分节（p14:sectionLst）：节名与所含页（来源页序号）
    sections: getSections(opened).map(section => ({ name: section.name, slideIndices: section.slideIndices })),
    slides: opened.deck.slides.map((slide, slideIndex) => ({
      hidden: getSlideHidden(slide),
      headerFooter: readHeaderFooter(slide),
      slideIndex,
      comments:comments[slideIndex],
      ...inspectSlideNotes(opened,slideIndex),
      background: slide.background?.type === 'solid' ? slide.background.color : null,
      ...inspectBackgroundImage(opened, slideIndex),
      ...opened.archive.resolveSlideChain(slide.path),
      transition: getSlideTransition(slide),
      ...transitionApplyAllState(slide),
      ...transitionEditAvailability(slide.bodySuffix),
      animations: getSlideAnimations(slide).map(({ spid, effect, trigger, durationMs, delayMs, direction, presetXml, preset, motionPath, paragraph }) => ({
        spid,
        elementId: slide.elements.find((element) => elementSpid(element) === spid)?.id ?? '',
        effect,
        trigger,
        durationMs,
        delayMs,
        ...(direction ? { direction } : {}),
        ...(motionPath ? { motionPath } : {}),
        ...(paragraph !== undefined ? { paragraph } : {}),
        ...(presetXml ? { presetXml } : {}),
        ...(preset ? { preset } : {}),
      })),
      elements: slide.elements.map((element) => ({
        id: element.id,
        type: element.type,
        name: element.name ?? '',
        text: textOf(element),
        ...(element.type === 'table' ? { tableStructureEditable: structureSafe(element), ...tableStyleState(element), ...cellShadingState(element,slide.path) } : {}),
        ...(element.type === 'picture' ? (() => { const image=pictureImages.find(item=>item.slideIndex===slideIndex&&item.elementId===element.id); return image ? {pictureReplaceable:image.replaceable,pictureReplaceReason:image.readOnlyReason,pictureSha256:image.sha256,pictureSize:image.size} : {} })() : {}),
        ...(element.type === 'picture' ? inspectPictureCrop(opened,slideIndex,element.id) : {}),
        ...(element.type === 'picture' ? inspectPictureOpacity(opened, slideIndex, element.id) : {}),
        ...inspectGroupCapabilities(opened, slideIndex, element.id),
        ...inspectLinkCapabilities(opened,slideIndex,element.id),
        ...inspectClipboardCapabilities(opened,slideIndex,element.id),
        brushSource:inspectBrushSource(element),
        orderEditable: ['text','shape','picture'].includes(element.type) && !isConnectorXml(element.anchor.originalXml),
        arrangeEditable: ['text','shape','picture'].includes(element.type) && !isConnectorXml(element.anchor.originalXml),
        ...(element.type === 'chart' ? inspectChartEdit(opened,slideIndex,element.id) : {}),
        ...((element.type === 'text'||element.type === 'shape') ? {findReplaceEditable:findReplaceEditable(element)} : {}),
        // 表格单元格文字（合并单元格为 null），供编辑器单元格网格使用
        ...(element.type === 'table' ? { tableCells: (element as unknown as { rows: { merged?: boolean; text?: { paragraphs: { runs: { text: string }[] }[] } }[][] }).rows.map(row => row.map(cell => cell.merged ? null : (cell.text?.paragraphs ?? []).map(paragraph => paragraph.runs.map(run => run.text).join('')).join('\n'))) } : {}),
        ...(element.type === 'text' || element.type === 'shape' ? (() => {
          const paragraphs = element.text?.paragraphs ?? []
          const run = paragraphs[0]?.runs[0]
          return {
            paragraphLists: paragraphs.map((paragraph) => ({
              bulletKind: paragraph.bullet?.type ?? null,
              bulletChar: paragraph.bullet?.char ?? null,
              bulletFont: paragraph.bullet?.font ?? null,
              numType: paragraph.bullet?.numType ?? null,
              startAt: paragraph.bullet?.startAt ?? null,
              bulletSizePct: paragraph.bullet?.sizePct ?? null,
              bulletSizePt: paragraph.bullet?.sizePt ?? null,
              bulletColor: paragraph.bullet?.color ?? null,
              level: paragraph.level ?? null,
              rtl: paragraph.rtl ?? null,
              marLEmu: paragraph.marL ?? null,
              indentEmu: paragraph.indent ?? null,
              hasExplicitHangingIndent: Boolean(paragraph.pPrExplicit?.marL && paragraph.indent != null && paragraph.indent < 0),
            })),
            paragraphAlignments: paragraphs.map((paragraph) => paragraph.align ?? null),
            paragraphFormatting: paragraphs.map((paragraph) => ({
              align: paragraph.align ?? null,
              lineSpacingPct: paragraph.lineHeight ?? null,
              lineSpacingPt: paragraph.lineExact ?? null,
              spaceBeforePt: paragraph.spaceBefore ?? null,
              spaceAfterPt: paragraph.spaceAfter ?? null,
              spaceBeforePct: paragraph.spaceBeforePct ?? null,
              spaceAfterPct: paragraph.spaceAfterPct ?? null,
            })),
            ...(run ? { textStyle: {
            fontSizePt: run.fontSize ?? null,
            fontFamily: run.fontFamily ?? null,
            color: run.color ?? null,
            bold: run.bold ?? null,
            italic: run.italic ?? null,
            underline: run.underline ?? null,
            strike: run.strike ?? null,
            } } : {}),
          }
        })() : {}),
        editable: element.type === 'text' || element.type === 'shape',
        deletable: deletableTypes.has(element.type),
        geometry: {
          x: element.transform.offset.x / 9525,
          y: element.transform.offset.y / 9525,
          width: element.transform.offset.cx / 9525,
          height: element.transform.offset.cy / 9525,
        },
      })),
    })),
  }))
} else {
  if (request.theme && !Object.hasOwn(themes, request.theme)) throw new Error('theme_invalid')
  // 页面引用在重排前固定；背景和新增文本框在主题之后写入，避免显式颜色被主题重映射。
  const originalSlides = [...opened.deck.slides]
  const slideCount = originalSlides.length
  const commentSourcePaths=originalSlides.map(slide=>slide.path)
  const notesEdits=prepareNotesEdits(opened,request.notesEdits,{deletedSlides:request.deletedSlides,newSlides:request.newSlides})
  const linkEdits=prepareLinkEdits(opened,request.linkEdits,{deletedSlides:request.deletedSlides,deletions:request.deletions,groupEdits:request.groupEdits,newSlides:request.newSlides})
  const clipboardPastes=prepareClipboardPastes(opened,request.clipboardPastes,{deletedSlides:request.deletedSlides,deletions:request.deletions,groupEdits:request.groupEdits,newSlides:request.newSlides,resetLayouts:request.resetLayouts,slideLayouts:request.slideLayouts,slideSize:request.slideSize,theme:request.theme,headerFooter:request.headerFooter})
  const groupEdits=validateGroupEdits(opened,request.groupEdits,{deletedSlides:request.deletedSlides})
  const groupedPages=new Set(groupEdits.map(item=>item.slideIndex))
  const groupPaths=groupEdits.map(item=>originalSlides[item.slideIndex]!.path)
  if(groupEdits.length){
    if(groupPaths.some(path=>originalSlides.filter(slide=>slide.path===path).length!==1))throw Error('group_edit_source_ambiguous')
    if(request.theme!==undefined||request.slideSize!==undefined||request.headerFooter!==undefined)throw Error('group_edit_conflict')
    for(const [key,records] of Object.entries<unknown>(request)){
      if(key==='groupEdits'||key==='order'||!Array.isArray(records))continue
      if((key==='deletedSlides'||key==='resetLayouts')&&records.some(index=>groupedPages.has(index)))throw Error('group_edit_conflict')
      if(key==='newSlides'&&records.some(item=>item&&typeof item==='object'&&(groupedPages.has(item.duplicateOf)||groupedPages.has(item.layoutFrom))))throw Error('group_edit_conflict')
      if(records.some(item=>item&&typeof item==='object'&&groupedPages.has(item.slideIndex)))throw Error('group_edit_conflict')
    }
  }
  // 层级按完整来源顺序先写入，随后复制/重置仍沿用正确的 spTree 顺序。
  const elementOrders=validateElementOrders(opened,request.elementOrders,{deletedSlides:request.deletedSlides})
  applyElementOrders(opened,elementOrders)
  const commentEdits=validateClassicCommentEdits(opened,request.commentEdits,request.commentAuthor,request.deletedSlides)
  // 修改来源图表后再复制页面，避免副本共享部件使同批来源编辑被误拒绝。
  const chartEdits=validateChartEdits(opened,request.chartEdits,{deletedSlides:request.deletedSlides, deletions:request.deletions})
  applyChartEdits(opened,chartEdits)
  // 新建页最先创建（副本因此复制已保存内容），逐个追加到末尾：来源页索引与新页编号（来源页数 + k）均不变；
  // 之后所有按索引的步骤只接受来源页，order（长度 = 来源页数 + 新页数）决定最终位置。
  const newSlideSource = (item: unknown) => item && typeof item === 'object' ? ('duplicateOf' in item ? (item as { duplicateOf: unknown }).duplicateOf : (item as { layoutFrom?: unknown }).layoutFrom) : undefined
  const newSlides = request.newSlides ?? []
  if (!Array.isArray(newSlides) || newSlides.length > 50) throw new Error('new_slides_invalid')
  for (const item of newSlides) {
    const keys = item && typeof item === 'object' ? Object.keys(item) : []
    if (keys.length === 1 && keys[0] === 'withLayout') {
      // 固定源 onAddSlideWithLayout：按所选版式生成占位符；插在末尾，来源页索引不变。
      const layoutPath = (item as { withLayout: unknown }).withLayout
      if (typeof layoutPath !== 'string' || !layouts.some(layout => layout.path === layoutPath)) throw new Error('new_slide_layout_invalid')
      if (!insertSlideWithLayout(opened, opened.deck.slides.length - 1, layoutPath)) throw new Error('new_slide_insert_failed')
      continue
    }
    const source = newSlideSource(item)
    if (keys.length !== 1 || !['layoutFrom', 'duplicateOf'].includes(keys[0]!) || !validSlideIndex(source, slideCount)) throw new Error('new_slide_source_invalid')
    const created = keys[0] === 'duplicateOf' ? duplicateSlide(opened, source) : insertBlankSlide(opened, source)
    if (!created) throw new Error('new_slide_insert_failed')
    const last = opened.deck.slides.length - 1
    if (source + 1 !== last) moveSlide(opened, source + 1, last)
  }
  const resetLayouts = request.resetLayouts ?? []
  if (!Array.isArray(resetLayouts) || new Set(resetLayouts).size !== resetLayouts.length || resetLayouts.some(index => !validSlideIndex(index, slideCount))) throw new Error('reset_layouts_invalid')
  for (const index of resetLayouts) {
    const sourceIds = new Map(originalSlides[index]!.elements.map(element => [elementSpid(element), element.id]))
    const reset = resetSlideLayout(opened, index)
    if (!reset) throw new Error('reset_layout_failed')
    // 固定引擎重建整页时生成新模型 ID；同批操作仍绑定来源 OOXML 对象身份。
    for (const element of reset.elements) {
      const spid = elementSpid(element)
      const sourceId = spid === null ? undefined : sourceIds.get(spid)
      if (sourceId) element.id = sourceId
    }
    originalSlides[index] = reset
  }
  const chartKinds = ['bar', 'bar3D', 'barStacked', 'barPercentStacked', 'barH', 'line', 'area', 'pie', 'pie3D', 'doughnut', 'scatter', 'radar', 'comboBarLine']
  const charts = request.charts ?? []
  if (!Array.isArray(charts) || charts.length > 50) throw new Error('charts_invalid')
  const label = (value: unknown) => typeof value === 'string' && [...value].length <= 100 && !/[\u0000-\u001f\u007f]/.test(value)
  for (const chart of charts) {
    if (!chart || typeof chart !== 'object' || Object.keys(chart).sort().join() !== 'categories,kind,series,slideIndex' || !validSlideIndex(chart.slideIndex, slideCount) || !chartKinds.includes(chart.kind)
      || !Array.isArray(chart.categories) || chart.categories.length < 1 || chart.categories.length > 100 || !chart.categories.every(label)
      || !Array.isArray(chart.series) || chart.series.length < 1 || chart.series.length > 20
      || chart.series.some(series => !series || Object.keys(series).sort().join() !== 'name,values' || !label(series.name) || !Array.isArray(series.values) || series.values.length !== chart.categories.length || !series.values.every(value => typeof value === 'number' && Number.isFinite(value)))
      || (chart.kind === 'comboBarLine' && chart.series.length < 2) || (chart.kind === 'scatter' && !chart.categories.every(value => Number.isFinite(Number(value))))) throw new Error('chart_invalid')
  }
  const smartArts = request.smartArts ?? []
  if (!Array.isArray(smartArts) || smartArts.length > 50) throw new Error('smartarts_invalid')
  for (const item of smartArts) {
    if (!item || typeof item !== 'object' || Object.keys(item).sort().join() !== 'items,layout,slideIndex' || !validSlideIndex(item.slideIndex, slideCount)
      || !['list', 'process', 'cycle', 'hierarchy', 'pyramid', 'matrix', 'venn'].includes(item.layout)
      || !Array.isArray(item.items) || item.items.length < 1 || item.items.length > 8 || !item.items.every(text => typeof text === 'string' && [...text].length <= 200 && !/[\u0000-\u001f\u007f]/.test(text))) throw new Error('smartart_invalid')
  }
  // 表格先校验；插入放在最后（addTable 会把已做的修改写入 XML 后重建页面并改变对象身份）。
  const tables = request.tables ?? []
  if (!Array.isArray(tables) || tables.length > 100) throw new Error('tables_invalid')
  for (const table of tables) {
    if (!table || typeof table !== 'object' || Object.keys(table).some(key => !['slideIndex', 'rows', 'cols'].includes(key)) || !validSlideIndex(table.slideIndex, slideCount)
      || !Number.isInteger(table.rows) || !Number.isInteger(table.cols) || table.rows < 1 || table.cols < 1 || table.rows > 75 || table.cols > 75) throw new Error('table_invalid')
  }
  if (request.paragraphFormatting !== undefined && (!Array.isArray(request.paragraphFormatting) || request.paragraphFormatting.length > 500)) {
    throw new Error('paragraph_format_invalid')
  }
  const paragraphFields = ['align', 'lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt', 'bullet', 'bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu', 'bulletSizePct', 'bulletColor', 'rtl', 'indentDelta']
  for (const format of request.paragraphFormatting ?? []) {
    if (!format || typeof format !== 'object' || Array.isArray(format) ||
      Object.keys(format).some(key => !['slideIndex', 'elementId', ...paragraphFields].includes(key)) ||
      !paragraphFields.some(key => Object.hasOwn(format, key)) ||
      !validSlideIndex(format.slideIndex, slideCount) || typeof format.elementId !== 'string' || !format.elementId ||
      (Object.hasOwn(format, 'align') && !['left', 'center', 'right', 'justify'].includes(format.align!)) ||
      (Object.hasOwn(format, 'lineSpacingPct') && ![100, 115, 150, 200, 250, 300].includes(format.lineSpacingPct!)) ||
      (['spaceBeforePt', 'spaceAfterPt'] as const).some(key => Object.hasOwn(format, key) &&
        (typeof format[key] !== 'number' || !Number.isFinite(format[key]) || format[key]! < 0 || format[key]! > 500)) ||
      (Object.hasOwn(format, 'bullet') && !['char', 'number', 'none'].includes(format.bullet!)) ||
      (Object.hasOwn(format, 'bulletChar') && (typeof format.bulletChar !== 'string' || [...format.bulletChar].length !== 1 || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\ufffe\uffff]/u.test(format.bulletChar))) ||
      (Object.hasOwn(format, 'bulletFont') && (typeof format.bulletFont !== 'string' || !format.bulletFont.trim() || [...format.bulletFont].length > 200 || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\ufffe\uffff]/u.test(format.bulletFont))) ||
      (Object.hasOwn(format, 'numType') && !numberingTypes.includes(format.numType!)) ||
      (Object.hasOwn(format, 'startAt') && (!Number.isInteger(format.startAt) || format.startAt! < 1 || format.startAt! > 32767)) ||
      (Object.hasOwn(format, 'bulletHangEmu') && (!Number.isInteger(format.bulletHangEmu) || format.bulletHangEmu! < 0 || format.bulletHangEmu! > maxParagraphEmu)) ||
      (Object.hasOwn(format, 'bulletSizePct') && ![75, 90, 100, 125, 150].includes(format.bulletSizePct!)) ||
      (Object.hasOwn(format, 'bulletColor') && (typeof format.bulletColor !== 'string' || !colorPattern.test(format.bulletColor))) ||
      (Object.hasOwn(format, 'rtl') && typeof format.rtl !== 'boolean') ||
      (Object.hasOwn(format, 'indentDelta') && ![-1, 1].includes(format.indentDelta!)) ||
      (format.bullet === 'none' && ['bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu', 'bulletSizePct', 'bulletColor'].some(key => Object.hasOwn(format, key))) ||
      (format.bullet === 'char' && ['numType', 'startAt'].some(key => Object.hasOwn(format, key))) ||
      (['bulletChar', 'bulletFont'].some(key => Object.hasOwn(format, key)) && format.bullet !== 'char')) {
      throw new Error('paragraph_format_invalid')
    }
  }
  const deletedSlides = request.deletedSlides ?? []
  if (!Array.isArray(deletedSlides) || new Set(deletedSlides).size !== deletedSlides.length || deletedSlides.some(index => !validSlideIndex(index, slideCount))) throw new Error('deleted_slides_invalid')
  if (deletedSlides.length && !request.order) throw new Error('deleted_slides_require_order')
  const hiddenSlides = request.hiddenSlides ?? []
  const hiddenTargets = new Set<number>()
  if (!Array.isArray(hiddenSlides) || hiddenSlides.length > 500) throw new Error('hidden_slides_invalid')
  for (const item of hiddenSlides) {
    if (!item || Object.keys(item).sort().join() !== 'hidden,slideIndex' || !validSlideIndex(item.slideIndex, slideCount) || typeof item.hidden !== 'boolean' || hiddenTargets.has(item.slideIndex)) throw new Error('hidden_slides_invalid')
    hiddenTargets.add(item.slideIndex)
  }
  const removedSlides = new Set(deletedSlides)
  const slideRecords: ({ slideIndex: number }[] | undefined)[] = [request.linkEdits, request.clipboardPastes, request.groupEdits, request.elementOrders, request.edits, request.images, request.nativeImages, request.pictureReplacements, request.pictureCrops, request.pictureOpacities, request.chartEdits, request.hiddenSlides, request.transitions, request.animations, request.animationSequences, request.slideLayouts, request.backgrounds, request.textBoxes, request.deletions, request.paragraphFormatting, request.shapes, request.tables, request.shapeStyles, request.shapeKinds, request.tableCells, request.tableStyles, request.tableStructures, request.charts, request.smartArts, (request.resetLayouts ?? []).map(slideIndex => ({ slideIndex }))]
  if (slideRecords.some(records => (records ?? []).some(record => removedSlides.has(record.slideIndex))) || (request.newSlides ?? []).some(item => removedSlides.has(newSlideSource(item) as number))) throw new Error('deleted_slide_has_pending_edits')
  const deletions = request.deletions ?? []
  const deleted = new Set<string>()
  for (const deletion of deletions) {
    if (!validSlideIndex(deletion.slideIndex, slideCount)) throw new Error('delete_slide_index_invalid')
    const element = originalSlides[deletion.slideIndex]!.elements.find((candidate) => candidate.id === deletion.elementId)
    if (!element || !deletableTypes.has(element.type)) throw new Error('delete_target_invalid')
    const key = `${deletion.slideIndex}:${deletion.elementId}`
    if (deleted.has(key)) throw new Error('delete_target_duplicated')
    deleted.add(key)
  }
  const touchesDeleted = (slideIndex: number, elementId: string) => deleted.has(`${slideIndex}:${elementId}`)
  const pictureReplacements=request.pictureReplacements??[]
  const pictureCrops=validatePictureCrops(opened,request.pictureCrops,{deletedSlides,deletions,pictureReplacements})
  const pictureOpacities = validatePictureOpacities(opened, request.pictureOpacities, { deletedSlides, deletions, pictureReplacements })
  validatePictureInsertions(opened,request.nativeImages??[])
  validatePictureReplacements(opened,pictureReplacements)
  for(const item of [...pictureReplacements,...chartEdits]) if(touchesDeleted(item.slideIndex,item.elementId)) throw new Error('media_edit_target_deleted')
  const pictureKeys=new Set(pictureReplacements.map(item=>`${item.slideIndex}:${item.elementId}`))
  if(chartEdits.some(item=>pictureKeys.has(`${item.slideIndex}:${item.elementId}`))) throw new Error('media_edit_target_conflict')
  const tableStructures=request.tableStructures ?? [], structuralSlides=new Set<number>()
  if (!Array.isArray(tableStructures) || tableStructures.length>100) throw new Error('table_structures_invalid')
  for (const item of tableStructures) {
    if (!item || Object.keys(item).some(key=>!['slideIndex','elementId','kind','index','before'].includes(key)) || !validSlideIndex(item.slideIndex,slideCount) || typeof item.elementId!=='string' || !['insert-row','delete-row','insert-col','delete-col'].includes(item.kind) || !Number.isInteger(item.index) || item.index<0 || (item.kind.startsWith('insert-') ? typeof item.before!=='boolean' : Object.hasOwn(item,'before')) || structuralSlides.has(item.slideIndex)) throw new Error('table_structure_invalid')
    const table=originalSlides[item.slideIndex]!.elements.find(el=>el.id===item.elementId)
    if (!table || table.type!=='table' || !structureSafe(table) || table.rows.length<1 || table.rows.length>75 || table.colWidths.length<1 || table.colWidths.length>75 || table.rows.some(row=>row.length!==table.colWidths.length)) throw new Error('table_structure_target_invalid')
    const count=item.kind.endsWith('row') ? table.rows.length : table.colWidths.length
    if (item.index>=count || (item.kind.startsWith('delete-') && count<=1) || (item.kind.startsWith('insert-') && count>=75) || touchesDeleted(item.slideIndex,item.elementId)) throw new Error('table_structure_index_invalid')
    if (request.slideSize || (request.resetLayouts ?? []).includes(item.slideIndex) || (request.slideLayouts ?? []).some(v=>v.slideIndex===item.slideIndex) || [...(request.tableCells ?? []),...(request.tableStyles ?? [])].some(v=>v.slideIndex===item.slideIndex && v.elementId===item.elementId)) throw new Error('table_structure_conflict')
    structuralSlides.add(item.slideIndex)
  }
  const tableStyles = request.tableStyles ?? [], styledTables = new Set<string>()
  const shadingColors = ['none','#FFFFFF','#F2F2F2','#DAEEF3','#EBF3FB','#D6E4F0','#FFF2CC','#FFE6CC','#FCE4D6','#E2EFDA','#E6E6FF']
  if (!Array.isArray(tableStyles) || tableStyles.length > 500) throw new Error('table_styles_invalid')
  let cellShadingCount = 0
  for (const item of tableStyles) {
    if (!item || Object.keys(item).some(key => !['slideIndex','elementId','styleName',...TABLE_FLAG_KEYS,'shadingColor','borderPreset','cellShadings'].includes(key)) || !validSlideIndex(item.slideIndex,slideCount) || typeof item.elementId !== 'string' || (item.styleName === undefined && TABLE_FLAG_KEYS.every(key => item[key] === undefined) && item.shadingColor === undefined && item.borderPreset === undefined && item.cellShadings === undefined) || (item.styleName !== undefined && (typeof item.styleName !== 'string' || !Object.hasOwn(TABLE_STYLE_PRESETS,item.styleName))) || TABLE_FLAG_KEYS.some(key => item[key] !== undefined && typeof item[key] !== 'boolean') || (item.shadingColor !== undefined && !shadingColors.includes(item.shadingColor)) || (item.borderPreset !== undefined && !['all','none'].includes(item.borderPreset)) || styledTables.has(`${item.slideIndex}:${item.elementId}`) || touchesDeleted(item.slideIndex,item.elementId) || !originalSlides[item.slideIndex]!.elements.some(el => el.id === item.elementId && el.type === 'table')) throw new Error('table_style_invalid')
    const target = originalSlides[item.slideIndex]!.elements.find(el => el.id === item.elementId)!
    if ((item.styleName !== undefined || TABLE_FLAG_KEYS.some(key => item[key] !== undefined)) && !tableStyleState(target as TableElement).tablePresetEditable) throw new Error('table_style_source_unsupported')
    if (item.cellShadings !== undefined) {
      const cells = item.cellShadings, source = target as TableElement
      if (!Array.isArray(cells) || cells.length === 0 || (cellShadingCount += cells.length) > 500 || !cellShadingSource(source,originalSlides[item.slideIndex]!.path)) throw new Error('table_cell_shading_source_or_budget_invalid')
      const keys = new Set<string>()
      for (const cell of cells) {
        if (!cell || typeof cell !== 'object' || Object.keys(cell).sort().join() !== 'col,row,shadingColor' || !Number.isInteger(cell.row) || !Number.isInteger(cell.col) || cell.row < 0 || cell.col < 0 || cell.row >= source.rows.length || cell.col >= source.colWidths.length || !shadingColors.includes(cell.shadingColor) || keys.has(`${cell.row}:${cell.col}`)) throw new Error('table_cell_shading_invalid')
        keys.add(`${cell.row}:${cell.col}`)
      }
    }
    styledTables.add(`${item.slideIndex}:${item.elementId}`)
  }
  if (!Array.isArray(request.tableCells ?? []) || (request.tableCells ?? []).length > 500) throw new Error('table_cells_invalid')
  const editedCells = new Set<string>()
  for (const cell of request.tableCells ?? []) {
    if (!cell || typeof cell !== 'object' || Object.keys(cell).sort().join() !== 'col,elementId,row,slideIndex,text' || !validSlideIndex(cell.slideIndex, slideCount) || typeof cell.elementId !== 'string'
      || !Number.isInteger(cell.row) || !Number.isInteger(cell.col) || cell.row < 0 || cell.col < 0 || typeof cell.text !== 'string' || cell.text.length > 10000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(cell.text) || touchesDeleted(cell.slideIndex, cell.elementId)) throw new Error('table_cell_invalid')
    const key = `${cell.slideIndex}:${cell.elementId}:${cell.row}:${cell.col}`
    if (editedCells.has(key)) throw new Error('table_cell_duplicated')
    editedCells.add(key)
  }
  if (!Array.isArray(request.shapeKinds ?? []) || (request.shapeKinds ?? []).length > 500) throw new Error('shape_kinds_invalid')
  const reshaped = new Set<string>()
  for (const item of tableStyles) {
    const slide = originalSlides[item.slideIndex]!
    if (item.styleName !== undefined) {
      const preset = TABLE_STYLE_PRESETS[item.styleName]!
      if (preset.styleId) ensureTableStylePart(opened,preset.styleId,preset.styleDefXml!)
      if (!editTableStyle(slide,item.elementId,{ tblPrXml:preset.tblPrXml, clearDirectFormatting:true, ...(preset.border ? {borderPreset:'all',borderColor:preset.border.color,borderWidthEmu:preset.border.widthEmu} : {}) })) throw new Error('table_style_target_invalid')
    }
    const flags = Object.fromEntries(TABLE_FLAG_KEYS.filter(key => item[key] !== undefined).map(key => [key,item[key]]))
    if (Object.keys(flags).length && !editTableStyle(slide,item.elementId,flags)) throw new Error('table_style_target_invalid')
    const patch = { ...(item.shadingColor !== undefined ? {shadingColor:item.shadingColor} : {}), ...(item.borderPreset !== undefined ? {borderPreset:item.borderPreset, ...(item.borderPreset === 'all' ? {borderColor:'#000000',borderWidthEmu:12700} : {})} : {}) }
    if (!editTableStyle(originalSlides[item.slideIndex]!,item.elementId,patch)) throw new Error('table_style_target_invalid')
    if (item.cellShadings !== undefined) {
      const table = slide.elements.find(element => element.id === item.elementId) as TableElement
      const before = cellShadingSource(table,slide.path)
      if (!before) throw new Error('table_cell_shading_source_changed')
      for (const cell of item.cellShadings) if (!editTableStyle(slide,item.elementId,{shadingColor:cell.shadingColor,cells:[{row:cell.row,col:cell.col}]})) throw new Error('table_cell_shading_failed')
      const after = cellShadingSource(table,slide.path), targets = new Map(item.cellShadings.map(cell => [`${cell.row}:${cell.col}`,cell.shadingColor]))
      if (!after) throw new Error('table_cell_shading_output_invalid')
      for (const [row,cells] of before.entries()) for (const [col,original] of cells.entries()) {
        const changed = after[row]![col]!, color = targets.get(`${row}:${col}`)
        if (color === undefined ? original !== changed : withoutCellProperties(original) !== withoutCellProperties(changed)) throw new Error('table_cell_shading_identity_changed')
        if (color !== undefined) {
          const properties = /<a:tcPr[^>]*>[\s\S]*?<\/a:tcPr>/.exec(changed)?.[0]
          const actual = properties ? tableStyleParser.parse(properties)['a:tcPr'] : null
          if (!actual || (color === 'none' ? !Object.hasOwn(actual,'a:noFill') : actual['a:solidFill']?.['a:srgbClr']?.['@_val'] !== color.slice(1))) throw new Error('table_cell_shading_not_applied')
        }
      }
    }

  }
  for (const item of request.shapeKinds ?? []) {
    if (!item || typeof item !== 'object' || Object.keys(item).some(key => !['slideIndex', 'elementId', 'kind'].includes(key)) || !validSlideIndex(item.slideIndex, slideCount) || typeof item.elementId !== 'string'
      || typeof item.kind !== 'string' || !shapePresets.presets.includes(item.kind) || shapePresets.lines.includes(item.kind)
      || touchesDeleted(item.slideIndex, item.elementId) || reshaped.has(`${item.slideIndex}:${item.elementId}`)) throw new Error('shape_kind_invalid')
    reshaped.add(`${item.slideIndex}:${item.elementId}`)
  }
  if (!Array.isArray(request.shapeStyles ?? []) || (request.shapeStyles ?? []).length > 500) throw new Error('shape_styles_invalid')
  const styled = new Set<string>()
  for (const style of request.shapeStyles ?? []) {
    if (!style || typeof style !== 'object' || Object.keys(style).some(key => !['slideIndex', 'elementId', 'fill', 'stroke'].includes(key)) || !validSlideIndex(style.slideIndex, slideCount) || typeof style.elementId !== 'string' || !style.elementId
      || (style.fill === undefined && style.stroke === undefined)
      || (style.fill !== undefined && style.fill !== 'none' && (typeof style.fill !== 'string' || !colorPattern.test(style.fill)))
      || (style.stroke !== undefined && style.stroke !== null && (typeof style.stroke !== 'object' || Object.keys(style.stroke).some(key => !['color', 'widthPt'].includes(key)) || typeof style.stroke.color !== 'string' || !colorPattern.test(style.stroke.color) || !Number.isFinite(style.stroke.widthPt) || style.stroke.widthPt <= 0 || style.stroke.widthPt > 100))
      || touchesDeleted(style.slideIndex, style.elementId) || styled.has(`${style.slideIndex}:${style.elementId}`)) throw new Error('shape_style_invalid')
    styled.add(`${style.slideIndex}:${style.elementId}`)
  }
  const sequences = request.animationSequences ?? []
  if (!Array.isArray(sequences) || sequences.length > slideCount) throw new Error('animation_sequences_invalid')
  const sequencedSlides = new Set<number>()
  for (const sequence of sequences) {
    if (!sequence || typeof sequence !== 'object' || Object.keys(sequence).sort().join() !== 'items,slideIndex' || !validSlideIndex(sequence.slideIndex, slideCount)
      || sequencedSlides.has(sequence.slideIndex) || !Array.isArray(sequence.items) || sequence.items.length > 500) throw new Error('animation_sequence_invalid')
    sequencedSlides.add(sequence.slideIndex)
    // 同一页不能同时使用逐条追加（animations）与整页覆盖（animationSequences）
    if ((request.animations ?? []).some(item => item.slideIndex === sequence.slideIndex)) throw new Error('animation_sequence_conflict')
    const slide = originalSlides[sequence.slideIndex]!
    const existing = getSlideAnimations(slide)
    const usedSources = new Set<number>()
    for (const item of sequence.items) {
      if (!item || typeof item !== 'object') throw new Error('animation_sequence_item_invalid')
      const timing = (value: AnimationTiming) => (value.trigger === undefined || ['onClick', 'withPrev', 'afterPrev'].includes(value.trigger))
        && (value.durationMs === undefined || validTiming(value.durationMs)) && (value.delayMs === undefined || validTiming(value.delayMs))
      if ('source' in item) {
        const source = existing[item.source]
        if (Object.keys(item).some(key => !['source', 'spid', 'effect', 'trigger', 'durationMs', 'delayMs'].includes(key)) || !Number.isInteger(item.source) || !source
          || usedSources.has(item.source) || source.spid !== item.spid || source.effect !== item.effect || !timing(item)) throw new Error('animation_sequence_source_invalid')
        // 原样保留的预设（presetXml）计时写在原始 XML 内，修改会被静默忽略：拒绝而不是假装生效
        if (source.presetXml && (item.trigger !== undefined || item.durationMs !== undefined || item.delayMs !== undefined)) throw new Error('animation_sequence_preset_readonly')
        const owner = slide.elements.find(element => elementSpid(element) === source.spid)
        if (owner && touchesDeleted(sequence.slideIndex, owner.id)) throw new Error('delete_target_has_pending_edits')
        const changedText = (request.edits ?? []).findLast(edit => edit.slideIndex === sequence.slideIndex && edit.elementId === owner?.id && edit.text !== undefined)?.text
        if (changedText !== undefined && source.paragraph !== undefined && source.paragraph >= changedText.split(/\r?\n/).length) throw new Error('animation_paragraph_invalid')
        usedSources.add(item.source)
        continue
      }
      if (Object.keys(item).some(key => !['elementId', 'effect', 'trigger', 'durationMs', 'delayMs', 'direction', 'motionPath', 'paragraph'].includes(key))
        || typeof item.elementId !== 'string' || !NEW_ANIMATION_EFFECTS.has(item.effect) || item.trigger === undefined || !timing(item) || !validTiming(item.durationMs) || !validTiming(item.delayMs)
        || (item.direction !== undefined && (!['top', 'bottom', 'left', 'right'].includes(item.direction) || !['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(item.effect)))
        || ((item.effect === 'motionPath') !== (item.motionPath !== undefined)) || (item.motionPath !== undefined && !MOTION_PATH_PRESETS.includes(item.motionPath))) throw new Error('animation_sequence_item_invalid')
      const element = slide.elements.find(candidate => candidate.id === item.elementId)
      if (!element || elementSpid(element) === null || (element.type !== 'text' && element.type !== 'shape') || touchesDeleted(sequence.slideIndex, item.elementId)) throw new Error('animation_target_invalid')
      if (item.paragraph !== undefined && (!Number.isInteger(item.paragraph) || item.paragraph < 0 || item.paragraph >= ((request.edits ?? []).findLast(edit => edit.slideIndex === sequence.slideIndex && edit.elementId === item.elementId && edit.text !== undefined)?.text?.split(/\r?\n/).length ?? (element as { text?: { paragraphs: unknown[] } }).text?.paragraphs.length ?? 0) || item.effect === 'motionPath')) throw new Error('animation_paragraph_invalid')
    }
  }
  if ((request.edits ?? []).some((edit) => touchesDeleted(edit.slideIndex, edit.elementId)) ||
    (request.animations ?? []).some((item) => touchesDeleted(item.slideIndex, item.elementId)) ||
    (request.paragraphFormatting ?? []).some((item) => touchesDeleted(item.slideIndex, item.elementId))) {
    throw new Error('delete_target_has_pending_edits')
  }
  const backgroundImages = validateBackgroundImages(opened, request.backgroundImages, { removedSlides, colorSlides: new Set((request.backgrounds ?? []).map(item => item.slideIndex)) })
  for (const background of request.backgrounds ?? []) {
    if (!validSlideIndex(background.slideIndex, slideCount)) throw new Error('background_slide_index_invalid')
    if (typeof background.color !== 'string' || !colorPattern.test(background.color)) throw new Error('background_color_invalid')
  }
  if ((request.shapes ?? []).length > 500) throw new Error('shapes_invalid')
  for (const shape of request.shapes ?? []) {
    if (!shape || typeof shape !== 'object' || Object.keys(shape).some(key => !['slideIndex', 'kind', 'geometry'].includes(key)) || !validSlideIndex(shape.slideIndex, slideCount) || typeof shape.kind !== 'string' || !shapePresets.presets.includes(shape.kind) || !validGeometry(shape.geometry)) throw new Error('shape_invalid')
  }
  for (const box of request.textBoxes ?? []) {
    if (!validSlideIndex(box.slideIndex, slideCount)) throw new Error('textbox_slide_index_invalid')
    if (typeof box.text !== 'string' || box.text.length > 20000) throw new Error('textbox_text_invalid')
    if (!validGeometry(box.geometry)) throw new Error('textbox_geometry_invalid')
    if (box.fontSize !== undefined && (!Number.isFinite(box.fontSize) || box.fontSize < 1 || box.fontSize > 400)) throw new Error('textbox_font_invalid')
    if (box.fontFamily !== undefined && (typeof box.fontFamily !== 'string' || !box.fontFamily.trim() || box.fontFamily.length > 200)) throw new Error('textbox_font_invalid')
    if (box.color !== undefined && (typeof box.color !== 'string' || !colorPattern.test(box.color))) throw new Error('textbox_color_invalid')
    if (box.bold !== undefined && typeof box.bold !== 'boolean') throw new Error('textbox_font_invalid')
    if (box.rotation !== undefined && (!Number.isFinite(box.rotation) || Math.abs(box.rotation) > 360)) throw new Error('textbox_rotation_invalid')
    if (box.field !== undefined && !['slidenum', 'datetime1'].includes(box.field)) throw new Error('textbox_field_invalid')
    if ((box.italic !== undefined && typeof box.italic !== 'boolean') || (box.wordArt !== undefined && typeof box.wordArt !== 'boolean')
      || (box.outline !== undefined && (!box.outline || typeof box.outline !== 'object' || Object.keys(box.outline).sort().join() !== 'color,widthEmu' || typeof box.outline.color !== 'string' || !colorPattern.test(box.outline.color) || !Number.isInteger(box.outline.widthEmu) || box.outline.widthEmu < 1 || box.outline.widthEmu > 254000))) throw new Error('textbox_wordart_invalid')
  }
  applyPictureOpacities(opened, pictureOpacities)
  applyPictureCrops(opened,pictureCrops)
  for (const edit of request.edits ?? []) {
    if (Object.keys(edit).some(key => !['slideIndex', 'elementId', 'text', 'geometry', 'fontSizePt', 'fontFamily', 'color', 'bold', 'italic', 'underline', 'strike'].includes(key))) {
      throw new Error('element_edit_invalid')
    }
    if (edit.fontSizePt !== undefined && (!Number.isFinite(edit.fontSizePt) || edit.fontSizePt < 1 || edit.fontSizePt > 400)) throw new Error('text_format_font_invalid')
    if (edit.fontFamily !== undefined && (typeof edit.fontFamily !== 'string' || !edit.fontFamily.trim() || edit.fontFamily.length > 200 || /[\x00-\x1f]/.test(edit.fontFamily))) throw new Error('text_format_font_invalid')
    if (edit.color !== undefined && (typeof edit.color !== 'string' || !colorPattern.test(edit.color))) throw new Error('text_format_color_invalid')
    if (['bold', 'italic', 'underline', 'strike'].some(key => edit[key as keyof TextEdit] !== undefined && typeof edit[key as keyof TextEdit] !== 'boolean')) throw new Error('text_format_font_invalid')
    if (!Number.isInteger(edit.slideIndex) || edit.slideIndex < 0 || edit.slideIndex >= opened.deck.slides.length) {
      throw new Error('slide_index_invalid')
    }
    const element = opened.deck.slides[edit.slideIndex]!.elements.find((candidate) => candidate.id === edit.elementId)
    if (!element || !['text','shape','picture'].includes(element.type)) throw new Error('element_not_editable')
    if (element.type === 'picture' && Object.keys(edit).some(key => !['slideIndex','elementId','geometry'].includes(key))) throw new Error('element_not_editable')
    if (edit.text !== undefined) {
      if (element.type !== 'text' && element.type !== 'shape') throw new Error('element_not_editable')
      if (!element.text?.paragraphs.length) throw new Error('element_text_missing')
      element.text.paragraphs = applyEditParagraphs(
        element.text.paragraphs,
        edit.text.split(/\r?\n/).map((text) => ({ runs: [{ text }] })),
      )
      element.dirty = true
    }
    if (edit.geometry) {
      const { x, y, width, height } = edit.geometry
      if (![x,y,width,height].every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=100000)||width<=0||height<=0) throw new Error('element_geometry_invalid')
      element.transform.offset = {
        x: Math.round(x * 9525),
        y: Math.round(y * 9525),
        cx: Math.round(width * 9525),
        cy: Math.round(height * 9525),
      }
      element.dirtyTransform = true
      updateConnectorsForMoved(opened.deck.slides[edit.slideIndex]!,[element.id])
    }
  }
  applyPictureReplacements(opened,pictureReplacements)
  for (const image of [...(request.images ?? []), ...(request.nativeImages ?? [])]) {
    if (!Number.isInteger(image.slideIndex) || image.slideIndex < 0 || image.slideIndex >= slideCount) {
      throw new Error('image_slide_index_invalid')
    }
    const slide = opened.deck.slides[image.slideIndex]!
    const content = Buffer.from(image.bytesBase64, 'base64')
    if (content.toString('base64') !== image.bytesBase64 || !['png', 'jpg'].includes(image.extension)) {
      throw new Error('image_asset_invalid')
    }
    const { x, y, width, height } = image.geometry
    const added = addPicture(opened, slide, {
      bytes: new Uint8Array(content),
      ext: image.extension,
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      name: image.descr === 'AI 生成配图' ? 'AI 生成配图' : '插入的图片',
      descr: image.descr,
    })
    if (!added) throw new Error('image_format_unsupported')
  }
  for (const item of hiddenSlides) setSlideHidden(originalSlides[item.slideIndex]!, item.hidden)
  for (const transition of request.transitions ?? []) {
    if (!Number.isInteger(transition.slideIndex) || transition.slideIndex < 0 || transition.slideIndex >= slideCount) {
      throw new Error('transition_slide_index_invalid')
    }
    const slide = opened.deck.slides[transition.slideIndex]!
    const preserved = patchTransitionPreservingMetadata(slide.bodySuffix, transition.kind)
    if (preserved !== slide.bodySuffix) {
      // Keep the pinned operation's dirty/save hook, then install preserved source XML.
      setSlideTransition(slide, transition.kind)
      slide.bodySuffix = preserved
    }
  }
  for (const animation of request.animations ?? []) {
    const durationMs = animation.durationMs ?? 500
    const delayMs = animation.delayMs ?? 0
    if (!Number.isFinite(durationMs) || durationMs < 0 || !Number.isFinite(delayMs) || delayMs < 0) {
      throw new Error('animation_timing_invalid')
    }
    if (animation.direction !== undefined && (
      !['top', 'bottom', 'left', 'right'].includes(animation.direction) ||
      !['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(animation.effect)
    )) throw new Error('animation_direction_invalid')
    const slide = opened.deck.slides[animation.slideIndex]
    const element = slide?.elements.find((candidate) => candidate.id === animation.elementId)
    const spid = element ? elementSpid(element) : null
    if (!slide || spid === null || (element!.type !== 'text' && element!.type !== 'shape')) {
      throw new Error('animation_target_invalid')
    }
    const existing = getSlideAnimations(slide)
    const index = animation.append ? -1 : existing.findIndex((item) => item.spid === spid && item.effect === animation.effect)
    const updated: SlideAnimation = {
      ...(index >= 0 ? existing[index] : {}),
      spid,
      effect: animation.effect,
      trigger: animation.trigger,
      durationMs,
      delayMs,
      ...(animation.direction !== undefined ? { direction: animation.direction } : {}),
    }
    if (index >= 0) existing[index] = updated
    else existing.push(updated)
    setSlideAnimations(slide, existing)
  }
  for (const sequence of request.animationSequences ?? []) {
    const slide = opened.deck.slides[sequence.slideIndex]!
    const existing = getSlideAnimations(slide)
    const next: SlideAnimation[] = sequence.items.map(item => {
      if ('source' in item) {
        const source = existing[item.source]!
        return { ...source, ...(item.trigger !== undefined ? { trigger: item.trigger } : {}), ...(item.durationMs !== undefined ? { durationMs: item.durationMs } : {}), ...(item.delayMs !== undefined ? { delayMs: item.delayMs } : {}) }
      }
      const element = slide.elements.find(candidate => candidate.id === item.elementId)!
      return {
        spid: elementSpid(element)!, effect: item.effect, trigger: item.trigger, durationMs: item.durationMs, delayMs: item.delayMs,
        ...(item.direction !== undefined ? { direction: item.direction } : {}),
        ...(item.motionPath !== undefined ? { motionPath: item.motionPath } : {}),
        ...(item.paragraph !== undefined ? { paragraph: item.paragraph } : {}),
      }
    })
    if (JSON.stringify(next) !== JSON.stringify(existing)) setSlideAnimations(slide, next)
  }
  for (const deletion of deletions) {
    if (!deleteElement(opened, originalSlides[deletion.slideIndex]!, deletion.elementId)) throw new Error('delete_target_invalid')
  }
  for (const cell of request.tableCells ?? []) {
    const slide = originalSlides[cell.slideIndex]!
    const table = slide.elements.find(candidate => candidate.id === cell.elementId) as unknown as { type: string; rows: { merged?: boolean; text?: { paragraphs: { runs: { text: string }[] }[] } }[][] } | undefined
    const source = table?.type === 'table' ? table.rows[cell.row]?.[cell.col] : undefined
    if (!source || source.merged) throw new Error('table_cell_target_invalid')
    const paragraphs = applyEditParagraphs(source.text?.paragraphs ?? [], cell.text.split(/\r?\n/).map(text => ({ runs: [{ text }] })))
    if (!editTableCellText(slide, cell.elementId, cell.row, cell.col, paragraphs as never)) throw new Error('table_cell_target_invalid')
  }
  for (const item of request.shapeKinds ?? []) {
    const slide = originalSlides[item.slideIndex]!
    const element = slide.elements.find(candidate => candidate.id === item.elementId)
    if (!element || element.type !== 'shape' || !setShapePresetGeometry(slide, item.elementId, item.kind)) throw new Error('shape_kind_target_invalid')
  }
  for (const style of request.shapeStyles ?? []) {
    const slide = originalSlides[style.slideIndex]!
    const element = slide.elements.find(candidate => candidate.id === style.elementId)
    if (!element || (element.type !== 'text' && element.type !== 'shape')) throw new Error('shape_style_target_invalid')
    if (style.fill !== undefined && !setElementFill(opened, slide, style.elementId, style.fill)) throw new Error('shape_fill_failed')
    if (style.stroke !== undefined) {
      const target = element as typeof element & { stroke?: unknown; dirtyStroke?: boolean }
      target.stroke = style.stroke ? strokePatchToModel({ color: style.stroke.color.toUpperCase(), widthEmu: Math.round(style.stroke.widthPt * 12700) }) : undefined
      target.dirtyStroke = true
    }
  }
  for (const selection of request.slideLayouts ?? []) {
    if (!Number.isInteger(selection.slideIndex) || selection.slideIndex < 0 || selection.slideIndex >= slideCount) {
      throw new Error('layout_slide_index_invalid')
    }
    if (!layouts.some((layout) => layout.path === selection.layoutPath)) {
      throw new Error('layout_path_invalid')
    }
    const laidOut = setSlideLayout(opened, selection.slideIndex, selection.layoutPath)
    if (!laidOut) throw new Error('layout_apply_failed')
    // Layout materialization replaces the slide model; later edits must target
    // that live object while retaining the request's original slide indices.
    originalSlides[selection.slideIndex] = laidOut
  }
  if (newSlides.length && !request.order) throw new Error('new_slides_require_order')
  // 原始编号 = 来源页 + 新建页；删除按部件路径执行，order 用原始编号列出全部保留页。
  const originalPaths = opened.deck.slides.map((slide) => slide.path)
  if (deletedSlides.length >= originalPaths.length) throw new Error('deleted_slides_all')
  for (const index of deletedSlides) {
    const current = opened.deck.slides.findIndex((slide) => slide.path === originalPaths[index])
    if (current < 0 || !deleteSlide(opened, current)) throw new Error('slide_delete_failed')
  }
  if (request.order) {
    if (request.order.length !== opened.deck.slides.length || new Set(request.order).size !== request.order.length || request.order.some((n) => !Number.isInteger(n) || n < 0 || n >= originalPaths.length || removedSlides.has(n))) {
      throw new Error('slide_order_invalid')
    }
    const desired = request.order.map((index) => originalPaths[index]!)
    for (let target = 0; target < desired.length; target++) {
      const current = opened.deck.slides.findIndex((slide) => slide.path === desired[target])
      if (current !== target) moveSlide(opened, current, target)
    }
  }
  const sections = request.sections ?? []
  if (!Array.isArray(sections) || sections.length > 100) throw new Error('sections_invalid')
  for (const section of sections) {
    if (!section || typeof section !== 'object' || Object.keys(section).some(key => !['slideIndex', 'name'].includes(key)) || !Number.isInteger(section.slideIndex) || section.slideIndex < 0 || section.slideIndex >= originalPaths.length || removedSlides.has(section.slideIndex)
      || typeof section.name !== 'string' || !section.name.trim() || [...section.name].length > 100 || /[\u0000-\u001f\u007f]/.test(section.name)) throw new Error('section_invalid')
    const current = opened.deck.slides.findIndex(slide => slide.path === originalPaths[section.slideIndex])
    if (current < 0 || !addSection(opened, current, section.name.trim())) throw new Error('section_add_failed')
  }
  if (request.theme) {
    const spec = themes[request.theme]
    applyThemeToArchive(opened, spec)
    remapDeckColors(opened, spec)
  }
  for (const edit of request.edits ?? []) {
    const { fontSizePt, fontFamily, color, bold, italic, underline, strike } = edit
    if ([fontSizePt, fontFamily, color, bold, italic, underline, strike].some(value => value !== undefined)) {
      if (!setElementFont(originalSlides[edit.slideIndex]!, edit.elementId, {
        ...(fontSizePt !== undefined ? { fontSizePt } : {}),
        ...(fontFamily !== undefined ? { fontFamily } : {}),
        ...(color !== undefined ? { color: color.toUpperCase() } : {}),
        ...(bold !== undefined ? { bold } : {}),
        ...(italic !== undefined ? { italic } : {}),
        ...(underline !== undefined ? { underline } : {}),
        ...(strike !== undefined ? { strike } : {}),
      })) throw new Error('text_format_target_invalid')
    }
  }
  for (const format of request.paragraphFormatting ?? []) {
    const { slideIndex, elementId, ...patch } = format
    const slide = originalSlides[slideIndex]
    const element = slide?.elements.find(candidate => candidate.id === elementId)
    if (!slide || !element || (element.type !== 'text' && element.type !== 'shape') || !element.text ||
      !setElementParagraphFormat(slide, elementId, patch)) throw new Error('paragraph_format_target_invalid')
    // Validate every ordered command so a later opposite indent cannot hide overflow.
    if (element.text?.paragraphs.some(paragraph =>
        (paragraph.marL != null && (paragraph.marL < 0 || paragraph.marL > maxParagraphEmu)) ||
        (paragraph.indent != null && Math.abs(paragraph.indent) > maxParagraphEmu))) {
      throw new Error('paragraph_indent_out_of_range')
    }
  }
  for (const background of request.backgrounds ?? []) {
    setSlideBackground(opened, originalSlides[background.slideIndex]!, background.color.toUpperCase())
  }
  applyBackgroundImages(opened, originalSlides, backgroundImages)
  for (const shape of request.shapes ?? []) {
    const { x, y, width, height } = shape.geometry
    const line = shapePresets.lines.includes(shape.kind)
    addElement(originalSlides[shape.slideIndex]!, {
      kind: shape.kind,
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      ...(line ? { stroke: { color: '#000000', widthEmu: 12700 } } : { fillColor: '#C43E1C' }),
    })
  }
  for (const box of request.textBoxes ?? []) {
    const { x, y, width, height } = box.geometry
    const element = addElement(originalSlides[box.slideIndex]!, {
      kind: 'textbox',
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      // 固定源 insertField：页码/日期为 <a:fld> 动态字段（文字为缓存值），居中。
      paragraphs: box.text.split(/\r?\n/).map((text) => ({ ...(box.field || box.wordArt ? { align: 'center' as const } : {}), runs: [{
        ...(box.italic ? { italic: true } : {}),
        ...(box.outline ? { outline: { color: box.outline.color.toUpperCase(), widthEmu: box.outline.widthEmu } } : {}),
        ...(box.field ? { field: box.field } : {}),
        text,
        fontSize: box.fontSize ?? 18,
        ...(box.fontFamily ? { fontFamily: box.fontFamily } : {}),
        color: (box.color ?? '#000000').toUpperCase(),
        ...(box.bold ? { bold: true } : {}),
      }] })),
      bodyPr: box.wordArt ? { wrap: 'none', autoFit: 'resize' } : { autoFit: 'shrink' },
    })
    if (box.rotation) {
      element.transform.rot = Math.round(box.rotation * 60000)
      element.dirtyTransform = true
    }
  }
  if (request.slideSize) {
    const { cx, cy } = request.slideSize
    if (Object.keys(request.slideSize).length !== 2
      || ![cx, cy].every(value => Number.isInteger(value) && value >= 914400 && value <= 51206400)) {
      throw new Error('slide_size_invalid')
    }
    // Draft coordinates refer to the original canvas. Resize after all edits;
    // setSlideSize materializes slides and must not invalidate pending targets.
    if ((opened.deck.size.cx !== cx || opened.deck.size.cy !== cy) && !setSlideSize(opened, cx, cy)) {
      throw new Error('slide_size_apply_failed')
    }
  }
  // All source-ID edits are complete. A structure edit materializes the page
  // and changes element IDs, so allow one per source slide and carry its fresh handle.
  for (const item of tableStructures) {
    const index=opened.deck.slides.indexOf(originalSlides[item.slideIndex]!)
    if (index<0) throw new Error('table_structure_slide_missing')
    const source = originalSlides[item.slideIndex]!.elements.find(el => el.id === item.elementId)
    if (!source || source.type !== 'table' || !structureSafe(source)) throw new Error('table_structure_identity_changed')
    const expectedRows = [...source.rowHeights], expectedColumns = [...source.colWidths]
    const rowOperation = item.kind.endsWith('row'), expected = rowOperation ? expectedRows : expectedColumns
    if (item.kind.startsWith('insert-')) expected.splice(item.index + (item.before ? 0 : 1),0,expected[item.index]!)
    else expected.splice(item.index,1)
    const spid = elementSpid(source)
    const changed=editTableStructure(opened,index,item.elementId,{kind:item.kind,index:item.index,...(item.before!==undefined?{before:item.before}:{})})
    if (!changed) throw new Error('table_structure_failed')
    const result = changed.slide.elements.find(el => el.id === changed.elementId)
    if (!result || result.type !== 'table' || elementSpid(result) !== spid || JSON.stringify(result.rowHeights) !== JSON.stringify(expectedRows) || JSON.stringify(result.colWidths) !== JSON.stringify(expectedColumns) || result.rows.length !== expectedRows.length || result.rows.some(row => row.length !== expectedColumns.length) || result.transform.offset.cx !== expectedColumns.reduce((sum,n)=>sum+n,0) || result.transform.offset.cy !== expectedRows.reduce((sum,n)=>sum+n,0)) throw new Error('table_structure_output_identity_invalid')
    originalSlides[item.slideIndex]=changed.slide
  }
  // 固定源 tableInsertSpec：宽 2/3 居中、顶部 10.5%、行高 29.2pt；在全部按对象身份的修改与尺寸缩放之后插入。
  for (const table of tables) {
    const { cx, cy } = opened.deck.size, rowHeightEmu = Math.round(29.2 * 12700), width = Math.round(cx * 2 / 3)
    const slideIndex = opened.deck.slides.indexOf(originalSlides[table.slideIndex]!)
    if (slideIndex < 0) throw new Error('table_slide_missing')
    const added = addTable(opened, slideIndex, { rows: table.rows, cols: table.cols, offset: { x: Math.round((cx - width) / 2), y: Math.round(cy * 0.105), cx: width, cy: table.rows * rowHeightEmu }, rowHeightsEmu: Array(table.rows).fill(rowHeightEmu) })
    if (!added) throw new Error('table_insert_failed')
    // 插入会重建页面对象：更新引用，供同页后续表格/图表定位
    originalSlides[table.slideIndex] = added.slide
  }
  // 图表与表格一样会重建页面，放在全部按对象身份的修改之后；位置同固定源 graphicFrameInsertFrame。
  for (const chart of charts) {
    const { cx, cy } = opened.deck.size, width = Math.round(cx * 2 / 3), height = Math.round(width * 2 / 3)
    const slideIndex = opened.deck.slides.indexOf(originalSlides[chart.slideIndex]!)
    if (slideIndex < 0) throw new Error('chart_slide_missing')
    const added = addChart(opened, slideIndex, { kind: (chart.kind === 'barH' ? 'bar' : chart.kind) as never, ...(chart.kind === 'barH' ? { barDir: 'bar' as const } : {}), categories: chart.categories, series: chart.series, offset: { x: Math.round((cx - width) / 2), y: Math.round((cy - height) / 2), cx: width, cy: height } })
    if (!added) throw new Error('chart_insert_failed')
    originalSlides[chart.slideIndex] = added.slide
  }
  for (const item of smartArts) {
    const { cx, cy } = opened.deck.size, width = Math.round(cx * 2 / 3), height = Math.round(width * 2 / 3)
    const slideIndex = opened.deck.slides.indexOf(originalSlides[item.slideIndex]!)
    if (slideIndex < 0) throw new Error('smartart_slide_missing')
    const added = addSmartArt(opened, slideIndex, { layout: item.layout as never, items: item.items, offset: { x: Math.round((cx - width) / 2), y: Math.round((cy - height) / 2), cx: width, cy: height } })
    if (!added) throw new Error('smartart_insert_failed')
    originalSlides[item.slideIndex] = added.slide
  }
  // 页眉页脚会重建页面：放在全部修改与表格之后，应用到最终全部页面（含新建页）。
  if (request.headerFooter !== undefined) {
    const hf = request.headerFooter
    const text = (value: unknown) => value === null || (typeof value === 'string' && [...value].length <= 500 && !/[\u0000-\u0008\u000b-\u001f\u007f]/.test(value))
    if (!hf || typeof hf !== 'object' || Object.keys(hf).sort().join() !== 'date,dateAuto,footer,slideNum' || !text(hf.footer) || !text(hf.date) || typeof hf.slideNum !== 'boolean' || typeof hf.dateAuto !== 'boolean') throw new Error('header_footer_invalid')
    applyHeaderFooter(opened, { footer: hf.footer?.trim() || null, slideNum: hf.slideNum, date: hf.date?.trim() || null, dateAuto: hf.dateAuto })
  }
  if (!request.output) throw new Error('output_path_required')
  // 页面可能已重排；组合末尾按来源部件定位，重建ID后不再执行旧对象编辑。
  const mappedGroupEdits=groupEdits.map((item,index)=>{
    const matches=opened.deck.slides.flatMap((slide,slideIndex)=>slide.path===groupPaths[index]?[slideIndex]:[])
    if(matches.length!==1)throw Error('group_edit_source_missing_or_ambiguous')
    return {...item,slideIndex:matches[0]!}
  })
  applyLinkEdits(opened,linkEdits)
  applyClipboardPastes(opened,clipboardPastes)
  applyGroupEdits(opened,mappedGroupEdits)
  applyClassicCommentEdits(opened,commentEdits,commentSourcePaths,request.commentAuthor)
  applyNotesEdits(opened,notesEdits)
  const bytes = await savePptx(opened)
  await writeFile(request.output, bytes)
  let issues: { page: number; message: string }[]
  try {
    const audit = await auditDeck(bytes)
    issues = audit.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message })))
  } catch (error) {
    issues = [{ page: 0, message: `PPTX layout audit failed: ${error instanceof Error ? error.message : String(error)}` }]
  }
  process.stdout.write(JSON.stringify({
    slideCount: opened.deck.slides.length,
    issues,
  }))
}
