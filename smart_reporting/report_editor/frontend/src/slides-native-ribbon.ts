import { createOfficeAIEntry } from './office-ai-entry'
import { bindOfficeRibbonScroll } from './office-ribbon-scroll'
import { SLIDES_TABLE_PRESETS } from './slides-table-presets'
import { TABLE_SHADING_COLORS } from './vendor/genoffice-slides/components/table-shading-colors'
import { SLIDE_TRANSITIONS } from './slides-transitions'
import { SMARTART_GALLERY } from './vendor/genoffice-slides/components/smartart-gallery-data'
import { CHART_GALLERY } from './vendor/genoffice-slides/components/chart-gallery-data'
import { WORDART_PRESETS } from './vendor/genoffice-docs/packages/ui/src/wordart-presets'
/** 固定源 ribbon zh 语言包中的艺术字预设名称（ribbonWordArtPreset*） */
export const WORDART_PRESET_LABELS: Record<string, string> = { blue: '填充：蓝色', gold: '填充：金色', red: '填充：深红', purple: '填充：紫色', 'green-italic': '填充：绿色；斜体', 'white-orange': '填充：白色；描边：橙色', 'white-red': '填充：白色；描边：深红', 'gold-brown': '填充：金色；描边：棕色', 'sky-navy': '填充：天蓝；描边：藏青', 'navy-white': '填充：藏青；描边：白色', 'black-gold': '填充：黑色；描边：金色', 'silver-dark': '填充：银色；描边：深灰' }
import { LINE_SHAPE_KINDS, SHAPE_GALLERY_GROUPS } from './vendor/genoffice-slides/components/shape-gallery-data'
import './office-theme.css'
import { BULLET_GLYPHS, BULLET_GLYPH_LABELS, BULLET_SYMBOLS, NUMBER_TYPES, BULLET_COLORS, PARAGRAPH_LIST_COMMANDS } from './slides-paragraph'
import { ArrowDown, ArrowUp, Bold, Download, Italic, Plus, Strikethrough, Trash2, Underline, createElement } from 'lucide'
import { createElement as reactElement, type ComponentType } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { IconAlignCenter, IconAlignJustify, IconAlignLeft, IconAlignRight, IconChart, IconComment, IconCopy, IconCut, IconDateTime, IconEquation, IconFooter, IconFormatPainter, IconGrowFont, IconNavPane, IconNewSlide, IconPageNumber, IconPaste, IconPicture, IconPlayFromStart, IconSave, IconSection, IconShapes, IconShrinkFont, IconSmartArt, IconSlideLayout, IconSlideMaster, IconSwitchRowCol, IconTable, IconTextBox, IconWordArt } from './vendor/genoffice-slides/components/icons'
import { genOfficeHomeClipboardLocale } from './vendor/genoffice-slides/components/ribbon-home-clipboard-locales'
import { slidesLayoutLabel, slidesRibbonLabel } from './slides-native-ribbon-locales'
import { slidesRibbonIcons, slidesRibbonSourceIcons } from './slides-native-ribbon-icons'
import { createNativeChartGallery, type NativeChartGalleryState } from './slides-native-chart-gallery'

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
  setTransitionEditEnabled(enabled: boolean, reason?: string): void
  setTransitionApplyAllEnabled(enabled: boolean, reason?: string): void
  setLocked(locked: boolean): void
  dispose(): void
}

type RibbonGlyph = ComponentType<{ size?: number }>
type Control = { id: string; label: string; kind?: 'button' | 'toggle' | 'select' | 'color' | 'number' | 'font' | 'spacing'; options?: string[]; optionLabels?: string[]; caption?: string; icon?: Parameters<typeof createElement>[0]; sourceIcon?: RibbonGlyph; sourceActionId?: string; unavailable?: string }
type Group = { label: string; controls: Control[] }
type Tab = { id: string; label: string; groups: Group[]; context?: NativeSlidesContext }

