import { createOfficeAIEntry } from './office-ai-entry'
import { bindOfficeRibbonScroll } from './office-ribbon-scroll'
import { SLIDES_TABLE_PRESETS } from './slides-table-presets'
import { TableMiniPreview } from './vendor/genoffice-slides/components/table-mini-preview'
import { TABLE_SHADING_COLORS } from './vendor/genoffice-slides/components/table-shading-colors'
import { SLIDE_TRANSITIONS } from './slides-transitions'
import { AnimEffectIcon, IconAnimStar, IconNoneX, IconPathDiagonal } from './vendor/genoffice-slides/components/icons'
import { EFFECT_LABELS, MOTION_PATHS, type SequenceEffect } from './slides-animation-sequence'
import { IconApplyAll, IconTransCircle, IconTransCover, IconTransDissolve, IconTransFade, IconTransMorph, IconTransNone, IconTransPull, IconTransPush, IconTransRandom, IconTransSplit, IconTransWipe, IconTransZoom } from './vendor/genoffice-slides/components/icons'
import { SMARTART_GALLERY } from './vendor/genoffice-slides/components/smartart-gallery-data'
import { CHART_GALLERY } from './vendor/genoffice-slides/components/chart-gallery-data'
import { WORDART_PRESETS } from './vendor/genoffice-docs/packages/ui/src/wordart-presets'
/** 固定源 ribbon zh 语言包中的艺术字预设名称（ribbonWordArtPreset*） */
export const WORDART_PRESET_LABELS: Record<string, string> = { blue: '填充：蓝色', gold: '填充：金色', red: '填充：深红', purple: '填充：紫色', 'green-italic': '填充：绿色；斜体', 'white-orange': '填充：白色；描边：橙色', 'white-red': '填充：白色；描边：深红', 'gold-brown': '填充：金色；描边：棕色', 'sky-navy': '填充：天蓝；描边：藏青', 'navy-white': '填充：藏青；描边：白色', 'black-gold': '填充：黑色；描边：金色', 'silver-dark': '填充：银色；描边：深灰' }
import { LINE_SHAPE_KINDS, SHAPE_GALLERY_GROUPS } from './vendor/genoffice-slides/components/shape-gallery-data'
import './office-theme.css'
import '@smart-reporting/office-desktop-ui/slides.css'
import { desktopRibbonButton, desktopRibbonGroup } from '@smart-reporting/office-desktop-ui/slides'
import { BULLET_GLYPHS, BULLET_GLYPH_LABELS, BULLET_SYMBOLS, NUMBER_TYPES, BULLET_COLORS, PARAGRAPH_LIST_COMMANDS } from './slides-paragraph'
import { ArrowDown, ArrowUp, Bold, Download, FolderOpen, Italic, Plus, Strikethrough, Trash2, Underline, createElement } from 'lucide'
import { createElement as reactElement, type ComponentType } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { IconAlignCenter, IconAlignJustify, IconAlignLeft, IconAlignRight, IconChart, IconComment, IconCopy, IconCut, IconDateTime, IconEquation, IconFooter, IconFormatPainter, IconGrowFont, IconNavPane, IconNewSlide, IconPageNumber, IconPaste, IconPicture, IconPlayFromStart, IconSave, IconSection, IconScreenRec, IconShapes, IconShrinkFont, IconSmartArt, IconSlideLayout, IconSlideMaster, IconSwitchRowCol, IconTable, IconTextBox, IconWordArt } from './vendor/genoffice-slides/components/icons'
import { genOfficeHomeClipboardLocale } from './vendor/genoffice-slides/components/ribbon-home-clipboard-locales'
import { slidesLayoutLabel, slidesRibbonLabel } from './slides-native-ribbon-locales'
import { slidesRibbonIcons, slidesRibbonSourceIcons } from './slides-native-ribbon-icons'
import { IconPrintLayout, IconArrangeAll, IconOutlineView, IconReadMode, IconZoomIn, IconZoomOut, IconZoom100, IconFitWindow, IconRotateRight, IconRotateLeft, IconObjFlipH, IconObjFlipV } from './vendor/genoffice-slides/components/icons'
import { createNativeChartGallery, type NativeChartGalleryState } from './slides-native-chart-gallery'
import { SLIDES_AI_TRANSLATE_TARGETS } from './slides-ai-presets'
import iconTransparency from './vendor/genoffice-slides/components/icon-transparency.png'
import iconCrop from './vendor/genoffice-slides/components/icon-crop.png'
import { IconFillColor, IconPageBorders, IconShapeStyle } from './vendor/genoffice-slides/components/icons'
import { RIBBON_SHAPE_STYLES } from './vendor/genoffice-slides/components/shape-style-presets'
import { installPopoverDismiss } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
import { ShapePreview } from './vendor/genoffice-docs/packages/ui/src/shape-gallery'
import { STANDARD_COLORS, THEME_COLORS, THEME_COLOR_SHADES } from './vendor/genoffice-slides/ui/color-picker'
import { OUTLINE_DASHES } from '../../../reporting/slides_engine/bridge/pptx-outline'
import type { ShapeGradient } from '../../../reporting/slides_engine/bridge/pptx-shape-fill'

// Fixed GenOffice Ribbon.tsx ShapeFillMenu gradient presets.
function mixHex(from: string, to: string, t: number): string {
  const pf = parseInt(from.slice(1), 16)
  const pt = parseInt(to.slice(1), 16)
  const ch = (shift: number) => {
    const a = (pf >> shift) & 255
    const b = (pt >> shift) & 255
    return Math.round(a + (b - a) * t)
  }
  return `#${((ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).padStart(6, '0').toUpperCase()}`
}

function createShapeGradientPresets(localize: (label: string) => string, onPick: (fill: string | ShapeGradient) => void) {
  const details = document.createElement('details')
  const summary = document.createElement('summary')
  summary.textContent = localize('Gradient')
  const entries = document.createElement('div')
  details.append(summary, entries)
  const directions = [
    { angleDeg: 90, radial: false, css: 'linear-gradient(180deg', label: 'Linear Down' },
    { angleDeg: 0, radial: false, css: 'linear-gradient(90deg', label: 'Linear Right' },
    { angleDeg: 45, radial: false, css: 'linear-gradient(135deg', label: 'Linear Diagonal' },
    { angleDeg: 0, radial: true, css: 'radial-gradient(circle', label: 'From Center' },
  ] as const
  const render = (base: string) => {
    const none = document.createElement('button')
    none.type = 'button'
    none.textContent = localize('No Gradient')
    none.onclick = () => onPick(base)
    entries.replaceChildren(none)
    const variants = [
      { from: mixHex(base, '#FFFFFF', 0.7), to: base, label: 'Light Variations' },
      { from: base, to: mixHex(base, '#000000', 0.5), label: 'Dark Variations' },
    ]
    for (const variant of variants) {
      const heading = document.createElement('div')
      heading.textContent = localize(variant.label)
      const row = document.createElement('div')
      row.className = 'slides-fill-gradients'
      for (const direction of directions) {
        const button = document.createElement('button')
        button.type = 'button'
        button.dataset.shapeFillGradient = variant.label + ':' + direction.label
        button.title = localize(direction.label)
        button.setAttribute('aria-label', localize(variant.label) + ' · ' + button.title)
        button.style.backgroundImage = `${direction.css}, ${variant.from}, ${variant.to})`
        button.onclick = () => onPick({ from: variant.from, to: variant.to, angleDeg: direction.angleDeg, radial: direction.radial })
        row.append(button)
      }
      entries.append(heading, row)
    }
  }
  return { details, render }
}

/**
 * Native web subset of GenOffice Slides Ribbon at f8c17004fb730df11f0f743164ffd8b4281bb38c.
 * Active actions map to the existing editSlides order/theme/transitions/animations/layouts,
 * backgrounds/textBoxes/deletions fields. Other listed controls remain explicitly unavailable.
 * Focused command and availability tests live in slides-native-ribbon.test.ts.
 */
export type NativeSlidesContext = 'table' | 'chart' | 'picture' | 'shape' | 'model3d' | null
export type NativeSlidesAction = (command: string, value?: unknown) => void
export interface NativeSlidesLayout { path: string; name: string; layoutType?: string }
export interface NativeSlidesRibbon {
  setChartDesign(state: NativeChartGalleryState | null): void
  setContext(context: NativeSlidesContext): void
  setLayouts(layouts: NativeSlidesLayout[]): void
  setValue(command: string, value: string, hint?: string): void
  setTextFormatEnabled(enabled: boolean): void
  setListTargets(state: { bullets: boolean; numbers: boolean; hanging: boolean }): void
  setSlideOrientationEnabled(enabled: boolean): void
  setCommentEditEnabled(enabled: boolean, reason?: string): void
  setAIEditEnabled(enabled: boolean, reason?: string): void
  setTransitionEditEnabled(enabled: boolean, reason?: string): void
  setTransitionApplyAllEnabled(enabled: boolean, reason?: string): void
  setAnimationGallery(target: 'shape' | 'media' | null, effect: string): void
  setTablePresetEnabled(enabled: boolean, reason?: string): void
  setTableShadingState(value: string, cell: boolean, enabled: boolean, hint: string): void
  cancelAnimationHover(): void
  setLocked(locked: boolean): void
  dispose(): void
}

type RibbonGlyph = ComponentType<{ size?: number }>
type Control = { id: string; label: string; kind?: 'button' | 'toggle' | 'select' | 'color' | 'number' | 'font' | 'spacing'; options?: string[]; optionLabels?: string[]; caption?: string; icon?: Parameters<typeof createElement>[0]; sourceIcon?: RibbonGlyph; sourceActionId?: string; unavailable?: string }
type Group = { label: string; controls: Control[] }
type Tab = { id: string; label: string; groups: Group[]; context?: NativeSlidesContext }

// Pinned GenOffice Slides Ribbon.tsx transition gallery and English ribbon labels.
const transitionCards = {
  none: ['None', IconTransNone], morph: ['Morph', IconTransMorph], fade: ['Fade', IconTransFade],
  push: ['Push', IconTransPush], wipe: ['Wipe', IconTransWipe], split: ['Split', IconTransSplit],
  circle: ['Circle', IconTransCircle], cover: ['Cover', IconTransCover], pull: ['Uncover', IconTransPull],
  dissolve: ['Dissolve', IconTransDissolve], zoom: ['Zoom', IconTransZoom], random: ['Random', IconTransRandom],
} as const

