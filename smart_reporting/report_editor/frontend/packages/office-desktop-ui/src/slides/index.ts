/** DOM-only presentation adapter for the pinned GenOffice desktop ribbon.
 * Commands, availability, persistence and popover lifecycle stay in the host.
 * See SOURCE.md for the original React components and exact copied CSS ranges.
 */
export function desktopRibbonButton(button: HTMLButtonElement, kind: 'big' | 'small' | 'icon' = 'big') {
  button.classList.add(`rb-${kind}`)
  if (kind === 'big' && !button.querySelector(':scope > .rb-big-icon')) {
    const icon = document.createElement('span')
    icon.className = 'rb-big-icon'
    const label = document.createElement('span')
    for (const node of [...button.childNodes]) {
      if (node instanceof SVGElement || node instanceof HTMLImageElement) icon.append(node)
      else label.append(node)
    }
    button.append(icon, label)
  }
  if (kind === 'icon') {
    // Keep labels for assistive technology while matching desktop icon-only rows.
    const label = document.createElement('span')
    label.className = 'desktop-ribbon-sr-label'
    for (const node of [...button.childNodes]) if (node.nodeType === Node.TEXT_NODE || (node instanceof HTMLElement && node.classList.contains('slides-ribbon-toggle-label'))) label.append(node)
    button.append(label)
  }
}

function compactButton(button: HTMLButtonElement, kind: 'small' | 'icon' = 'icon') {
  const icon = button.querySelector(':scope > .rb-big-icon')
  if (icon) { button.prepend(...icon.childNodes); icon.remove() }
  button.lastElementChild?.classList.add('desktop-ribbon-sr-label')
  button.classList.remove('rb-big')
  desktopRibbonButton(button, kind)
}

export function desktopRibbonGroup(group: HTMLElement, items: HTMLElement, tab: string, label: string) {
  for (const button of items.querySelectorAll<HTMLButtonElement>(':scope > button')) desktopRibbonButton(button)
  if (tab !== 'home') return
  const take = (command: string) => items.querySelector<HTMLElement>(`[data-command="${command}"]`)
  const column = (className = 'rb-col') => {
    const element = document.createElement('div')
    element.className = className
    return element
  }
  if (label === 'Clipboard') {
    const compact = column('rb-col rb-clip-col')
    for (const command of ['cut', 'copy', 'formatBrush']) {
      const button = take(command) as HTMLButtonElement | null
      if (!button) continue
      // Unwrap the big presentation before adopting the source compact form.
      const icon = button.querySelector('.rb-big-icon')
      const text = button.lastElementChild
      if (icon) button.prepend(...icon.childNodes)
      icon?.remove()
      if (text) text.className = 'desktop-ribbon-sr-label'
      button.classList.remove('rb-big')
      desktopRibbonButton(button, 'icon')
      compact.append(button)
    }
    items.append(compact)
  } else if (label === 'Font') {
    const col = column(), first = column('rb-row'), second = column('rb-row')
    for (const command of ['fontFamily', 'fontSize', 'fontSizeUp', 'fontSizeDown']) {
      const control = take(command)
      if (!control) continue
      if (control instanceof HTMLInputElement) control.classList.add('rb-font-btn', command === 'fontFamily' ? 'rb-font-name' : 'rb-font-size')
      if (control instanceof HTMLButtonElement) compactButton(control)
      first.append(control)
    }
    for (const child of [...items.children]) {
      if (child instanceof HTMLButtonElement) {
        const icon = child.querySelector('.rb-big-icon')
        if (icon) { child.prepend(...icon.childNodes); icon.remove() }
        child.lastElementChild?.classList.add('desktop-ribbon-sr-label')
        child.classList.remove('rb-big')
        desktopRibbonButton(child, 'icon')
      }
      second.append(child)
    }
    col.append(first, second)
    items.append(col)
  } else if (label === 'Slides') {
    const col = column('rb-col rb-slides-col')
    for (const command of ['layout', 'addSection']) {
      const child = take(command)
      if (!child) continue
      if (child instanceof HTMLButtonElement) {
        const icon = child.querySelector('.rb-big-icon')
        if (icon) { child.prepend(...icon.childNodes); icon.remove() }
        child.classList.remove('rb-big')
        desktopRibbonButton(child, 'small')
      }
      col.append(child)
    }
    const extra = column('rb-col desktop-ribbon-extra')
    for (const command of ['addSlideWithLayout', 'resetLayout', 'movePrevious', 'moveNext']) {
      const child = take(command)
      if (child) extra.append(child)
    }
    items.append(col, extra)
  }
  group.dataset.desktopSource = 'RibbonHomeTab'
}
