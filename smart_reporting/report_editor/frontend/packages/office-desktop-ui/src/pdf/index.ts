import { pdfDesktopIconMarkup } from './icons.generated'

// Static SVGs are generated from the desktop components without redrawing their geometry.
const commandIcons: Record<string, string> = {
  highlight: pdfDesktopIconMarkup.IconHighlight, underline: pdfDesktopIconMarkup.IconUnderline, squiggly: pdfDesktopIconMarkup.IconSquiggly, strikeout: pdfDesktopIconMarkup.IconStrike,
  editText: pdfDesktopIconMarkup.IconEditText, insertText: pdfDesktopIconMarkup.IconFormText, undo: pdfDesktopIconMarkup.IconUndo, redo: pdfDesktopIconMarkup.IconRedo,
  toWord: pdfDesktopIconMarkup.IconConvertPdf, toExcel: pdfDesktopIconMarkup.IconConvertPdf, toPowerPoint: pdfDesktopIconMarkup.IconConvertPdf,
  toMarkdown: pdfDesktopIconMarkup.IconConvertPdf, toHtml: pdfDesktopIconMarkup.IconConvertPdf, exportImagesPng: pdfDesktopIconMarkup.IconExportImg, exportImagesJpg: pdfDesktopIconMarkup.IconExportImg,
  fitWidth: pdfDesktopIconMarkup.IconFitWidth, fitPage: pdfDesktopIconMarkup.IconFitPage, toggle: pdfDesktopIconMarkup.IconSearch, search: pdfDesktopIconMarkup.IconSearch,
  print: pdfDesktopIconMarkup.IconPrint, documentProperties: pdfDesktopIconMarkup.IconProps,
  thumbnails: pdfDesktopIconMarkup.IconThumbs, outline: pdfDesktopIconMarkup.IconOutline, comments: pdfDesktopIconMarkup.IconComments,
  pageSpread: pdfDesktopIconMarkup.IconSpread, nightMode: pdfDesktopIconMarkup.IconNight,
  previousField: pdfDesktopIconMarkup.IconPreviousField, nextField: pdfDesktopIconMarkup.IconNextField, complete: pdfDesktopIconMarkup.IconCompleteForm,
  addTextField: pdfDesktopIconMarkup.IconFieldText, addCheckBox: pdfDesktopIconMarkup.IconFieldCheckbox, addDateField: pdfDesktopIconMarkup.IconFieldDate,
  addRadioGroup: pdfDesktopIconMarkup.IconFieldRadio, addRadioOption: pdfDesktopIconMarkup.IconFieldRadio, addDropdown: pdfDesktopIconMarkup.IconFieldChoice,
  keepTool: pdfDesktopIconMarkup.IconFieldKeep, detectFields: pdfDesktopIconMarkup.IconFieldDetect, alignFields: pdfDesktopIconMarkup.IconFieldArrange, preview: pdfDesktopIconMarkup.IconFieldPreview,
  note: pdfDesktopIconMarkup.IconNote, ink: pdfDesktopIconMarkup.IconInk, line: pdfDesktopIconMarkup.IconInk, freehand: pdfDesktopIconMarkup.IconInk,
  rectangle: pdfDesktopIconMarkup.IconRect, ellipse: pdfDesktopIconMarkup.IconEllipse, arrow: pdfDesktopIconMarkup.IconArrow, polygon: pdfDesktopIconMarkup.IconPolygon,
  caret: pdfDesktopIconMarkup.IconCaret, measure: pdfDesktopIconMarkup.IconMeasure, sign: pdfDesktopIconMarkup.IconSign, certificateSign: pdfDesktopIconMarkup.IconCertSign,
  signaturePanel: pdfDesktopIconMarkup.IconSignatures, protect: pdfDesktopIconMarkup.IconProtect,
  rotateLeft: pdfDesktopIconMarkup.IconRotateL, rotateRight: pdfDesktopIconMarkup.IconRotateR, rotateAll: pdfDesktopIconMarkup.IconRotateAll,
  delete: pdfDesktopIconMarkup.IconDeletePage, extract: pdfDesktopIconMarkup.IconExtract, insertPdf: pdfDesktopIconMarkup.IconInsertPdf, insertBlank: pdfDesktopIconMarkup.IconInsertBlank,
  bates: pdfDesktopIconMarkup.IconBates, replace: pdfDesktopIconMarkup.IconReplacePages, crop: pdfDesktopIconMarkup.IconCropPages, size: pdfDesktopIconMarkup.IconPageSize,
  reverse: pdfDesktopIconMarkup.IconReverse, splitPdf: pdfDesktopIconMarkup.IconSplitPdf, mergePdf: pdfDesktopIconMarkup.IconMergePdf,
  mergePages: pdfDesktopIconMarkup.IconMergePages, splitPages: pdfDesktopIconMarkup.IconSplitPages,
  insertImage: pdfDesktopIconMarkup.IconInsertImage, editImage: pdfDesktopIconMarkup.IconEditImage, editLink: pdfDesktopIconMarkup.IconLink, watermark: pdfDesktopIconMarkup.IconWatermark,
  summarize: pdfDesktopIconMarkup.IconAiSummarize, keyPoints: pdfDesktopIconMarkup.IconAiKeyPoints,
}