// Pinned GenOffice Slides Ribbon.tsx ANIM_EFFECTS order and English locale labels.
const animationCards = [
  ['appear', 'Appear'], ['fade', 'Fade'], ['flyIn', 'Fly In'], ['wipe', 'Wipe'],
  ['wipeDown', 'Wipe Down'], ['splitIn', 'Split'], ['bounce', 'Bounce'], ['flipIn', 'Flip'],
  ['zoom', 'Zoom'], ['pulse', 'Pulse'], ['spin', 'Spin'], ['grow', 'Grow/Shrink'],
  ['teeter', 'Teeter'], ['disappear', 'Disappear'], ['fadeOut', 'Fade Out'], ['flyOut', 'Fly Out'],
  ['wipeOut', 'Wipe Out'], ['shrink', 'Shrink & Turn'], ['zoomOut', 'Zoom Out'],
  ['mediaPlay', 'Play'], ['mediaPause', 'Pause'], ['mediaStop', 'Stop'],
] as const satisfies ReadonlyArray<readonly [SequenceEffect, string]>
const animationCardChineseLabels: Partial<Record<SequenceEffect, string>> = {
  flipIn: '翻转式', shrink: '缩小旋转', mediaPlay: '播放', mediaPause: '暂停', mediaStop: '停止',
}