const noWrite = (operation: string) => `${operation} 尚无受支持的 editSlides 写回操作。`
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
    { label: 'Export', controls: [
      { id: 'print', label: 'Print', unavailable: desktop('打印') },
      { id: 'exportPdf', label: 'Export PDF', icon: Download, unavailable: noWrite('PDF 导出') },
      { id: 'exportImages', label: 'Export Images', unavailable: noWrite('图片导出') },
    ] },
    { label: 'Save', controls: [
      { id: 'saveRevision', label: 'Save Revision', sourceIcon: IconSave },
      { id: 'saveAs', label: 'Save As', unavailable: noWrite('另存为') },
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
      { id: 'pictureBullet', label: 'Picture Bullet', sourceActionId: 'onParagraphFormat', unavailable: desktop('图片项目符号文件选择与上传') },
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
      { id: 'insertShape', label: 'Shapes', kind: 'select', sourceIcon: IconShapes, sourceActionId: 'onPickShape' },
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
    { label: 'Symbols', controls: [{ id: 'insertEquation', label: 'Equation', sourceIcon: IconEquation, sourceActionId: 'onOpenEquation', unavailable: noWrite('公式编辑/数学标记未进入 editSlides 请求') }] },
    { label: 'Media', controls: [
      { id: 'insertAudio', label: 'Audio', unavailable: desktop('插入音频') },
      { id: 'insertVideo', label: 'Video', unavailable: desktop('插入视频') },
      { id: 'insertModel3d', label: '3D Model', unavailable: desktop('读取 3D 模型文件') },
    ] },
  ] },
  { id: 'draw', label: 'Draw', groups: [
    { label: 'Tools', controls: [{ id: 'drawPen', label: 'Pen', unavailable: noWrite('墨迹') }, { id: 'drawEraser', label: 'Eraser', unavailable: noWrite('墨迹擦除') }] },
  ] },
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
    { label: 'Transition to This Slide', controls: [{ id: 'transition', label: 'Effect', kind: 'select', sourceActionId: 'onTransition', options: [...SLIDE_TRANSITIONS] }] },
    { label: 'Timing', controls: [{ id: 'applyTransitionAll', label: 'Apply to All', sourceActionId: 'onTransition' }] },
  ] },
  { id: 'animations', label: 'Animations', groups: [
    { label: 'Preview', controls: [{ id: 'animationPreview', label: 'Preview', sourceActionId: 'onAnimPreview', unavailable: noWrite('动画预览') }] },
    { label: 'Animation', controls: [
      { id: 'animationNone', label: 'None', sourceActionId: 'onApplyAnimation' },
      { id: 'animationEffect', label: 'Effect', kind: 'select', sourceActionId: 'onApplyAnimation', options: ['appear', 'fade', 'flyIn', 'wipe', 'wipeDown', 'splitIn', 'bounce', 'flipIn', 'zoom', 'pulse', 'spin', 'grow', 'teeter', 'disappear', 'fadeOut', 'flyOut', 'wipeOut', 'shrink', 'zoomOut'] },
      { id: 'animationDirection', label: 'Direction', kind: 'select', options: ['top', 'bottom', 'left', 'right'] },
      { id: 'addAnimation', label: 'Add Animation', sourceActionId: 'onAddAnimation' },
      { id: 'toggleAnimationPane', label: 'Animation Pane', sourceActionId: 'onToggleAnimPane' },
      { id: 'animationByParagraph', label: 'By Paragraph', sourceActionId: 'onToggleAnimByParagraph' },
    ] },
    { label: 'Motion Paths', controls: [
      { id: 'motionPathRight', label: 'Line Right', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathDown', label: 'Line Down', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathDiagonal', label: 'Diagonal', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathCircle', label: 'Circle', sourceActionId: 'onApplyMotionPath' },
      { id: 'motionPathZigzag', label: 'Zigzag', sourceActionId: 'onApplyMotionPath' },
    ] },
    { label: 'Timing', controls: [
      { id: 'animationTrigger', label: 'Trigger', kind: 'select', sourceActionId: 'onAnimTiming', options: ['onClick', 'withPrev', 'afterPrev'] },
      { id: 'animationDuration', label: 'Duration (ms)', kind: 'number', sourceActionId: 'onAnimTiming' },
      { id: 'animationDelay', label: 'Delay (ms)', kind: 'number', sourceActionId: 'onAnimTiming' },
    ] },
  ] },
  { id: 'slideShow', label: 'Slide Show', groups: [
    { label: 'Start Slide Show', controls: [{ id: 'startShow', label: 'From Beginning', sourceIcon: IconPlayFromStart, sourceActionId: 'onSlideShow' }, { id: 'startShowCurrent', label: 'From Current Slide', sourceActionId: 'onSlideShow' }, { id: 'presenter', label: 'Presenter View', unavailable: desktop('演讲者视图') }] },
    { label: 'Set Up', controls: [{ id: 'rehearse', label: 'Rehearse Timings', unavailable: noWrite('排练计时') }, { id: 'record', label: 'Record', unavailable: desktop('屏幕/旁白录制') }, { id: 'hideSlide', label: 'Hide Slide', kind: 'toggle' }] },
  ] },
  { id: 'review', label: 'Review', groups: [
    { label: 'Comments', controls: [
      { id: 'newComment', label: 'New Comment', sourceIcon: IconComment, sourceActionId: 'onNewComment' },
      { id: 'commentsPane', label: 'Comments Pane', kind: 'toggle', sourceIcon: IconNavPane, sourceActionId: 'onToggleComments' },
    ] },
    { label: 'Proofing', controls: [{ id: 'spelling', label: 'Spelling', unavailable: noWrite('拼写检查') }, { id: 'translate', label: 'Translate', unavailable: noWrite('翻译写回') }] },
  ] },
  { id: 'view', label: 'View', groups: [
    { label: 'Presentation Views', controls: [
      { id: 'normalView', label: 'Normal', unavailable: noWrite('大纲/排序/阅读视图状态') },
      { id: 'slideSorter', label: 'Slide Sorter', unavailable: noWrite('大纲/排序/阅读视图状态') },
      { id: 'slideMaster', label: 'Slide Master', sourceIcon: IconSlideMaster, unavailable: noWrite('母版编辑') },
    ] },
    { label: 'Show', controls: [{ id: 'ruler', label: 'Ruler', kind: 'toggle', sourceActionId: 'onToggleRuler' }, { id: 'grid', label: 'Gridlines', kind: 'toggle', sourceActionId: 'onToggleGrid' }, { id: 'notes', label: 'Notes', kind:'toggle', sourceActionId:'onToggleNotes' }] },
  ] },
  { id: 'tableDesign', label: 'Table Design', context: 'table', groups: [{ label: 'Table Styles', controls: [{ id: 'tableStructure', label: 'Rows and Columns', caption: '行列操作', sourceActionId: 'editTableStructure' }, { id: 'tableStyle', label: 'Table Style', caption: '表格样式', kind: 'select', sourceActionId: 'onEditTableStyle', options: ['', ...SLIDES_TABLE_PRESETS.map(item => item.name)], optionLabels: ['来源样式或未选择', ...SLIDES_TABLE_PRESETS.map(item => item.label)] }, { id: 'tableFirstRow', label: '标题行', kind: 'toggle', sourceActionId: 'onEditTableStyle' }, { id: 'tableBandRow', label: '斑马纹', kind: 'toggle', sourceActionId: 'onEditTableStyle' }, { id: 'tableRtl', label: '从右到左表格', kind: 'toggle', sourceActionId: 'onEditTableStyle' }, { id: 'tableShadingWholeTable', label: '底纹作用于整表', sourceActionId: 'onEditTableStyle' }, { id: 'tableShading', label: 'Shading', caption: '底纹', kind: 'select', sourceActionId: 'onEditTableStyle', options: ['', ...TABLE_SHADING_COLORS, 'none'], optionLabels: ['选择底纹', '白色', '浅灰', '浅青', '淡蓝', '灰蓝', '浅黄', '浅橙', '浅桃', '浅绿', '浅紫', '无填充'] }, { id: 'tableAllBorders', label: 'All Borders', caption: '所有边框', sourceActionId: 'onEditTableStyle' }, { id: 'tableNoBorders', label: 'No Borders', caption: '无边框', sourceActionId: 'onEditTableStyle' }] }] },
  { id: 'chartDesign', label: 'Chart Design', context: 'chart', groups: [{ label: 'Chart Elements', controls: [{ id: 'chartElements', label: 'Chart Elements', sourceActionId: 'onEditChart', sourceIcon: IconChart }] }, { label: 'Chart Styles', controls: [{ id: 'chartDesignPresets', label: 'Chart Colors and Styles', sourceActionId: 'onEditChart', sourceIcon: IconChart }, { id: 'chartPointColors', label: 'Chart Point Colors', sourceActionId: 'onEditChart', sourceIcon: IconChart }] }, { label: 'Chart Data', controls: [{ id: 'chartSwitchRowCol', label: 'Switch Row/Column', sourceActionId: 'onEditChart', sourceIcon: IconSwitchRowCol }, { id: 'chartType', label: 'Change Chart Type', sourceActionId: 'onChartType' }, { id: 'chartData', label: 'Edit Data', sourceActionId: 'onChartData' }] }] },
  { id: 'pictureFormat', label: 'Picture Format', context: 'picture', groups: [{ label: 'Adjust', controls: [{ id: 'replacePicture', label: 'Replace Picture', sourceActionId: 'onReplacePicture' }, { id: 'cropPicture', label: 'Crop', sourceActionId: 'onPictureCrop' }, { id: 'pictureOpacity', label: 'Transparency', caption: '透明度 %', kind: 'number', sourceActionId: 'onPictureOpacity' }] }] },
  { id: 'shapeFormat', label: 'Shape Format', context: 'shape', groups: [
    { label: 'Size', controls: [{ id: 'shapeGeometry', label: 'Position and Size' }] },
    { label: 'Shape Styles', controls: [{ id: 'shapeFill', label: 'Fill', caption: '填充', kind: 'color', sourceActionId: 'onShapeFill' }, { id: 'shapeNoFill', label: 'No Fill', caption: '无填充', sourceActionId: 'onShapeFill' }, { id: 'shapeOutline', label: 'Outline', caption: '轮廓', kind: 'color', sourceActionId: 'onShapeOutline' }, { id: 'shapeOutlineWidth', label: 'Outline Weight', caption: '粗细', kind: 'select', options: ['0.75', '1', '1.5', '2.25', '3', '4.5', '6'], optionLabels: ['0.75 磅', '1 磅', '1.5 磅', '2.25 磅', '3 磅', '4.5 磅', '6 磅'], sourceActionId: 'onShapeOutline' }, { id: 'shapeNoOutline', label: 'No Outline', caption: '无轮廓', sourceActionId: 'onShapeOutline' }, { id: 'changeShape', label: 'Change Shape', caption: '更改形状', kind: 'select', sourceActionId: 'onChangeShape' }] },
  ] },
  { id: 'model3dFormat', label: '3D Model', context: 'model3d', groups: [{ label: 'Views', controls: [{ id: 'model3dView', label: '3D View', unavailable: noWrite('3D 视角') }] }] },
]

