import { createElement, type ComponentType } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { IconAlignLeft, IconBorderOuter, IconCheck, IconCheckbox, IconChevronLeft, IconChevronRight, IconClock, IconComments, IconCompare, IconConvert, IconCrop, IconCursor, IconDoc, IconEraser, IconEye, IconGear, IconLink, IconLock, IconMoon, IconMultiPage, IconNavPane, IconPageSize, IconPageWidth, IconPaperclip, IconPen, IconPencil, IconPicture, IconPlus, IconReplace, IconRotateRight, IconRuler, IconSearch, IconSend, IconShading, IconShapes, IconSplit, IconSwitchWindows, IconSymbol, IconTextBox, IconTrash, IconWatermark, IconWholePage, IconZoomIn, IconZoomOut } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { Underline, Strikethrough, Waves, CaseSensitive, WholeWord, Download, createElement as lucideElement } from 'lucide'

const source: Record<string, ComponentType<{size?: number}>> = {
  'thumbnails': IconNavPane,
  'search': IconSearch,
  'ink': IconPen,
  'measure': IconRuler,
  'polygon': IconShapes,
  'caret': IconSymbol,
  'certificateSign': IconPen,
  'signaturePanel': IconNavPane,
  'addDateField': IconClock,
  'addRadioGroup': IconCheckbox,
  'addRadioOption': IconPlus,
  'addDropdown': IconNavPane,
  'alignFields': IconAlignLeft,
  '选择文字': IconCursor,
  '待保存绘图': IconPen,
  '已保存绘图': IconPicture,
  '校验当前修改': IconCheck,
  '页面前移': IconChevronLeft,
  '页面后移': IconChevronRight,
  '签名字段': IconPen,
  '自动检测': IconSearch,
  '预览': IconEye,

  'rotateAll': IconRotateRight,
  'delete': IconTrash,
  'extract': IconDoc,
  'insertPdf': IconDoc,
  'insertBlank': IconPlus,
  'replace': IconReplace,
  'crop': IconCrop,
  'size': IconPageSize,
  'reverse': IconSwitchWindows,
  'splitPdf': IconSplit,
  'mergePdf': IconMultiPage,
  'mergePages': IconMultiPage,
  'splitPages': IconSplit,
  'redact': IconShading,
  'processNotes': IconComments,
  'line': IconPen,
  'arrow': IconSend,
  'rectangle': IconBorderOuter,
  'ellipse': IconShapes,
  'freehand': IconPen,

  editText: IconPencil, insertText: IconTextBox, toWord: IconConvert, toExcel: IconConvert, toMarkdown: IconConvert, toHtml: IconConvert, toPowerPoint: IconConvert,
  exportImagesPng: IconPicture, exportImagesJpg: IconPicture, zoomIn: IconZoomIn, zoomOut: IconZoomOut, fitWidth: IconPageWidth, fitPage: IconWholePage,
  previousMatch: IconChevronLeft, nextMatch: IconChevronRight, documentProperties: IconDoc,
  outline: IconNavPane, comments: IconComments, attachments: IconPaperclip, pageSpread: IconMultiPage, nightMode: IconMoon, compare: IconCompare,
  addTextField: IconTextBox, addCheckBox: IconCheckbox, deleteField: IconTrash, fieldProperties: IconGear,
  sign: IconPen, protect: IconLock, insertImage: IconPicture, editImage: IconPicture, editLink: IconLink, watermark: IconWatermark,
  clearRedaction: IconEraser, applyRedaction: IconCheck,
}
const fallback: Record<string, Parameters<typeof lucideElement>[0]> = {
  underline: Underline, strikeout: Strikethrough, squiggly: Waves, matchCase: CaseSensitive, wholeWord: WholeWord, downloadOriginal: Download,
}
/** 保留已有 PDF 源图标；缺图命令优先复用 GenOffice Docs 对应图形。 */
export function addPdfCommandIcon(element: HTMLElement, id: string): void {
  if (!element.matches('button, a') || element.querySelector('svg')) return
  const command = id.split('.').at(-1)!
  const component = source[command]
  if (component) element.insertAdjacentHTML('afterbegin', renderToStaticMarkup(createElement(component, {size:16})))
  else if (fallback[command]) element.prepend(lucideElement(fallback[command]!, {width:16,height:16,'stroke-width':1.5,'aria-hidden':'true'}))
}