const noWrite = (operation: string) => `${operation} 尚无受支持的 editSlides 写回操作。`
const PICTURE_TRANSPARENCY_PRESETS = ['0', '15', '30', '50', '65', '80', '95']
const OUTLINE_WIDTHS = ['0.5', '1', '1.5', '2.25', '3', '4.5', '6']
const desktop = (operation: string) => `${operation} 依赖桌面 IPC 或本机资源；浏览器没有授权的 Web 等价操作。`
// Kept in sync with the fixed upstream @genoffice/pptx-ops font-size ladder.
const FONT_SIZE_LADDER = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44, 48, 54, 60, 66, 72, 80, 88, 96]
export function stepNativeFontSize(current: number | null | undefined, direction: 1 | -1): number {
  const from = Number.isFinite(current) ? current! : 18
  if (direction > 0) return from >= 96 ? Math.min(400, from + 8) : FONT_SIZE_LADDER.find(size => size > from) ?? 18
  if (from > 96) return Math.max(96, from - 8)
  if (from <= 8) return Math.max(1, from - 1)
  return FONT_SIZE_LADDER.findLast(size => size < from) ?? 8
}
const tabs: Tab[] = [
  { id: 'file', label: 'File', groups: [
    { label: 'File', controls: [{ id: 'openFile', label: 'Open', icon: FolderOpen, sourceActionId: 'onOpen' }] },
    { label: 'Save', controls: [
      { id: 'saveRevision', label: 'Save Revision', sourceIcon: IconSave, sourceActionId: 'onSave' },
      { id: 'saveAs', label: 'Save As', sourceIcon: IconSave, sourceActionId: 'onSaveAs' },
      { id: 'nameWithAi', label: 'Name with AI…', sourceIcon: IconSave, sourceActionId: 'onNameWithAi' },
    ] },
    { label: 'Export', controls: [
      { id: 'exportPdf', label: 'Export PDF', icon: Download, sourceActionId: 'onExportPdf' },
      { id: 'print', label: 'Print', sourceActionId: 'onPrint' },
      { id: 'exportImages', label: 'Export as PNG', sourceActionId: 'onExportImages' },
      { id: 'exportImagesJpg', label: 'Export as JPG', sourceActionId: 'onExportImagesJpg' },
    ] },
  ] },
  { id: 'home', label: 'Home', groups: [
    { label: 'AI 助手', controls: [] },
    { label: 'Clipboard', controls: [
      { id: 'paste', label: 'Paste', sourceIcon: IconPaste, sourceActionId: 'onPaste' },
      { id: 'cut', label: 'Cut', sourceIcon: IconCut, sourceActionId: 'onCut' },
      { id: 'copy', label: 'Copy', sourceIcon: IconCopy, sourceActionId: 'onCopy' },
      { id: 'formatBrush', label: 'Format Painter', sourceIcon: IconFormatPainter, sourceActionId: 'onFormatBrushClick' },
    ] },
    { label: 'Slides', controls: [
      { id: 'addSlide', label: 'New Slide', sourceIcon: IconNewSlide, sourceActionId: 'onAddSlide' },
      { id: 'addSlideWithLayout', label: 'New Slide with Layout', kind: 'select', sourceIcon: IconNewSlide, sourceActionId: 'onAddSlideWithLayout' },
      { id: 'layout', label: 'Change Layout', kind: 'select', sourceIcon: IconSlideLayout, sourceActionId: 'onSetLayout' },
      { id: 'resetLayout', label: 'Reset Layout', sourceIcon: IconSlideLayout, sourceActionId: 'onResetLayout' },
      { id: 'addSection', label: 'Add Section', sourceIcon: IconSection, sourceActionId: 'onAddSection' },
      { id: 'movePrevious', label: 'Move Earlier', icon: ArrowUp }, { id: 'moveNext', label: 'Move Later', icon: ArrowDown },
    ] },
    { label: 'Font', controls: [
      { id: 'fontFamily', label: 'Font Family', kind: 'font' },
      { id: 'fontSize', label: 'Font Size (pt)', kind: 'number' },
      { id: 'bold', label: 'Bold', kind: 'toggle', icon: Bold },
      { id: 'italic', label: 'Italic', kind: 'toggle', icon: Italic },
      { id: 'underline', label: 'Underline', kind: 'toggle', icon: Underline },
      { id: 'strike', label: 'Strikethrough', kind: 'toggle', icon: Strikethrough },
      { id: 'fontSizeUp', label: 'Increase Font Size', sourceIcon: IconGrowFont },
      { id: 'fontSizeDown', label: 'Decrease Font Size', sourceIcon: IconShrinkFont },
      { id: 'fontColor', label: 'Font Color', kind: 'color' },
    ] },
    { label: 'Paragraph', controls: [
      { id: 'bulletChar', label: 'Bullets', sourceActionId: 'onParagraphFormat' },
      { id: 'bulletNumber', label: 'Numbering', sourceActionId: 'onParagraphFormat' },
      { id: 'bulletNone', label: 'No Bullets', sourceActionId: 'onParagraphFormat' },
      { id: 'paragraphAlignLeft', label: 'Align Left', sourceIcon: IconAlignLeft, sourceActionId: 'onAlign' },
      { id: 'paragraphAlignCenter', label: 'Center', sourceIcon: IconAlignCenter, sourceActionId: 'onAlign' },
      { id: 'paragraphAlignRight', label: 'Align Right', sourceIcon: IconAlignRight, sourceActionId: 'onAlign' },
      { id: 'paragraphAlignJustify', label: 'Justify', sourceIcon: IconAlignJustify, sourceActionId: 'onAlign' },
      { id: 'indentDecrease', label: 'Decrease Indent', sourceActionId: 'onParagraphFormat' },
      { id: 'indentIncrease', label: 'Increase Indent', sourceActionId: 'onParagraphFormat' },
      { id: 'directionLtr', label: 'Left to Right', sourceActionId: 'onDirection' },
      { id: 'directionRtl', label: 'Right to Left', sourceActionId: 'onDirection' },
      { id: 'lineSpacingPct', label: 'Line Spacing', kind: 'select', options: ['100', '115', '150', '200', '250', '300'], sourceActionId: 'onParagraphFormat' },
      { id: 'spaceBeforePt', label: 'Space Before', kind: 'spacing', sourceActionId: 'onParagraphFormat' },
      { id: 'spaceAfterPt', label: 'Space After', kind: 'spacing', sourceActionId: 'onParagraphFormat' },
      { id: 'bulletCharPreset', label: 'Bullet Gallery', caption: '项目符号', kind: 'select', options: BULLET_GLYPHS.map((_, i) => String(i)), optionLabels: BULLET_GLYPHS.map(([, font], i) => `${BULLET_GLYPH_LABELS[i]} (${font})`), sourceActionId: 'onParagraphFormat' },
      { id: 'bulletSymbol', label: 'Bullet Symbols', caption: '其他符号', kind: 'select', options: BULLET_SYMBOLS, sourceActionId: 'onParagraphFormat' },
      { id: 'bulletCustomChar', label: 'Custom Bullet Character', caption: '自定义字符', kind: 'spacing', sourceActionId: 'onParagraphFormat' },
      { id: 'pictureBullet', label: 'Picture Bullet', sourceActionId: 'onParagraphFormat' },
      { id: 'numType', label: 'Numbering Scheme', caption: '编号格式', kind: 'select', options: [...NUMBER_TYPES], optionLabels: ['1. 2. 3.', '1) 2) 3)', 'I. II. III.', 'A. B. C.', 'a) b) c)', 'a. b. c.', 'i. ii. iii.', '① ② ③', '一. 二. 三.'], sourceActionId: 'onParagraphFormat' },
      { id: 'startAt', label: 'Numbering Start', caption: '起始编号', kind: 'spacing', sourceActionId: 'onParagraphFormat' },
      { id: 'bulletHangEmu', label: 'Bullet Hanging Indent', caption: '悬挂缩进', kind: 'select', options: ['171450', '285750', '342900'], optionLabels: ['18 px', '30 px', '36 px'], sourceActionId: 'onParagraphFormat' },
      { id: 'bulletHangPx', label: 'Custom Hanging Indent (px)', caption: '自定义缩进（px）', kind: 'spacing', sourceActionId: 'onParagraphFormat' },
      { id: 'bulletSizePct', label: 'Bullet Size', caption: '符号大小', kind: 'select', options: ['75', '90', '100', '125', '150'], optionLabels: ['75%', '90%', '100%', '125%', '150%'], sourceActionId: 'onParagraphFormat' },
      { id: 'bulletColorPreset', label: 'Bullet Color Palette', caption: '符号颜色', kind: 'select', options: BULLET_COLORS, sourceActionId: 'onParagraphFormat' },
      { id: 'bulletColor', label: 'Custom Bullet Color', caption: '自定义颜色', kind: 'color', sourceActionId: 'onParagraphFormat' },
    ] },
    { label: 'Editing', controls: [{ id: 'findReplace', label: 'Find and Replace', sourceActionId: 'onFindReplace' }] },
    { label: 'Arrange', controls: [
      { id: 'groupObjects', label: 'Group', sourceActionId: 'groupSelected' },
      { id: 'ungroupObjects', label: 'Ungroup', sourceActionId: 'ungroupSelected' },
      { id: 'bringToFront', label: 'Bring to Front', sourceActionId: 'reorderSelected' },
      { id: 'bringForward', label: 'Bring Forward', sourceActionId: 'reorderSelected' },
      { id: 'sendBackward', label: 'Send Backward', sourceActionId: 'reorderSelected' },
      { id: 'sendToBack', label: 'Send to Back', sourceActionId: 'reorderSelected' },
      { id: 'alignLeft', label: 'Align Left', sourceActionId: 'onAlignSelected' },
      { id: 'alignCenter', label: 'Align Center', sourceActionId: 'onAlignSelected' },
      { id: 'alignRight', label: 'Align Right', sourceActionId: 'onAlignSelected' },
      { id: 'alignTop', label: 'Align Top', sourceActionId: 'onAlignSelected' },
      { id: 'alignMiddle', label: 'Align Middle', sourceActionId: 'onAlignSelected' },
      { id: 'alignBottom', label: 'Align Bottom', sourceActionId: 'onAlignSelected' },
      { id: 'distributeHorizontal', label: 'Distribute Horizontally', sourceActionId: 'onAlignSelected' },
      { id: 'distributeVertical', label: 'Distribute Vertically', sourceActionId: 'onAlignSelected' },
      { id: 'addText', label: 'Text Box', icon: Plus }, { id: 'addWatermark', label: 'Watermark' }, { id: 'deleteObject', label: 'Delete Object', icon: Trash2 },
    ] },
  ] },
  { id: 'insert', label: 'Insert', groups: [
    { label: 'Slides', controls: [{ id: 'addSlide', label: 'New Slide', sourceIcon: IconNewSlide, sourceActionId: 'onAddSlide' }] },
    { label: 'Tables', controls: [{ id: 'insertTable', label: 'Table', sourceIcon: IconTable, sourceActionId: 'onInsertTable' }] },
    { label: 'Images', controls: [{ id: 'insertPicture', label: 'Pictures', sourceIcon: IconPicture, sourceActionId: 'onInsertImage' }] },
    { label: 'Illustrations', controls: [
      { id: 'insertShape', label: 'Shapes', sourceActionId: 'onPickShape' },
      { id: 'insertSmartArt', label: 'SmartArt', kind: 'select', sourceIcon: IconSmartArt, sourceActionId: 'onInsertSmartArt' },
      { id: 'insertChart', label: 'Chart', kind: 'select', sourceIcon: IconChart, sourceActionId: 'onInsertChart' },
    ] },
    { label: 'Text', controls: [
      { id: 'addText', label: 'Text Box', sourceIcon: IconTextBox, sourceActionId: 'onInsert' },
      { id: 'insertWordArt', label: 'WordArt', kind: 'select', sourceIcon: IconWordArt, sourceActionId: 'onInsertWordArt' },
      { id: 'headerFooter', label: 'Header and Footer', sourceIcon: IconFooter, sourceActionId: 'onOpenHeaderFooter' },
      { id: 'dateTime', label: 'Date and Time', sourceIcon: IconDateTime, sourceActionId: 'onInsertField:datetime' },
      { id: 'slideNumber', label: 'Slide Number', sourceIcon: IconPageNumber, sourceActionId: 'onInsertField:slidenum' },
      { id: 'insertLink', label: 'Link', sourceActionId: 'onOpenLink' },
    ] },
    { label: 'Zoom', controls: [{id:'slideZoom',label:'幻灯片缩放定位',sourceActionId:'onZoom:slide'}, {id:'sectionZoom',label:'节缩放定位',sourceActionId:'onZoom:section'}, {id:'summaryZoom',label:'摘要缩放定位',unavailable:'摘要模式尚缺少新页、占位符和分节原子写入协议'}] },
    { label: 'Symbols', controls: [{ id: 'insertEquation', label: 'Equation', sourceIcon: IconEquation, sourceActionId: 'onOpenEquation' }] },
    { label: 'Media', controls: [
      { id: 'insertAudio', label: 'Audio', sourceActionId: 'onInsertMedia:audio' },
      { id: 'insertVideo', label: 'Video', sourceActionId: 'onInsertMedia:video' },
      { id: 'screenRecording', label: '屏幕录制', sourceIcon: IconScreenRec, sourceActionId: 'onToggleScreenRecord' },
      { id: 'insertModel3d', label: '3D Model', sourceActionId:'onInsertModel3d' },
    ] },
  ] },
  { id: 'draw', label: 'Draw', groups: [] }, // 完整固定源 DrawTab 由 editing ink 宿主挂载。
  { id: 'design', label: 'Design', groups: [
    { label: 'Themes', controls: [{ id: 'theme', label: 'Theme', kind: 'select', options: ['executive', 'clinical', 'modern'] }] },
    { label: 'Customize', controls: [
      { id: 'background', label: 'Background Color', kind: 'color' },
      { id: 'layout', label: 'Slide Layout', kind: 'select' },
      { id: 'slideSize', label: 'Slide Size', kind: 'select', sourceActionId: 'onSlideSize', options: ['16:9', '4:3', 'A4', 'A3'] },
      { id: 'customSlideSize', label: 'Custom Slide Size', sourceActionId: 'onCustomSlideSize' },
      { id: 'defaultSlideSize', label: 'Use for New Presentations', sourceActionId: 'saveDefaultNewSlideSize', unavailable: '当前仅支持上传和编辑演示文稿，尚无新建空白演示文稿入口。' },
      { id: 'slideOrientation', label: 'Slide Orientation', kind: 'select', sourceActionId: 'onSlideSize', options: ['landscape', 'portrait'] },
      { id: 'backgroundImage', label: 'Background Image', sourceActionId: 'onBackground' },
      { id: 'formatBackground', label: 'Format Background', sourceActionId: 'onFormatBackground' },
    ] },
  ] },
  { id: 'transitions', label: 'Transitions', groups: [
    { label: 'Transition to This Slide', controls: [] },
    { label: 'Timing', controls: [{ id: 'applyTransitionAll', label: 'Apply to All', sourceIcon: IconApplyAll, sourceActionId: 'onTransition' }] },
  ] },
  { id: 'animations', label: 'Animations', groups: [
    { label: 'Preview', controls: [{ id: 'animationPreview', label: 'Preview', sourceActionId: 'onAnimPreview' }] },
    { label: 'Animation', controls: [
      { id: 'animationNone', label: 'None', sourceActionId: 'onApplyAnimation' },
    ] },
    { label: 'Motion Paths', controls: [
      { id: 'motionPathRight', label: 'Line Right', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathDown', label: 'Line Down', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathDiagonal', label: 'Diagonal', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathCircle', label: 'Circle', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathZigzag', label: 'Zigzag', sourceActionId: 'onApplyMotionPath' },
    ] },
    { label: 'Advanced Animation', controls: [
      { id: 'animationEffect', label: 'Effect', kind: 'select', sourceActionId: 'onAddAnimation', options: animationCards.map(([kind]) => kind) },
      { id: 'animationDirection', label: 'Direction', kind: 'select', options: ['top', 'bottom', 'left', 'right'] },
      { id: 'addAnimation', label: 'Add Animation', sourceActionId: 'onAddAnimation' },
      { id: 'toggleAnimationPane', label: 'Animation Pane', sourceActionId: 'onToggleAnimPane' },
      { id: 'animationByParagraph', label: 'By Paragraph', sourceActionId: 'onToggleAnimByParagraph' },
    ] },
    { label: 'Timing', controls: [
      { id: 'animationTrigger', label: 'Trigger', kind: 'select', sourceActionId: 'onAnimTiming', options: ['onClick', 'withPrev', 'afterPrev'] },
      { id: 'animationDuration', label: 'Duration (ms)', kind: 'number', sourceActionId: 'onAnimTiming' },
      { id: 'animationDelay', label: 'Delay (ms)', kind: 'number', sourceActionId: 'onAnimTiming' },
    ] },
  ] },
  { id: 'slideShow', label: 'Slide Show', groups: [
    { label: 'Start Slide Show', controls: [{ id: 'startShow', label: 'From Beginning', sourceIcon: IconPlayFromStart, sourceActionId: 'onSlideShow' }, { id: 'startShowCurrent', label: 'From Current Slide', sourceActionId: 'onSlideShow' }, { id: 'presenter', label: 'Presenter View', sourceActionId: 'onPresenterView' }] },
    { label: 'Set Up', controls: [{ id:'customShows',label:'自定义放映',sourceActionId:'onCustomShows' }, { id: 'rehearse', label: 'Rehearse Timings', sourceActionId: 'onRehearse' }, { id: 'record', label: 'Record', unavailable: desktop('屏幕/旁白录制') }, { id: 'hideSlide', label: 'Hide Slide', kind: 'toggle' }] },
  ] },
  { id: 'review', label: 'Review', groups: [
    { label: 'Comments', controls: [
      { id: 'newComment', label: 'New Comment', sourceIcon: IconComment, sourceActionId: 'onNewComment' },
      { id: 'commentsPane', label: 'Comments Pane', kind: 'toggle', sourceIcon: IconNavPane, sourceActionId: 'onToggleComments' },
    ] },
    { label: 'Proofing', controls: [{ id: 'spelling', label: 'Spelling', sourceActionId: 'onAiPreset' }, { id: 'translate', label: 'Translate', kind: 'select', sourceActionId: 'onAiPreset', options: SLIDES_AI_TRANSLATE_TARGETS.map(item => item.id), optionLabels: SLIDES_AI_TRANSLATE_TARGETS.map(item => item.label) }] },
  ] },
  { id: 'view', label: 'View', groups: [
    { label: 'Presentation Views', controls: [
      { id: 'normalView', label: 'Normal', kind: 'toggle', sourceIcon: IconPrintLayout, sourceActionId: 'onViewMode' },
      { id: 'outlineView', label: 'Outline View', kind: 'toggle', sourceIcon: IconOutlineView, sourceActionId: 'onViewMode' },
      { id: 'slideSorter', label: 'Slide Sorter', kind: 'toggle', sourceIcon: IconArrangeAll, sourceActionId: 'onViewMode' },
      { id: 'readingView', label: 'Reading View', kind: 'toggle', sourceIcon: IconReadMode, sourceActionId: 'onViewMode' },
      { id: 'slideMaster', label: 'Slide Master', sourceIcon: IconSlideMaster, sourceActionId: 'onSlideMaster' },
    ] },
    { label: 'Show', controls: [{ id: 'ruler', label: 'Ruler', kind: 'toggle', sourceActionId: 'onToggleRuler' }, { id: 'grid', label: 'Gridlines', kind: 'toggle', sourceActionId: 'onToggleGrid' }, { id: 'guides', label: 'Guides', kind: 'toggle', sourceActionId: 'onToggleGuides' }, { id: 'notes', label: 'Notes', kind:'toggle', sourceActionId:'onToggleNotes' }, { id: 'thumbnailPane', label: 'Thumbnail Pane', kind: 'toggle', sourceIcon: IconNavPane, sourceActionId: 'onToggleThumbs' }] },
    { label: 'Zoom', controls: [
      { id: 'viewZoomIn', label: 'Zoom In', sourceIcon: IconZoomIn, sourceActionId: 'onZoom' },
      { id: 'viewZoomOut', label: 'Zoom Out', sourceIcon: IconZoomOut, sourceActionId: 'onZoom' },
      { id: 'viewZoom100', label: '100%', sourceIcon: IconZoom100, sourceActionId: 'onZoom' },
      { id: 'viewZoomFit', label: 'Fit to Window', sourceIcon: IconFitWindow, sourceActionId: 'onZoomFit' },
    ] },
  ] },
  { id: 'tableDesign', label: 'Table Design', context: 'table', groups: [
    { label: 'Table Styles', controls: [] },
    { label: 'Table Style Options', controls: [
      { id: 'tableFirstRow', label: '标题行', kind: 'toggle', sourceActionId: 'onEditTableStyle' },
      { id: 'tableBandRow', label: '斑马纹', kind: 'toggle', sourceActionId: 'onEditTableStyle' },
      { id: 'tableRtl', label: '从右到左表格', kind: 'toggle', sourceActionId: 'onEditTableStyle' },
    ] },
    { label: 'Shading', controls: [
      { id: 'tableShadingWholeTable', label: '底纹作用于整表', sourceActionId: 'onEditTableStyle' },
    ] },
    { label: 'Borders', controls: [
      { id: 'tableAllBorders', label: 'All Borders', caption: '所有边框', sourceActionId: 'onEditTableStyle' },
      { id: 'tableNoBorders', label: 'No Borders', caption: '无边框', sourceActionId: 'onEditTableStyle' },
    ] },
    { label: 'Rows and Columns', controls: [{ id: 'tableStructure', label: 'Rows and Columns', caption: '行列操作', sourceActionId: 'editTableStructure' }] },
  ] },
  { id: 'chartDesign', label: 'Chart Design', context: 'chart', groups: [{ label: 'Chart Elements', controls: [{ id: 'chartElements', label: 'Chart Elements', sourceActionId: 'onEditChart', sourceIcon: IconChart }] }, { label: 'Chart Styles', controls: [{ id: 'chartDesignPresets', label: 'Chart Colors and Styles', sourceActionId: 'onEditChart', sourceIcon: IconChart }, { id: 'chartPointColors', label: 'Chart Point Colors', sourceActionId: 'onEditChart', sourceIcon: IconChart }] }, { label: 'Chart Data', controls: [{ id: 'chartSwitchRowCol', label: 'Switch Row/Column', sourceActionId: 'onEditChart', sourceIcon: IconSwitchRowCol }, { id: 'chartType', label: 'Change Chart Type', sourceActionId: 'onChartType' }, { id: 'chartData', label: 'Edit Data', sourceActionId: 'onChartData' }] }] },
  { id: 'pictureFormat', label: 'Picture Format', context: 'picture', groups: [{ label: 'Adjust', controls: [{ id:'removeBackground',label:'去除背景',sourceActionId:'onPictureCutout' }, { id: 'replacePicture', label: 'Replace Picture', sourceActionId: 'onReplacePicture' }, { id: 'pictureOpacity', label: 'Transparency', sourceActionId: 'onPictureOpacity' }] },
    { label: 'Outline', controls: [
      { id: 'pictureOutlineColor', label: '轮廓颜色', caption: '颜色', kind: 'color', sourceActionId: 'onPictureStroke' },
      { id: 'pictureOutlineWidth', label: 'Outline Weight', options: OUTLINE_WIDTHS, optionLabels: OUTLINE_WIDTHS.map(value => value + ' pt'), sourceActionId: 'onPictureStroke' },
      { id: 'pictureNoOutline', label: 'No Outline', sourceIcon: IconPageBorders, sourceActionId: 'onPictureStroke' },
    ] },
    { label: 'Size', controls: [{ id: 'cropPicture', label: 'Crop', kind: 'toggle', sourceActionId: 'onPictureCrop' }] },
    { label: 'Arrange', controls: [
      { id: 'rotatePictureRight', label: 'Rotate Right 90°', sourceIcon: IconRotateRight, sourceActionId: 'onPictureRotate:90' },
      { id: 'rotatePictureLeft', label: 'Rotate Left 90°', sourceIcon: IconRotateLeft, sourceActionId: 'onPictureRotate:-90' },
      { id: 'flipPictureH', label: 'Flip Horizontal', sourceIcon: IconObjFlipH, sourceActionId: 'onFlip:h' },
      { id: 'flipPictureV', label: 'Flip Vertical', sourceIcon: IconObjFlipV, sourceActionId: 'onFlip:v' },
    ] },
  ] },
  { id: 'shapeFormat', label: 'Shape Format', context: 'shape', groups: [
    { label: 'Shapes', controls: [{ id: 'changeShape', label: 'Change Shape', sourceActionId: 'onChangeShape' }] },
    { label: 'Size', controls: [{ id: 'shapeGeometry', label: 'Position and Size' }] },
    { label: 'Shape Styles', controls: [] },
    { label: 'Fill', controls: [
      { id: 'shapeFill', label: 'Fill', caption: '颜色', kind: 'color', sourceActionId: 'onShapeFill' },
      { id: 'shapeNoFill', label: 'No Fill', sourceActionId: 'onShapeFill' },
    ] },
    { label: 'Outline', controls: [
      { id: 'shapeOutline', label: 'Outline', caption: '颜色', kind: 'color', sourceActionId: 'onPictureStroke' },
      { id: 'shapeOutlineWidth', label: 'Outline Weight', options: OUTLINE_WIDTHS, optionLabels: OUTLINE_WIDTHS.map(value => value + ' pt'), sourceActionId: 'onPictureStroke' },
      { id: 'shapeOutlineDash', label: 'Line Style', options: [...OUTLINE_DASHES], optionLabels: ['Solid Line', 'Dashed Line', 'Dotted Line', 'Dash-Dot Line'], sourceActionId: 'onPictureStroke' },
      { id: 'shapeNoOutline', label: 'No Outline', sourceActionId: 'onPictureStroke' },
    ] },
  ] },
  { id: 'model3dFormat', label: '3D Model', context: 'model3d', groups: [{ label: 'Views', controls: [{ id: 'model3dView', label: '3D View', unavailable: noWrite('3D 视角') }] }] },
]

