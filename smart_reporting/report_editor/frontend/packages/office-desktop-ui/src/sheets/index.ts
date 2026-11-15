/** Presentation adapter for GenOffice's RibbonGroup / two-row control composition.
 * Controllers and permission checks remain in the host application.
 * See vendor/SOURCE.md for pinned upstream source and deviations.
 */
// Commands explicitly rendered with <RibbonButton large> in pinned ExcelShell.
const sourceLargeCommands = new Set([
  'paste', 'chart-select-data', 'chart-switch-row-col', 'chart-format-pane', 'chart-delete',
  'pivot-open', 'pivot-edit', 'format-as-table', 'insert-picture', 'insert-checkbox',
  'recommended-charts-open', 'link-open', 'note-open', 'header-footer-open',
  'insert-function-open', 'name-manager-open', 'toggle-show-formulas', 'error-checking',
  'watch-window', 'external-links-panel', 'filter-toggle', 'flash-fill',
  'remove-duplicates-open', 'dv-open', 'consolidate-open', 'subtotal-open',
  'toggle-page-break-preview', 'zoom-reset', 'zoom-to-selection', 'spell-check',
  'workbook-statistics', 'comment-new', 'comment-delete', 'sheet-protect',
  'workbook-protect', 'allow-edit-ranges-open',
])
export function composeSheetsDesktopGroup(section: HTMLElement, title: string, tab: string) {
  section.classList.add('ribbon-group')
  section.setAttribute('aria-label', title)
  // Upstream RibbonGroup uses aria-label, with no visible caption.
  section.querySelector(':scope > h2')?.remove()
  const content = document.createElement('div')
  content.className = 'ribbon-group-content'
  const controls = Array.from(section.children).filter((item): item is HTMLElement => item instanceof HTMLElement)
  const isFont = tab === 'Home' && title === '字体'
  const isAlignment = tab === 'Home' && title === '对齐方式'
  const isNumber = tab === 'Home' && title === '数字'
  const inline = isFont || isAlignment || isNumber
  section.querySelectorAll<HTMLElement>('.workbook-ribbon-icon').forEach(icon => icon.classList.add('tool-symbol'))
  for (const button of controls.filter((item): item is HTMLButtonElement => item instanceof HTMLButtonElement)) {
    button.classList.add('ribbon-tool', 'as-button')
    if (button.classList.contains('workbook-ribbon-large') || sourceLargeCommands.has(button.dataset.ribbonCommand ?? '') || button.classList.contains('office-ai-entry')) {
      button.classList.add('large')
      if (button.classList.contains('office-ai-entry')) button.classList.add('ai-entry')
      const icon = button.querySelector('.tool-symbol, :scope > svg')
      if (icon) {
        const iconRow = document.createElement('span')
        iconRow.className = 'tool-icon-row'
        icon.before(iconRow)
        iconRow.append(icon)
      }
    } else if (inline && button.querySelector('.tool-symbol')) {
      button.classList.add('sheets-icon-only')
    }
  }
  section.querySelectorAll<HTMLElement>('.workbook-ribbon-large-menu').forEach(menu => {
    menu.classList.add('ribbon-tool', 'large')
    menu.querySelector('.workbook-ribbon-large-menu-icons')?.classList.add('tool-icon-row')
  })
  section.querySelectorAll<HTMLElement>('.workbook-ribbon-check-column').forEach(column => {
    column.classList.add('check-column')
    if (column.classList.contains('workbook-ribbon-check-column-view')) column.classList.add('check-column-view')
    column.querySelectorAll('button').forEach(button => button.classList.add('check-item'))
  })
  section.querySelectorAll<HTMLElement>('.workbook-ribbon-select').forEach(select => select.classList.add('select-like'))
  section.querySelector('[data-ribbon-control="font-family"]')?.classList.add('select-like', 'font-name')
  section.querySelector('[data-ribbon-control="font-size"]')?.classList.add('select-like', 'font-size')
  const pasteSpecial = section.querySelector<HTMLSelectElement>('[data-ribbon-menu="paste-special"]')
  if (pasteSpecial?.parentElement) {
    const wrapper = pasteSpecial.parentElement
    wrapper.classList.add('ribbon-tool', 'large')
    pasteSpecial.classList.add('cover-select')
    const icon = wrapper.querySelector('.tool-symbol')
    if (icon) {
      const iconRow = document.createElement('span'); iconRow.className = 'tool-icon-row'
      icon.before(iconRow); iconRow.append(icon)
    }
    const caption = document.createElement('span'); caption.textContent = pasteSpecial.getAttribute('aria-label')
    caption.setAttribute('aria-hidden', 'true'); wrapper.append(caption)
  }
  const large = (item: HTMLElement) => item.classList.contains('large') || item.classList.contains('check-column')
  if (!inline && !(tab === 'Home' && title === '剪贴板')) {
    // Keep command reading order across mixed tall buttons and row stacks.
    let run: HTMLElement[] = []
    const flush = () => {
      if (!run.length) return
      const rows = document.createElement('div'); rows.className = 'ribbon-rows'
      const first = document.createElement('div'), second = document.createElement('div')
      first.className = second.className = 'inline-tools'
      const midpoint = Math.ceil(run.length / 2)
      run.forEach((item, index) => (index < midpoint ? first : second).append(item))
      rows.append(first); if (second.childElementCount) rows.append(second)
      content.append(rows); run = []
    }
    for (const item of controls) {
      if (large(item) || item.tagName === 'DATALIST') { flush(); content.append(item) }
      else run.push(item)
    }
    flush(); section.replaceChildren(content); return
  }
  const compact = controls.filter(item => !large(item) && item.tagName !== 'DATALIST')
  const rows = document.createElement('div')
  rows.className = inline ? 'ribbon-rows' : 'ribbon-rows sheets-command-rows'
  const first = document.createElement('div'), second = document.createElement('div')
  first.className = second.className = 'inline-tools'
  if (isFont) {
    for (const item of compact) {
      const control = item.dataset.ribbonControl ?? ''
      ;(['font-family', 'font-size', 'font-size-increase', 'font-size-decrease'].includes(control) ? first : second).append(item)
    }
    // Source font row: decorations, then colors and borders.
    const decorationOrder = ['bold', 'italic', 'underline', 'underline:double', 'strike', 'superscript', 'subscript']
    const decorations = decorationOrder.flatMap(command => Array.from(second.children).filter(item => (item as HTMLElement).dataset.ribbonCommand === command))
    second.prepend(...decorations)
  } else if (isNumber) {
    for (const item of compact) (item.dataset.ribbonControl === 'number-format' ? first : second).append(item)
  } else if (tab === 'Home' && title === '剪贴板') {
    // Source clipboard composition: two tall actions and a 3×20px icon stack.
    const stack = document.createElement('div'); stack.className = 'tool-stack'
    for (const item of compact) {
      if (['cut', 'copy', 'format-painter'].includes(item.dataset.ribbonCommand ?? '')) {
        item.classList.add('sheets-icon-only'); stack.append(item)
      } else first.append(item)
    }
    if (stack.childElementCount) content.append(stack)
  } else {
    // Additional host commands use two rows and expand horizontally. They never
    // create a third 30px row that would be clipped by the upstream 80px band.
    const midpoint = Math.ceil(compact.length / 2)
    compact.forEach((item, index) => (index < midpoint ? first : second).append(item))
  }
  if (first.childElementCount) rows.append(first)
  if (second.childElementCount) rows.append(second)
  const tallControls = controls.filter(large)
  content.prepend(...tallControls)
  if (rows.childElementCount) content.append(rows)
  content.append(...controls.filter(item => item.tagName === 'DATALIST'))
  section.replaceChildren(content)
}