function adoptCommandIcon(control: HTMLElement): void {
  const command = control.dataset.sourceCommandId?.split('.').at(-1)
  if (!command) return
  const pressed = control.getAttribute('aria-pressed') === 'true'
  const markup = command === 'openAssistant' ? pdfDesktopIconMarkup.GensparkMark26
    : command === 'pageSpread' && pressed ? pdfDesktopIconMarkup.IconSinglePage : commandIcons[command]
  const key = command === 'pageSpread' ? `${command}:${pressed}` : command
  const existing = control.querySelector<SVGSVGElement>('svg')
  if (existing?.dataset.desktopIcon === key) return
  if (!markup) return
  const template = document.createElement('template'); template.innerHTML = markup
  const icon = template.content.firstElementChild as SVGSVGElement
  icon.dataset.desktopIcon = key
  if (existing) existing.replaceWith(icon)
  else control.prepend(icon)
}

/** Visual adapter for the pinned GenOffice PDF ribbon.
 * Keep original command nodes and native controller state; only adopt source classes/wrappers.
 */
export function bindPdfDesktopCommandAppearance(root: HTMLElement): () => void {
  const decorateCommands = () => {
    for (const element of root.querySelectorAll<HTMLElement>('.ribbon-group-items')) {
      const name = element.closest<HTMLElement>('[data-ribbon-group]')?.dataset.ribbonGroup
      for (const control of element.querySelectorAll<HTMLElement>(':scope > button, :scope > a')) {
        adoptCommandIcon(control)
        control.classList.add('rb-big')
        control.classList.toggle('active', control.getAttribute('aria-pressed') === 'true' || control.getAttribute('aria-expanded') === 'true')
        if (name === 'AI' || name === 'AI Review') control.classList.add('ai-entry')
        let icon = control.querySelector<HTMLElement>(':scope > .rb-big-icon')
        const svg = control.querySelector<SVGSVGElement>(':scope > svg')
        if (svg) {
          if (!icon) { icon = document.createElement('span'); icon.className = 'rb-big-icon'; control.prepend(icon) }
          const command = control.dataset.sourceCommandId?.split('.').at(-1)
          if (command === 'summarize' || command === 'keyPoints') {
            const feature = document.createElement('span'); feature.className = 'ai-feature-icon'; feature.setAttribute('aria-hidden', 'true')
            feature.append(svg); icon.append(feature)
          } else icon.append(svg)
        }
        // Some local unavailable commands and download links use plain text nodes.
        for (const text of [...control.childNodes]) {
          if (text.nodeType !== Node.TEXT_NODE || !text.textContent?.trim()) continue
          const label = document.createElement('span'); label.textContent = text.textContent; control.replaceChild(label, text)
        }
      }
      for (const input of element.querySelectorAll('.pdf-view-page-input')) input.classList.add('tb-page-input')
      if (name === 'Page & Zoom') {
        // Reuse the desktop's two-row rb-col/rb-row arrangement; keep the original local select.
        let column = element.querySelector<HTMLElement>(':scope > .pdf-desktop-page-zoom')
        const pageRow = element.querySelector<HTMLElement>(':scope > .pdf-view-page-row')
        if (pageRow && !column) {
          column = document.createElement('div'); column.className = 'rb-col pdf-desktop-page-zoom'
          element.insertBefore(column, pageRow); pageRow.classList.add('rb-row'); column.append(pageRow)
          const zoomRow = document.createElement('div'); zoomRow.className = 'rb-row pdf-desktop-zoom-row'; column.append(zoomRow)
          const zoom = element.querySelector<HTMLElement>(':scope > .pdf-zoom')
          for (const key of ['zoomOut', 'select', 'zoomIn']) {
            const control = key === 'select' ? zoom : element.querySelector<HTMLElement>(`:scope > [data-source-command-id$=".${key}"]`)
            if (control) zoomRow.append(control)
          }
        }
        for (const control of element.querySelectorAll<HTMLElement>('.pdf-desktop-zoom-row > button, .pdf-view-zoom-row > button')) {
          control.classList.remove('rb-big'); control.classList.add('rb-icon')
          const key = control.dataset.sourceCommandId?.split('.').at(-1)
          if (control.querySelector('.pdf-desktop-zoom-symbol')) continue
          control.querySelector('svg')?.remove()
          for (const child of control.children) child.classList.add('pdf-desktop-zoom-label')
          const symbol = document.createElement('span'); symbol.className = 'pdf-desktop-zoom-symbol'; symbol.setAttribute('aria-hidden', 'true'); symbol.textContent = key === 'zoomOut' ? '−' : '+'; control.append(symbol)
        }
        element.querySelector('.pdf-view-page-zoom')?.classList.add('rb-col')
      }
    }
  }
  const observer = new MutationObserver(decorateCommands)
  observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-pressed', 'aria-expanded'] })
  decorateCommands()
  return () => observer.disconnect()
}