function createRibbonPopover(trigger: HTMLButtonElement, label: string, beforeOpen: () => void, afterClose?: () => void) {
  const menu = document.createElement('div')
  menu.className = 'slides-ribbon-popover'
  menu.setAttribute('popover', 'manual')
  menu.setAttribute('role', 'dialog')
  menu.setAttribute('aria-label', label)
  menu.hidden = true
  trigger.setAttribute('aria-haspopup', 'dialog')
  trigger.setAttribute('aria-expanded', 'false')
  let dismiss: (() => void) | undefined
  const close = (focus = false) => {
    if (menu.hidden) return
    dismiss?.()
    dismiss = undefined
    menu.hidePopover?.()
    menu.hidden = true
    trigger.setAttribute('aria-expanded', 'false')
    afterClose?.()
    if (focus) trigger.focus()
  }
  const open = () => {
    if (trigger.disabled || !menu.hidden) return
    beforeOpen()
    menu.hidden = false
    menu.showPopover?.()
    trigger.setAttribute('aria-expanded', 'true')
    const anchor = trigger.getBoundingClientRect(), box = menu.getBoundingClientRect()
    menu.style.left = Math.max(8, Math.min(anchor.left, innerWidth - box.width - 8)) + 'px'
    menu.style.top = Math.max(8, Math.min(anchor.bottom + 4, innerHeight - box.height - 8)) + 'px'
    dismiss = installPopoverDismiss(close, { inside: () => [trigger, menu] })
    const first = menu.querySelector<HTMLElement>('[aria-pressed="true"]:not(:disabled)') ?? menu.querySelector<HTMLElement>('input:not(:disabled), button:not(:disabled)')
    first?.focus({ preventScroll: true })
  }
  trigger.onclick = () => menu.hidden ? open() : close()
  trigger.onkeydown = event => {
    if (event.key !== 'ArrowDown' || event.defaultPrevented || event.isComposing) return
    event.preventDefault()
    open()
  }
  menu.onkeydown = event => {
    if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return
    event.preventDefault()
    close(true)
  }
  return { menu, close }
}