export function createSlidesNativeRibbon(host: HTMLElement, options: {
  onAction: NativeSlidesAction
  onAssistant?: () => void
  layouts?: NativeSlidesLayout[]
  locked?: boolean
}): NativeSlidesRibbon {
  const root = document.createElement('section')
  root.className = 'slides-native-ribbon'
  const disposeScroll = bindOfficeRibbonScroll(root)
  root.setAttribute('aria-label', 'PowerPoint 功能区')
  const tablist = document.createElement('div')
  tablist.className = 'slides-native-ribbon-tabs'
  tablist.setAttribute('role', 'tablist')
  const panels = new Map<string, HTMLElement>()
  const tabButtons = new Map<string, HTMLButtonElement>()
  const controls = new Map<string, HTMLElement[]>()
  let activeTab = 'home'
  let activeContext: NativeSlidesContext = null
  let chartGallery: ReturnType<typeof createNativeChartGallery> | undefined
  let locked = options.locked === true
  let currentAnimationEffect = ''
  let listTargets = { bullets: false, numbers: false, hanging: false }
  let hasTextTarget = false
  let hasWritableSlideSize = false
  const clipboardLocale = genOfficeHomeClipboardLocale(document.documentElement.lang)
  const localize = (label: string) => slidesRibbonLabel(label, document.documentElement.lang)

  let commentEditReady = false, commentEditReason: string | undefined
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
      ;(control as HTMLSelectElement).disabled = locked || !transitionEditReady
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
  const selectTab = (id: string) => {
    if (id !== 'chartDesign') chartGallery?.close()
    activeTab = id
    for (const tab of tabs) {
      const selected = tab.id === id
      const button = tabButtons.get(tab.id)!
      button.setAttribute('aria-selected', String(selected))
      button.tabIndex = selected ? 0 : -1
      panels.get(tab.id)!.hidden = !selected
    }
  }
  for (const tab of tabs) {
    const button = document.createElement('button')
    button.type = 'button'
    button.id = `slides-native-tab-${tab.id}`
    button.dataset.ribbonTab = tab.id
    button.textContent = localize(tab.label)
    button.setAttribute('role', 'tab')
    button.setAttribute('aria-controls', `slides-native-panel-${tab.id}`)
    button.hidden = !!tab.context
    button.addEventListener('click', () => selectTab(tab.id))
    button.addEventListener('keydown', event => {
      const visible = tabs.filter(item => !item.context || item.context === activeContext)
      const index = visible.findIndex(item => item.id === tab.id)
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
    panel.setAttribute('role', 'tabpanel')
    panel.setAttribute('aria-labelledby', button.id)
    panel.hidden = tab.id !== activeTab || !!tab.context
    for (const groupDefinition of tab.groups) {
      const group = document.createElement('section')
      group.className = 'slides-native-ribbon-group'
      group.dataset.ribbonGroup = groupDefinition.label
      const groupLabel = tab.id === 'home' && groupDefinition.label === 'Clipboard' ? clipboardLocale.group : localize(groupDefinition.label)
      group.setAttribute('aria-label', groupLabel)
      const heading = document.createElement('h3')
      heading.textContent = groupLabel
      group.append(heading)
      if (groupDefinition.label === 'AI 助手') {
        group.classList.add('office-ai-group')
        group.append(createOfficeAIEntry(options.onAssistant))
      }
      for (const control of groupDefinition.controls) {
        const localizedLabel = tab.id === 'home' && groupDefinition.label === 'Clipboard'
          ? clipboardLocale[(control.id === 'formatBrush' ? 'formatPainter' : control.id) as keyof typeof clipboardLocale] as string
          : localize(control.label)
        const unavailable = control.unavailable
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
        } else if (control.kind === 'select') {
          const select = document.createElement('select')
          select.setAttribute('aria-label', localizedLabel)
          select.dataset.command = control.id
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
          } else if (control.id === 'insertShape' || control.id === 'changeShape') {
            // 固定源形状库：分组与顺序同 SHAPE_GALLERY_GROUPS，选后复位。
            select.add(new Option(control.id === 'insertShape' ? '插入形状…' : '更改形状…', ''))
            // 更改形状与固定源一致：线条不在可选范围内。
            for (const group of SHAPE_GALLERY_GROUPS.filter(item => control.id === 'insertShape' || item.shapes.some(shape => !LINE_SHAPE_KINDS.includes(shape.prst)))) {
              const optgroup = document.createElement('optgroup'); optgroup.label = group.group
              for (const shape of group.shapes.filter(item => control.id === 'insertShape' || !LINE_SHAPE_KINDS.includes(item.prst))) optgroup.append(new Option(shape.label, shape.prst))
              select.append(optgroup)
            }
          } else if (control.id === 'layout' || control.id === 'addSlideWithLayout') {
            if (control.id === 'addSlideWithLayout') select.add(new Option('新建指定版式幻灯片…', ''))
            for (const layout of options.layouts ?? []) select.add(new Option(slidesLayoutLabel(layout, document.documentElement.lang), layout.path))
          } else {
            for (const [index, value] of (control.options ?? []).entries()) select.add(new Option(localize(control.optionLabels?.[index] ?? (control.id === 'lineSpacingPct' ? `${Number(value) / 100} 倍` : value)), value))
          }
          select.addEventListener('change', () => { options.onAction(control.id, select.value); if (['addSlideWithLayout', 'insertShape', 'changeShape', 'insertWordArt', 'insertChart', 'insertSmartArt'].includes(control.id)) select.value = '' })
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
          if (sourceIcon) buttonElement.insertAdjacentHTML('afterbegin', sourceIcon)
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
        if (control.unavailable) {
          element.id = controlId
        } else {
          element.id = controlId
          if (locked) (element as HTMLButtonElement).disabled = true
        }
        if (control.sourceActionId) element.dataset.sourceAction = control.sourceActionId
        if (!element.title) element.title = localizedLabel
        if (PARAGRAPH_LIST_COMMANDS.includes(control.id)) element.title = localizedLabel + '：作用于当前对象的全部段落；自定义输入 Enter 提交'
        controls.set(control.id, [...(controls.get(control.id) ?? []), element])
        if (control.caption || ['lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt'].includes(control.id)) {
          const label = document.createElement('label')
          label.htmlFor = controlId
          label.className = 'slides-ribbon-field'
          label.append(document.createTextNode(control.caption ?? (control.id === 'lineSpacingPct' ? '行距' : control.id === 'spaceBeforePt' ? '段前（磅）' : '段后（磅）')), element)
          if (control.id === 'bulletColor') {
            const status = document.createElement('span')
            status.className = 'bullet-color-state'
            label.append(status)
          }
          group.append(label)
        } else group.append(element)
      }
      if (tab.id === 'chartDesign' && groupDefinition.label === 'Chart Styles') {
        chartGallery = createNativeChartGallery(group, (command, value) => options.onAction(command, value))
        chartGallery.setLocked(locked)
      }
      panel.append(group)
    }
    panels.set(tab.id, panel)
    root.append(panel)
  }
  root.prepend(tablist)
  host.prepend(root)
  selectTab(activeTab)
  updateTextFormattingState()
  updateSlideOrientationState()
  updateTransitionApplyAll()
  updateTransitionEdit()
  updateCommentEdit()

  return {
    setChartDesign(state) { chartGallery?.setState(state) },
    setContext(context) {
      if (context !== 'chart') chartGallery?.setState(null)
      activeContext = context
      for (const tab of tabs.filter(item => item.context)) {
        const visible = tab.context === context
        tabButtons.get(tab.id)!.hidden = !visible
        panels.get(tab.id)!.hidden = tab.id !== activeTab
      }
      const activeContextTab = tabs.find(tab => tab.id === activeTab && tab.context)
      if (activeContextTab && activeContextTab.context !== context) selectTab('home')
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
    setTransitionEditEnabled(enabled, reason) { transitionEditReady = enabled; transitionEditReason = reason; updateTransitionEdit() },
    setTransitionApplyAllEnabled(enabled, reason) { transitionApplyAllReady = enabled; transitionApplyAllReason = reason; updateTransitionApplyAll() },
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
        if (['commentsPane', 'italic', 'underline', 'strike', 'hideSlide', 'tableFirstRow', 'tableBandRow', 'tableRtl'].includes(command) && element instanceof HTMLButtonElement) element.setAttribute('aria-pressed', String(value === 'true'))
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
      if (['toggleAnimationPane', 'animationByParagraph', 'grid', 'ruler'].includes(command)) for (const element of controls.get(command) ?? []) element.setAttribute('aria-pressed', value)
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
      chartGallery?.setLocked(value)
      for (const elements of controls.values()) for (const element of elements) {
        if (element instanceof HTMLButtonElement || element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
          element.disabled = locked || element.dataset.unavailable === 'true'
        }
      }
      const direction = (controls.get('animationDirection') ?? [])[0] as HTMLSelectElement | undefined
      if (direction) direction.disabled = locked || !['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(currentAnimationEffect)
      updateTextFormattingState()
      updateSlideOrientationState()
      updateTransitionApplyAll()
      updateTransitionEdit()
      updateCommentEdit()
    },
    dispose() { chartGallery?.dispose(); disposeScroll(); root.remove() },
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
