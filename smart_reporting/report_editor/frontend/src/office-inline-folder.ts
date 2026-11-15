function editFolderName(
  input: HTMLInputElement, initial: string, commitName: (name: string) => void, close: (restoreFocus: boolean) => void,
) {
  let settled = false
  const finish = (commit: boolean) => {
    if (settled) return
    settled = true
    const name = input.value.trim()
    close(!commit)
    if (commit && name && name !== initial) commitName(name)
  }
  input.addEventListener('blur', () => finish(true))
  input.addEventListener('keydown', event => {
    event.stopPropagation()
    if (event.isComposing || (event.key !== 'Enter' && event.key !== 'Escape')) return
    event.preventDefault()
    finish(event.key === 'Enter')
  })
  input.focus()
}

export function openInlineFolder(parent: HTMLElement, create: (name: string) => void): HTMLInputElement {
  parent.parentElement?.querySelector('.folder-create-row')?.remove()
  const row = document.createElement('div')
  row.className = 'folder-row folder-create-row'
  row.style.setProperty('--depth', String(Number(parent.style.getPropertyValue('--depth')) + 1))
  const input = document.createElement('input')
  input.type = 'text'
  input.className = 'folder-name-input'
  input.placeholder = '新建文件夹'
  input.setAttribute('aria-label', '新建文件夹名称')
  row.append(input)
  parent.after(row)
  editFolderName(input, '', create, restoreFocus => {
    row.remove()
    if (restoreFocus) parent.querySelector<HTMLElement>('[data-folder]')?.focus()
  })
  return input
}

export function renameInlineFolder(button: HTMLButtonElement, name: string, rename: (name: string) => void): HTMLInputElement {
  const input = document.createElement('input')
  input.type = 'text'
  input.className = 'folder-name-input'
  input.setAttribute('aria-label', '重命名文件夹')
  input.value = name
  button.replaceWith(input)
  editFolderName(input, name, rename, restoreFocus => {
    input.replaceWith(button)
    if (restoreFocus) button.focus()
  })
  input.select()
  return input
}