export function createSlidesNativeRibbon(host: HTMLElement, options: {
  onAction: NativeSlidesAction
  onAnimationHover?: (effect: string | null) => void
  onAssistant?: () => void
  pdfExportAvailable?: boolean
  saveAsAvailable?: boolean
  openFileAvailable?: boolean
  imageExportAvailable?: boolean
  nameWithAiAvailable?: boolean
  layouts?: NativeSlidesLayout[]
  locked?: boolean
}): NativeSlidesRibbon {
  const root = document.createElement('section')
  root.className = 'slides-native-ribbon ribbon'
  const disposeScroll = bindOfficeRibbonScroll(root)
  root.setAttribute('aria-label', 'PowerPoint 功能区')
  const tablist = document.createElement('div')
  tablist.className = 'slides-native-ribbon-tabs ribbon-tabs'
  tablist.setAttribute('role', 'tablist')
  const panels = new Map<string, HTMLElement>()
  const tabButtons = new Map<string, HTMLButtonElement>()
  const controls = new Map<string, HTMLElement[]>()
  const desktopMenus: Array<() => void> = []
  let activeTab = 'home'
  let activeContext: NativeSlidesContext = null
  let chartGallery: ReturnType<typeof createNativeChartGallery> | undefined
  let closePictureOutline: (() => void) | undefined
  let pictureTransparency: ReturnType<typeof createRibbonPopover> | undefined
  const shapeGalleries = new Map<string, () => void>()
  const closeShapeGalleries = (exceptTab?: string) => {
    for (const [tabId, close] of shapeGalleries) if (tabId !== exceptTab) close()
  }
  const closePictureMenus = () => { closePictureOutline?.(); pictureTransparency?.close() }
  const shapeFormatMenus = new Map<string, () => void>()
  const closeShapeFormatMenus = (except?: string) => {
    for (const [id, close] of shapeFormatMenus) if (id !== except) close()
  }
  let locked = options.locked === true
  let currentAnimationEffect = ''
  let listTargets = { bullets: false, numbers: false, hanging: false }
  let hasTextTarget = false
  let hasWritableSlideSize = false
  const clipboardLocale = genOfficeHomeClipboardLocale(document.documentElement.lang)
  const localize = (label: string) => slidesRibbonLabel(label, document.documentElement.lang)

  let commentEditReady = false, commentEditReason: string | undefined
  let aiEditReady = false, aiEditReason: string | undefined
  const updateAIEdit = () => {
    for (const command of ['spelling', 'translate']) for (const control of controls.get(command) ?? []) {
      ;(control as HTMLButtonElement | HTMLSelectElement).disabled = locked || !aiEditReady
      control.title = aiEditReady ? (command === 'spelling' ? '检查整稿可编辑文字；先生成候选，再明确采纳' : '翻译当前页可编辑文字；先生成候选，再明确采纳') : aiEditReason ?? '当前会话未启用 AI 编辑'
    }
  }
  const updateCommentEdit = () => {
    for (const control of controls.get('newComment') ?? []) {
      ;(control as HTMLButtonElement).disabled = locked || !commentEditReady
      control.title = commentEditReady ? '在当前来源页新建经典批注' : commentEditReason ?? '请先打开已核验的批注来源'
    }
  }
  let transitionEditReady = false
  let transitionEditReason: string | undefined
  const updateTransitionEdit = () => {
    for (const control of controls.get('transition') ?? []) {
      ;(control as HTMLButtonElement).disabled = locked || !transitionEditReady
      control.title = transitionEditReady ? '更改视觉转场效果；保留原速度、换片、声音及扩展设置' : transitionEditReason ?? '请先打开已核验的演示文稿'
    }
  }
  let transitionApplyAllReady = false
  let transitionApplyAllReason: string | undefined
  const updateTransitionApplyAll = () => {
    for (const button of controls.get('applyTransitionAll') ?? []) {
      ;(button as HTMLButtonElement).disabled = locked || !transitionApplyAllReady
      button.title = transitionApplyAllReady ? '将当前页转场效果应用到全部保留页面；各页自动换片时间保留' : transitionApplyAllReason ?? '请先打开可编辑的演示文稿；一次最多支持 500 页'
    }
  }
  let animationTarget: 'shape' | 'media' | null = null
  let appliedAnimation = ''
  let tablePresetReady = false
  let tablePresetReason: string | undefined
  let tableShading: { group: HTMLElement; heading: HTMLElement; palette: HTMLFieldSetElement; enabled: boolean } | undefined
  const updateTablePresetGallery = () => {
    for (const element of controls.get('tableStyle') ?? []) {
      const button = element as HTMLButtonElement
      button.disabled = locked || !tablePresetReady
      button.title = tablePresetReady ? button.textContent ?? '' : tablePresetReason ?? '请选择支持样式编辑的来源表格'
    }
  }
  let animationHoverTimer: number | undefined
  let animationHoveredButton: HTMLButtonElement | undefined
  const animationFlyouts: Array<{ group: HTMLElement; trigger: HTMLButtonElement; close(): void; setCollapsed(value: boolean): void; inlineWidth: number; foldedWidth: number }> = []
  let updateAnimationLayout: (() => void) | undefined
  const cancelAnimationHover = () => {
    if (!animationHoveredButton) return
    window.clearTimeout(animationHoverTimer)
    animationHoverTimer = undefined
    animationHoveredButton = undefined
    options.onAnimationHover?.(null)
  }
  const bindAnimationHover = (button: HTMLButtonElement, effect: string) => {
    if (!options.onAnimationHover) return
    button.addEventListener('mouseenter', () => {
      cancelAnimationHover()
      if (locked || button.disabled || activeTab !== 'animations' || animationTarget !== 'shape') return
      animationHoveredButton = button
      animationHoverTimer = window.setTimeout(() => {
        animationHoverTimer = undefined
        if (animationHoveredButton === button) options.onAnimationHover?.(effect)
      }, 350)
    })
    button.addEventListener('mouseleave', () => {
      if (animationHoveredButton === button) cancelAnimationHover()
    })
    button.addEventListener('pointerdown', cancelAnimationHover)
    button.addEventListener('click', cancelAnimationHover, true)
  }
  const updateAnimationGallery = () => {
    for (const element of controls.get('applyAnimationEffect') ?? []) {
      const button = element as HTMLButtonElement
      const kind = button.dataset.animationEffect!
      button.disabled = locked || !animationTarget || (kind.startsWith('media') !== (animationTarget === 'media'))
      button.setAttribute('aria-pressed', String(kind === appliedAnimation))
    }
    for (const button of controls.get('animationNone') ?? []) (button as HTMLButtonElement).disabled = locked || !animationTarget
  }
  const selectTab = (id: string) => {
    desktopMenus.forEach(close => close())
    if (id !== 'animations') {
      cancelAnimationHover()
      for (const flyout of animationFlyouts) flyout.close()
    }
    if (id !== 'chartDesign') chartGallery?.close()
    if (id !== 'pictureFormat') closePictureMenus()
    if (id !== 'shapeFormat') closeShapeFormatMenus()
    closeShapeGalleries(id)
    activeTab = id
    for (const tab of tabs) {
      const selected = tab.id === id
      const button = tabButtons.get(tab.id)!
      button.setAttribute('aria-selected', String(selected))
      button.classList.toggle('active', selected)
      button.tabIndex = selected ? 0 : -1
      panels.get(tab.id)!.hidden = !selected
    }
    if (id === 'animations') updateAnimationLayout?.()
  }
  for (const tab of tabs) {
    const button = document.createElement('button')
    button.type = 'button'
    button.id = `slides-native-tab-${tab.id}`
    button.dataset.ribbonTab = tab.id
    button.className = 'ribbon-tab' + (tab.id === activeTab ? ' active' : '')
    button.textContent = localize(tab.label)
    button.setAttribute('role', 'tab')
    button.setAttribute('aria-controls', `slides-native-panel-${tab.id}`)
    button.hidden = !!tab.context
    button.addEventListener('click', () => selectTab(tab.id))
    button.addEventListener('keydown', event => {
      if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
      const visible = tabs.filter(item => {
        const candidate = tabButtons.get(item.id)!
        return !candidate.hidden && !candidate.disabled && (!item.context || item.context === activeContext)
      })
      const index = visible.findIndex(item => item.id === tab.id)
      if (index < 0) return
      const target = event.key === 'ArrowRight' ? visible[(index + 1) % visible.length]
        : event.key === 'ArrowLeft' ? visible[(index - 1 + visible.length) % visible.length]
          : event.key === 'Home' ? visible[0] : event.key === 'End' ? visible.at(-1) : undefined
      if (!target) return
      event.preventDefault()
      selectTab(target.id)
      tabButtons.get(target.id)!.focus()
    })
    tablist.append(button)
    tabButtons.set(tab.id, button)

    const panel = document.createElement('div')
    panel.id = `slides-native-panel-${tab.id}`
    panel.dataset.ribbonPanel = tab.id
    panel.className = 'ribbon-body'
    panel.setAttribute('role', 'tabpanel')
    panel.setAttribute('aria-labelledby', button.id)
    panel.hidden = tab.id !== activeTab || !!tab.context
    for (const groupDefinition of tab.groups) {
      const group = document.createElement('section')
      group.className = 'slides-native-ribbon-group ribbon-group'
      group.dataset.ribbonGroup = groupDefinition.label
      const groupLabel = tab.id === 'home' && groupDefinition.label === 'Clipboard' ? clipboardLocale.group : localize(groupDefinition.label)
      group.setAttribute('aria-label', groupLabel)
      const heading = document.createElement('h2')
      heading.textContent = groupLabel
      heading.className = 'ribbon-group-label'
      const groupItems = document.createElement('div')
      groupItems.className = 'ribbon-group-items'
      group.append(groupItems, heading)
      let controlHost: HTMLElement = groupItems
      if (tab.id === 'tableDesign' && groupDefinition.label === 'Shading') {
        const palette = document.createElement('fieldset')
        palette.className = 'slides-table-shading'
        palette.dataset.command = 'tableShading'
        palette.disabled = true
        palette.setAttribute('aria-label', groupLabel)
        for (const color of [...TABLE_SHADING_COLORS, 'none']) {
          const swatch = document.createElement('button')
          swatch.type = 'button'
          swatch.dataset.tableShadingColor = color
          swatch.dataset.sourceAction = 'onEditTableStyle'
          const label = color === 'none' ? localize('No Shading') : color
          swatch.title = label
          swatch.setAttribute('aria-label', label)
          swatch.setAttribute('aria-pressed', 'false')
          if (color === 'none') swatch.innerHTML = renderToStaticMarkup(reactElement(IconNoneX, { size: 12 }))
          else swatch.style.backgroundColor = color
          swatch.addEventListener('mousedown', event => event.preventDefault())
          swatch.addEventListener('click', () => {
            if (!palette.disabled) options.onAction('tableShading', color)
          })
          palette.append(swatch)
        }
        groupItems.append(palette)
        tableShading = { group, heading, palette, enabled: false }
      }
      if (tab.id === 'tableDesign' && groupDefinition.label === 'Table Styles') {
        group.classList.add('slides-table-style-gallery')
        controls.set('tableStyle', SLIDES_TABLE_PRESETS.map(preset => {
          const button = document.createElement('button')
          button.type = 'button'
          button.dataset.command = 'tableStyle'
          button.dataset.tableStylePreset = preset.name
          button.dataset.sourceAction = 'onEditTableStyle'
          button.setAttribute('aria-pressed', 'false')
          button.innerHTML = renderToStaticMarkup(reactElement(TableMiniPreview, preset.preview))
          const label = document.createElement('span')
          label.textContent = document.documentElement.lang.toLowerCase().startsWith('zh') ? preset.label : preset.english
          button.append(label)
          button.addEventListener('click', () => {
            if (!button.disabled) options.onAction('tableStyle', preset.name)
          })
          groupItems.append(button)
          return button
        }))
      }
      if (tab.id === 'transitions' && groupDefinition.label === 'Transition to This Slide') {
        group.classList.add('slides-transition-gallery')
        controls.set('transition', SLIDE_TRANSITIONS.map(kind => {
          const [english, icon] = transitionCards[kind]
          const translated = localize(kind)
          const button = document.createElement('button')
          button.type = 'button'
          button.dataset.command = 'transition'
          button.dataset.sourceAction = 'onTransition'
          button.dataset.transitionEffect = kind
          button.setAttribute('aria-pressed', 'false')
          button.innerHTML = renderToStaticMarkup(reactElement(icon, { size: 24 }))
          button.append(document.createTextNode(translated === kind ? english : translated))
          button.addEventListener('click', () => {
            if (!locked && transitionEditReady) options.onAction('transition', kind)
          })
          groupItems.append(button)
          return button
        }))
      }
      const pictureOutline = tab.id === 'pictureFormat' && groupDefinition.label === 'Outline'
      const shapeFill = tab.id === 'shapeFormat' && groupDefinition.label === 'Fill'
      const shapeOutline = tab.id === 'shapeFormat' && groupDefinition.label === 'Outline'
      const shapeStyle = tab.id === 'shapeFormat' && groupDefinition.label === 'Shape Styles'
      if (pictureOutline || shapeFill || shapeOutline || shapeStyle) {
        const trigger = document.createElement('button')
        trigger.type = 'button'
        trigger.disabled = locked || pictureOutline
        const id = pictureOutline ? 'pictureOutlineMenu' : shapeFill ? 'shapeFillMenu' : shapeStyle ? 'shapeStyleMenu' : 'shapeOutlineMenu'
        trigger.dataset.command = id
        trigger.dataset.sourceAction = shapeFill ? 'onShapeFill' : shapeStyle ? 'onShapeStyle' : 'onPictureStroke'
        trigger.innerHTML = renderToStaticMarkup(reactElement(shapeFill ? IconFillColor : shapeStyle ? IconShapeStyle : IconPageBorders, { size: 15 }))
        trigger.append(document.createTextNode(groupLabel + ' ▾'))
        controls.set(id, [trigger])
        let updateGradients: (() => void) | undefined
        const { menu, close } = createRibbonPopover(trigger, groupLabel, () => {
          if (pictureOutline) pictureTransparency?.close()
          else {
            closeShapeFormatMenus(id)
            closeShapeGalleries()
          }
          updateGradients?.()
        })
        groupItems.append(trigger, menu)
        controlHost = menu
        if (shapeStyle) {
          const grid = document.createElement('div')
          grid.className = 'slides-shape-style-grid'
          RIBBON_SHAPE_STYLES.forEach((preset, index) => {
            const swatch = document.createElement('button')
            swatch.type = 'button'
            swatch.dataset.shapeStylePreset = String(index)
            swatch.style.backgroundColor = preset.fill
            swatch.style.borderColor = preset.stroke
            swatch.style.borderStyle = preset.dash ? 'dashed' : 'solid'
            swatch.setAttribute('aria-label', preset.fill + ' / ' + preset.stroke + (preset.dash ? ' (' + preset.dash + ')' : ''))
            swatch.setAttribute('aria-pressed', 'false')
            swatch.addEventListener('click', () => {
              if (trigger.disabled || menu.hidden || swatch.disabled) return
              close(true)
              options.onAction('shapeStylePreset', index)
            })
            grid.append(swatch)
          })
          menu.append(grid)
        }
        if (shapeFill) {
          const appendSwatches = (colors: readonly { hex: string; name: string }[]) => {
            const grid = document.createElement('div')
            grid.className = 'slides-fill-swatches'
            for (const { hex, name } of colors) {
              const button = document.createElement('button')
              const color = '#' + hex
              button.type = 'button'
              button.dataset.shapeFillSwatch = color
              button.title = name
              button.setAttribute('aria-label', name === color ? color : name + ' ' + color)
              button.setAttribute('aria-pressed', 'false')
              button.style.backgroundColor = color
              button.onclick = () => {
                if (trigger.disabled || menu.hidden) return
                close(true)
                options.onAction('shapeFill', color)
              }
              grid.append(button)
            }
            menu.append(grid)
          }
          const addHeading = (label: string) => {
            const heading = document.createElement('div')
            heading.textContent = localize(label)
            menu.append(heading)
          }
          addHeading('Theme Colors')
          appendSwatches(THEME_COLORS)
          appendSwatches(THEME_COLOR_SHADES.flat().map(hex => ({ hex, name: '#' + hex })))
          addHeading('Standard Colors')
          appendSwatches(STANDARD_COLORS)
          const gradients = createShapeGradientPresets(localize, value => {
            if (trigger.disabled || menu.hidden) return
            close(true)
            if (typeof value === 'string') options.onAction('shapeFill', value)
            else options.onAction('shapeFillGradient', value)
          })
          menu.append(gradients.details)
          updateGradients = () => {
            gradients.details.open = false
            const color = menu.querySelector<HTMLInputElement>('[data-command="shapeFill"]')?.dataset.gradientBase
            gradients.render(color || '#4472C4')
          }
        }
        if (pictureOutline) closePictureOutline = close
        else shapeFormatMenus.set(id, close)
        menu.addEventListener('click', event => {
          if (event.target instanceof Element && event.target.closest('[data-outline-width], [data-outline-dash], [data-command="pictureNoOutline"], [data-command="shapeNoFill"], [data-command="shapeNoOutline"]')) close(true)
        })
      }
      if (groupDefinition.label === 'AI 助手') {
        group.classList.add('office-ai-group')
        groupItems.append(createOfficeAIEntry(options.onAssistant))
      }
      for (const control of groupDefinition.controls) {
        const localizedLabel = tab.id === 'home' && groupDefinition.label === 'Clipboard'
          ? clipboardLocale[(control.id === 'formatBrush' ? 'formatPainter' : control.id) as keyof typeof clipboardLocale] as string
          : localize(control.label)
        const unavailable = control.id === 'exportPdf' && !options.pdfExportAvailable ? '当前会话未开放 PDF 导出。'
          : control.id === 'saveAs' && !options.saveAsAvailable ? '当前会话未开放另存为。'
          : (control.id === 'exportImages' || control.id === 'exportImagesJpg') && !options.imageExportAvailable ? '当前会话未开放图片导出。'
          : control.id === 'nameWithAi' && !options.nameWithAiAvailable ? '当前会话未开放 AI 命名。'
          : control.id === 'openFile' && !options.openFileAvailable ? '当前会话未开放文件导入。' : control.unavailable
        const controlId = `slides-native-command-${tab.id}-${control.id}`
        const sourceGlyph = control.sourceIcon ?? slidesRibbonSourceIcons[control.id]
        const glyph = control.icon ?? slidesRibbonIcons[control.id]
        const sourceIcon = sourceGlyph
          ? renderToStaticMarkup(reactElement(sourceGlyph, { size: 15 }))
          : ''
        let element: HTMLElement
        if (unavailable) {
          const buttonElement = document.createElement('button')
          buttonElement.type = 'button'
          buttonElement.disabled = true
          buttonElement.title = unavailable
          buttonElement.setAttribute('aria-label', `${localizedLabel}. ${unavailable}`)
          if (sourceIcon) buttonElement.insertAdjacentHTML('afterbegin', sourceIcon)
          else if (glyph) buttonElement.append(createElement(glyph, { width: 15, height: 15, 'aria-hidden': 'true' }))
          buttonElement.append(document.createTextNode(localizedLabel))
          buttonElement.dataset.command = control.id
          buttonElement.dataset.unavailable = 'true'
          element = buttonElement
        } else if (control.id === 'pictureOpacity') {
          const trigger = document.createElement('button')
          trigger.type = 'button'
          trigger.dataset.command = control.id
          trigger.disabled = true
          const icon = new Image(22, 22)
          icon.src = iconTransparency
          icon.alt = ''
          trigger.append(icon, localizedLabel + ' ▾')
          const { menu, close } = createRibbonPopover(trigger, localizedLabel, () => closePictureOutline?.())
          pictureTransparency = { menu, close }
          for (const value of PICTURE_TRANSPARENCY_PRESETS) {
            const choice = document.createElement('button')
            choice.type = 'button'
            choice.textContent = value + '%'
            choice.dataset.pictureTransparency = value
            choice.setAttribute('aria-pressed', 'false')
            choice.onclick = () => {
              if (trigger.disabled || menu.hidden) return
              close(true)
              options.onAction(control.id, value)
            }
            menu.append(choice)
          }
          controlHost.append(trigger, menu)
          element = trigger
        } else if (control.id === 'changeShape' || control.id === 'insertShape') {
          const trigger = document.createElement('button')
          trigger.type = 'button'
          trigger.dataset.command = control.id
          trigger.innerHTML = renderToStaticMarkup(reactElement(IconShapes, { size: 18 }))
          trigger.append(localizedLabel + ' ▾')
          const { menu, close } = createRibbonPopover(trigger, localizedLabel, () => {
            closeShapeFormatMenus()
            if (menu.hasChildNodes()) return
            for (const category of SHAPE_GALLERY_GROUPS) {
              const shapes = control.id === 'insertShape'
                ? category.shapes
                : category.shapes.filter(shape => !LINE_SHAPE_KINDS.includes(shape.prst))
              if (!shapes.length) continue
              const title = document.createElement('div'), grid = document.createElement('div')
              title.textContent = category.group
              grid.className = 'slides-shape-gallery-grid'
              for (const shape of shapes) {
                const choice = document.createElement('button')
                choice.type = 'button'
                choice.dataset.prst = shape.prst
                choice.title = shape.label
                choice.setAttribute('aria-label', shape.label)
                choice.innerHTML = renderToStaticMarkup(reactElement(ShapePreview, { prst: shape.prst, size: 18 }))
                choice.onclick = () => {
                  if (trigger.disabled || menu.hidden) return
                  close(true)
                  options.onAction(control.id, shape.prst)
                }
                grid.append(choice)
              }
              menu.append(title, grid)
            }
          })
          menu.classList.add('slides-shape-gallery')
          shapeGalleries.set(tab.id, close)
          controlHost.append(trigger, menu)
          element = trigger
        } else if (control.id === 'pictureOutlineWidth' || control.id === 'shapeOutlineWidth' || control.id === 'shapeOutlineDash') {
          const presets = document.createElement('fieldset')
          presets.dataset.command = control.id
          const selectionKey = control.id === 'shapeOutlineDash' ? 'outlineDash' : 'outlineWidth'
          const legend = document.createElement('legend')
          legend.textContent = localizedLabel
          presets.append(legend)
          for (const [index, value] of (control.options ?? []).entries()) {
            const button = document.createElement('button')
            button.type = 'button'
            button.dataset[selectionKey] = value
            button.textContent = localize(control.optionLabels?.[index] ?? value)
            button.setAttribute('aria-pressed', 'false')
            button.onclick = () => options.onAction(control.id, value)
            presets.append(button)
          }
          element = presets
        } else if (control.kind === 'select') {
          const select = document.createElement('select')
          select.setAttribute('aria-label', localizedLabel)
          select.dataset.command = control.id
          if (control.id === 'translate') select.add(new Option(localize('Choose translation language…'), ''))
          if (control.id === 'lineSpacingPct' || PARAGRAPH_LIST_COMMANDS.includes(control.id)) select.add(new Option('未设置或混合值', ''))
          if (control.id === 'insertSmartArt') {
            // 固定源 SMARTART_GALLERY：7 种布局
            select.add(new Option('插入 SmartArt…', ''))
            for (const item of SMARTART_GALLERY) select.add(new Option(item.label, item.layout))
          } else if (control.id === 'insertChart') {
            // 固定源 CHART_GALLERY：13 种图表，顺序与名称同固定源。
            select.add(new Option('插入图表…', ''))
            for (const item of CHART_GALLERY) select.add(new Option(item.label, item.kind))
          } else if (control.id === 'insertWordArt') {
            // 固定源共享艺术字库：12 个预设，顺序与名称同固定源。
            select.add(new Option('插入艺术字…', ''))
            for (const preset of WORDART_PRESETS) select.add(new Option(WORDART_PRESET_LABELS[preset.id] ?? preset.id, preset.id))
          } else if (control.id === 'layout' || control.id === 'addSlideWithLayout') {
            if (control.id === 'addSlideWithLayout') select.add(new Option('新建指定版式幻灯片…', ''))
            for (const layout of options.layouts ?? []) select.add(new Option(slidesLayoutLabel(layout, document.documentElement.lang), layout.path))
          } else {
            for (const [index, value] of (control.options ?? []).entries()) select.add(new Option(localize(control.optionLabels?.[index] ?? (control.id === 'lineSpacingPct' ? `${Number(value) / 100} 倍` : value)), value))
          }
          select.addEventListener('change', () => { if (control.id === 'translate' && (!aiEditReady || locked || !select.value)) return; options.onAction(control.id, select.value); if (['translate', 'addSlideWithLayout', 'insertWordArt', 'insertChart', 'insertSmartArt'].includes(control.id)) select.value = '' })
          element = select
        } else if (control.kind === 'font' || control.kind === 'number' || control.kind === 'color' || control.kind === 'spacing') {
          const input = document.createElement('input')
          input.type = control.kind === 'font' || control.kind === 'spacing' ? 'text' : control.kind
          input.setAttribute('aria-label', localizedLabel)
          input.dataset.command = control.id
          if (control.kind === 'spacing') {
            input.setAttribute('inputmode', 'decimal')
            input.addEventListener('keydown', event => {
              if ((event as KeyboardEvent).key === 'Enter') { event.preventDefault(); options.onAction(control.id, input.value) }
            })
          } else input.addEventListener('change', () => options.onAction(control.id, input.value))
          element = input
        } else {
          const buttonElement = document.createElement('button')
          buttonElement.type = 'button'
          buttonElement.setAttribute('aria-label', localizedLabel)
          if (control.id === 'cropPicture') {
            const icon = new Image(22, 22)
            icon.src = iconCrop
            icon.alt = ''
            buttonElement.append(icon)
          } else if (sourceIcon) buttonElement.insertAdjacentHTML('afterbegin', sourceIcon)
          else if (glyph) buttonElement.append(createElement(glyph, { width: 15, height: 15, 'aria-hidden': 'true' }))
          if (control.kind === 'toggle') {
            buttonElement.title = localizedLabel
            const label = document.createElement('span')
            label.className = 'slides-ribbon-toggle-label'
            label.textContent = localizedLabel
            buttonElement.append(label)
          } else buttonElement.append(document.createTextNode(localizedLabel))
          buttonElement.dataset.command = control.id
          if (control.kind === 'toggle') {
            buttonElement.setAttribute('aria-pressed', 'false')
            buttonElement.addEventListener('click', () => options.onAction(control.id, buttonElement.getAttribute('aria-pressed') !== 'true'))
          } else {
            buttonElement.addEventListener('click', () => options.onAction(control.id))
            if (control.id === 'formatBrush') buttonElement.addEventListener('dblclick', () => options.onAction(control.id, 'continuous'))
          }
          element = buttonElement
        }
        if (unavailable) {
          element.id = controlId
        } else {
          element.id = controlId
          if (locked) (element as HTMLButtonElement).disabled = true
        }
        if (control.sourceActionId) element.dataset.sourceAction = control.sourceActionId
        if (element instanceof HTMLButtonElement && Object.hasOwn(MOTION_PATHS, control.id)) bindAnimationHover(element, control.id)
        if (!element.title) element.title = localizedLabel
        if (control.id === 'openFile' && !unavailable) element.setAttribute('aria-keyshortcuts', 'Control+O Meta+O')
        if (control.id === 'saveAs' && !unavailable) element.setAttribute('aria-keyshortcuts', 'Control+Shift+S Meta+Shift+S')
        if (control.id === 'saveRevision') element.setAttribute('aria-keyshortcuts', 'Control+S Meta+S')
        if (control.id === 'print') element.setAttribute('aria-keyshortcuts', 'Control+P Meta+P')
        if (PARAGRAPH_LIST_COMMANDS.includes(control.id)) element.title = localizedLabel + '：作用于当前对象的全部段落；自定义输入 Enter 提交'
        controls.set(control.id, [...(controls.get(control.id) ?? []), element])
        if (control.id === 'pictureOpacity' || control.id === 'changeShape' || control.id === 'insertShape') continue
        if (control.caption || ['translate', 'lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt'].includes(control.id)) {
          const label = document.createElement('label')
          label.htmlFor = controlId
          label.className = 'slides-ribbon-field'
          if (control.id === 'translate' && sourceIcon) label.insertAdjacentHTML('beforeend', sourceIcon)
          label.append(document.createTextNode(control.caption ?? (control.id === 'translate' ? localizedLabel : control.id === 'lineSpacingPct' ? '行距' : control.id === 'spaceBeforePt' ? '段前（磅）' : '段后（磅）')), element)
          if (control.id === 'bulletColor') {
            const status = document.createElement('span')
            status.className = 'bullet-color-state'
            label.append(status)
          }
          controlHost.append(label)
        } else if (control.id === 'shapeNoFill') controlHost.prepend(element)
        else controlHost.append(element)
      }
      if (tab.id === 'animations' && groupDefinition.label === 'Animation') {
        group.classList.add('slides-effect-gallery')
        controls.set('applyAnimationEffect', animationCards.map(([kind, label]) => {
          const button = document.createElement('button')
          button.type = 'button'
          button.dataset.command = 'applyAnimationEffect'
          button.dataset.sourceAction = 'onApplyAnimation'
          button.dataset.animationEffect = kind
          if (!kind.startsWith('media')) bindAnimationHover(button, kind)
          button.innerHTML = renderToStaticMarkup(reactElement(AnimEffectIcon, { kind, size: 24 }))
          button.append(document.createTextNode(document.documentElement.lang.toLowerCase().startsWith('zh')
            ? animationCardChineseLabels[kind] ?? EFFECT_LABELS[kind] ?? label : label))
          button.addEventListener('click', () => {
            if (!button.disabled) options.onAction('applyAnimationEffect', kind)
          })
          groupItems.append(button)
          return button
        }))
      }
      if (tab.id === 'animations' && ['Animation', 'Motion Paths'].includes(groupDefinition.label)) {
        const animation = groupDefinition.label === 'Animation'
        const items = [...groupItems.children]
        const trigger = document.createElement('button')
        trigger.type = 'button'
        trigger.dataset.animationCollapse = animation ? 'animation' : 'motionPaths'
        trigger.disabled = locked
        trigger.hidden = true
        trigger.innerHTML = renderToStaticMarkup(reactElement(animation ? IconAnimStar : IconPathDiagonal, { size: 24 }))
        trigger.append(document.createTextNode(groupLabel + ' ▾'))
        const { menu, close } = createRibbonPopover(trigger, groupLabel, () => {
          for (const flyout of animationFlyouts) if (flyout.trigger !== trigger) flyout.close()
        }, cancelAnimationHover)
        menu.classList.add('slides-animation-collapsed-flyout')
        groupItems.append(trigger, menu)
        const flyout: typeof animationFlyouts[number] = { group, trigger, close, inlineWidth: 0, foldedWidth: 88, setCollapsed(value) {
          if (value === !trigger.hidden) return
          const focused = document.activeElement
          const restore = items.find(item => item === focused || item.contains(focused))
          cancelAnimationHover()
          close()
          trigger.hidden = !value
          if (value) menu.append(...items)
          else for (const item of items) groupItems.insertBefore(item, trigger)
          if (value && restore) trigger.focus({ preventScroll: true })
          else if (!value && (restore || focused === trigger)) {
            const target = restore ?? items.find(item => item instanceof HTMLButtonElement && !item.disabled)
            if (target instanceof HTMLElement) target.focus({ preventScroll: true })
          }
        } }
        // Source collapse priority is Motion Paths before Animation.
        if (animation) animationFlyouts.push(flyout)
        else animationFlyouts.unshift(flyout)
      }
      if (tab.id === 'chartDesign' && groupDefinition.label === 'Chart Styles') {
        chartGallery = createNativeChartGallery(groupItems, (command, value) => options.onAction(command, value))
        chartGallery.setLocked(locked)
      }
      desktopRibbonGroup(group, groupItems, tab.id, groupDefinition.label)
      if (tab.id === 'home' && groupDefinition.label === 'Paragraph') {
        const trigger = document.createElement('button')
        trigger.type = 'button'
        trigger.setAttribute('aria-label', groupLabel)
        trigger.innerHTML = renderToStaticMarkup(reactElement(IconAlignLeft, { size: 28 }))
        trigger.append(document.createTextNode(groupLabel))
        desktopRibbonButton(trigger)
        const { menu, close } = createRibbonPopover(trigger, groupLabel, () => desktopMenus.forEach(close => close()))
        menu.classList.add('rb-para-drop')
        menu.append(...groupItems.childNodes)
        groupItems.append(trigger, menu)
        desktopMenus.push(close)
      }
      if (panel.children.length) {
        const separator = document.createElement('div')
        separator.className = 'ribbon-sep'
        separator.setAttribute('aria-hidden', 'true')
        panel.append(separator)
      }
      panel.append(group)
    }
    panels.set(tab.id, panel)
    root.append(panel)
  }
  root.prepend(tablist)
  host.prepend(root)
  const animationPanel = panels.get('animations')!
  // Fixed source Ribbon.tsx COLLAPSE_ORDER and fitCount with 8px unfolding hysteresis.
  updateAnimationLayout = () => {
    if (animationPanel.hidden || !animationPanel.clientWidth) return
    const style = getComputedStyle(animationPanel)
    const available = animationPanel.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0)
    let fullWidth = [...animationPanel.children].reduce((width, group) => {
      const margins = getComputedStyle(group)
      return width + (group as HTMLElement).offsetWidth + (parseFloat(margins.marginLeft) || 0) + (parseFloat(margins.marginRight) || 0)
    }, 0)
    const savings = animationFlyouts.map(flyout => {
      if (flyout.trigger.hidden) flyout.inlineWidth = flyout.group.offsetWidth
      else flyout.foldedWidth = flyout.group.offsetWidth
      const saving = Math.max(0, flyout.inlineWidth - flyout.foldedWidth)
      if (!flyout.trigger.hidden) fullWidth += saving
      return saving
    })
    const fitCount = (width: number) => {
      let needed = fullWidth, count = 0
      while (count < savings.length && needed > width) needed -= savings[count++]!
      return count
    }
    const current = animationFlyouts.filter(flyout => !flyout.trigger.hidden).length
    const fit = fitCount(available)
    const next = fit >= current ? fit : Math.min(fitCount(available - 8), current)
    animationFlyouts.forEach((flyout, index) => flyout.setCollapsed(index < next))
  }
  const animationLayoutObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(updateAnimationLayout) : undefined
  animationLayoutObserver?.observe(animationPanel)
  for (const group of animationPanel.children) animationLayoutObserver?.observe(group)
  selectTab(activeTab)
  updateTextFormattingState()
  updateSlideOrientationState()
  updateTransitionApplyAll()
  updateTransitionEdit()
  updateAnimationGallery()
  updateTablePresetGallery()
  updateCommentEdit()
  updateAIEdit()

  return {
    setChartDesign(state) { chartGallery?.setState(state) },
    setContext(context) {
      const focused = document.activeElement
      const restoreFocus = tabs.some(tab => tab.context && tab.context !== context && (
        tabButtons.get(tab.id) === focused || (focused !== null && panels.get(tab.id)!.contains(focused))
      ))
      if (context !== 'chart') chartGallery?.setState(null)
      activeContext = context
      for (const tab of tabs.filter(item => item.context)) {
        const visible = tab.context === context
        tabButtons.get(tab.id)!.hidden = !visible
        panels.get(tab.id)!.hidden = tab.id !== activeTab
      }
      const activeContextTab = tabs.find(tab => tab.id === activeTab && tab.context)
      if (activeContextTab && activeContextTab.context !== context) selectTab('home')
      if (restoreFocus) tabButtons.get(activeTab)!.focus()
      updateTextFormattingState()
    },
    setListTargets(state) {
      listTargets = state
      updateTextFormattingState()
    },
    setTextFormatEnabled(enabled) {
      hasTextTarget = enabled
      updateTextFormattingState()
    },
    setCommentEditEnabled(enabled, reason) { commentEditReady = enabled; commentEditReason = reason; updateCommentEdit() },
    setAIEditEnabled(enabled, reason) { aiEditReady = enabled; aiEditReason = reason; updateAIEdit() },
    setTransitionEditEnabled(enabled, reason) { transitionEditReady = enabled; transitionEditReason = reason; updateTransitionEdit() },
    setTransitionApplyAllEnabled(enabled, reason) { transitionApplyAllReady = enabled; transitionApplyAllReason = reason; updateTransitionApplyAll() },
    setAnimationGallery(target, effect) {
      if (target !== animationTarget) cancelAnimationHover()
      animationTarget = target; appliedAnimation = effect; updateAnimationGallery()
    },
    setTablePresetEnabled(enabled, reason) { tablePresetReady = enabled; tablePresetReason = reason; updateTablePresetGallery() },
    setTableShadingState(value, cell, enabled, hint) {
      if (!tableShading) return
      const { group, heading, palette } = tableShading
      const label = localize(cell ? 'Cell Shading' : 'Shading')
      group.setAttribute('aria-label', label)
      heading.textContent = label
      palette.setAttribute('aria-label', label)
      tableShading.enabled = enabled
      palette.disabled = locked || !enabled
      palette.title = hint
      for (const swatch of palette.querySelectorAll<HTMLButtonElement>('button')) {
        swatch.setAttribute('aria-pressed', String(swatch.dataset.tableShadingColor === value))
      }
    },
    cancelAnimationHover,
    setSlideOrientationEnabled(enabled) {
      hasWritableSlideSize = enabled
      updateSlideOrientationState()
    },
    setLayouts(layouts) {
      for (const select of controls.get('layout') ?? []) {
        const picker = select as HTMLSelectElement
        const current = picker.value
        picker.replaceChildren(...layouts.map(layout => new Option(slidesLayoutLabel(layout, document.documentElement.lang), layout.path)))
        picker.value = layouts.some(layout => layout.path === current) ? current : ''
      }
      for (const select of controls.get('addSlideWithLayout') ?? []) {
        (select as HTMLSelectElement).replaceChildren(new Option('新建指定版式幻灯片…', ''), ...layouts.map(layout => new Option(slidesLayoutLabel(layout, document.documentElement.lang), layout.path)))
      }
    },
    setValue(command, value, hint) {
      for (const element of controls.get(command) ?? []) {
        if (command === 'transition') element.setAttribute('aria-pressed', String(element.dataset.transitionEffect === value))
        if (command === 'tableStyle') element.setAttribute('aria-pressed', String(element.dataset.tableStylePreset === value))
        if (command === 'pictureOutlineWidth') for (const button of element.querySelectorAll<HTMLButtonElement>('[data-outline-width]')) {
          button.setAttribute('aria-pressed', String(button.dataset.outlineWidth === value))
        }
        if (command === 'pictureNoOutline') element.setAttribute('aria-pressed', value)
        if (command === 'pictureOpacity') {
          for (const choice of pictureTransparency?.menu.querySelectorAll<HTMLButtonElement>('[data-picture-transparency]') ?? []) {
            choice.setAttribute('aria-pressed', String(choice.dataset.pictureTransparency === value))
          }
          if (value) element.setAttribute('aria-description', value + '%')
          else element.removeAttribute('aria-description')
        }
        if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
          element.value = value
          if (command === 'bulletColor') {
            element.dataset.mixed = String(!value)
            element.style.opacity = value ? '1' : '0'
            const stateLabel = element.parentElement?.querySelector<HTMLElement>('.bullet-color-state')
            if (stateLabel) stateLabel.textContent = value || '未设置或混合值（点击选择）'
            element.setAttribute('aria-valuetext', value || '未设置或混合值')
          }
        }
        if (hint !== undefined) {
          element.title = hint
          if (element instanceof HTMLInputElement) element.placeholder = hint
          if (command === 'lineSpacingPct' && element instanceof HTMLSelectElement) element.options[0]!.textContent = hint
        }
        if (command === 'bold' && element instanceof HTMLButtonElement) element.setAttribute('aria-pressed', String(value === 'true'))
        if (['commentsPane', 'italic', 'underline', 'strike', 'hideSlide', 'tableFirstRow', 'tableBandRow', 'tableRtl', 'cropPicture'].includes(command) && element instanceof HTMLButtonElement) element.setAttribute('aria-pressed', String(value === 'true'))
      }
      if (command === 'bulletKind') for (const [kind, id] of [['char', 'bulletChar'], ['number', 'bulletNumber'], ['none', 'bulletNone']]) {
        for (const element of controls.get(id!) ?? []) element.setAttribute('aria-pressed', String(kind === value))
      }
      if (command === 'paragraphDirection') for (const [rtl, id] of [['false', 'directionLtr'], ['true', 'directionRtl']]) {
        for (const element of controls.get(id!) ?? []) element.setAttribute('aria-pressed', String(rtl === value))
      }
      if (command === 'paragraphAlign') for (const alignment of ['left', 'center', 'right', 'justify']) {
        for (const element of controls.get(`paragraphAlign${alignment[0]!.toUpperCase()}${alignment.slice(1)}`) ?? []) {
          if (element instanceof HTMLButtonElement) element.setAttribute('aria-pressed', String(alignment === value))
        }
      }
      if (['normalView', 'outlineView', 'slideSorter', 'readingView', 'toggleAnimationPane', 'animationByParagraph', 'grid', 'ruler', 'guides', 'thumbnailPane'].includes(command)) for (const element of controls.get(command) ?? []) element.setAttribute('aria-pressed', value)
      if (command === 'animationEffect') {
        currentAnimationEffect = value
        const direction = (controls.get('animationDirection') ?? [])[0] as HTMLSelectElement | undefined
        if (direction) {
          const enabled = ['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(value)
          direction.disabled = locked || !enabled
          direction.title = enabled ? '' : '方向仅适用于飞入、飞出、擦除和擦除退出。'
        }
      }
    },
    setLocked(value) {
      locked = value
      if (tableShading) tableShading.palette.disabled = value || !tableShading.enabled
      for (const flyout of animationFlyouts) flyout.trigger.disabled = value
      if (value) {
        cancelAnimationHover()
        for (const flyout of animationFlyouts) flyout.close()
      }
      if (value) { closePictureMenus(); closeShapeGalleries(); closeShapeFormatMenus() }
      chartGallery?.setLocked(value)
      for (const elements of controls.values()) for (const element of elements) {
        if (element instanceof HTMLButtonElement || element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement || element instanceof HTMLFieldSetElement) {
          element.disabled = locked || element.dataset.unavailable === 'true'
        }
      }
      const direction = (controls.get('animationDirection') ?? [])[0] as HTMLSelectElement | undefined
      if (direction) direction.disabled = locked || !['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(currentAnimationEffect)
      updateTextFormattingState()
      updateSlideOrientationState()
      updateTransitionApplyAll()
      updateTransitionEdit()
      updateAnimationGallery()
      updateTablePresetGallery()
      updateCommentEdit()
      updateAIEdit()
    },
    dispose() {
      desktopMenus.forEach(close => close()); animationLayoutObserver?.disconnect(); for (const flyout of animationFlyouts) flyout.close(); cancelAnimationHover(); chartGallery?.dispose(); closePictureMenus(); closeShapeGalleries(); closeShapeFormatMenus(); disposeScroll(); root.remove() },
  }

  function updateTextFormattingState() {
    for (const command of ['bold', 'italic', 'underline', 'strike', 'fontSize', 'fontSizeUp', 'fontSizeDown', 'fontFamily', 'fontColor', 'paragraphAlignLeft', 'paragraphAlignCenter', 'paragraphAlignRight', 'paragraphAlignJustify', 'lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt', ...PARAGRAPH_LIST_COMMANDS]) {
      for (const element of controls.get(command) ?? []) {
        if (element instanceof HTMLButtonElement || element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
          const requiresNumber = command === 'startAt'
          const requiresBullet = ['bulletSizePct', 'bulletColorPreset', 'bulletColor'].includes(command)
          const requiresHang = ['bulletHangEmu', 'bulletHangPx'].includes(command)
          const unavailableTarget = (requiresNumber && !listTargets.numbers) || (requiresBullet && !listTargets.bullets) || (requiresHang && !listTargets.hanging)
          element.disabled = locked || !hasTextTarget || unavailableTarget
          if (unavailableTarget) element.title = requiresNumber ? '先设置编号；起始编号仅作用于现有编号段落。' : '先设置项目符号或编号；此选项仅作用于适用段落。'
        }
      }
    }
  }
  function updateSlideOrientationState() {
    for (const element of controls.get('slideOrientation') ?? []) {
      const select = element as HTMLSelectElement
      select.disabled = locked || !hasWritableSlideSize
      select.title = hasWritableSlideSize ? '' : '当前尺寸超出可写范围；请先输入 1–56 in 范围内的尺寸。'
    }
  }
}
