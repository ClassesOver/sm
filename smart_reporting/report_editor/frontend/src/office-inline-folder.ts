/** Edit the new folder name in the tree, using the same commit keys as GenOffice. */
export function openInlineFolder(parent: HTMLElement, create: (name: string) => void): HTMLInputElement {
  parent.parentElement?.querySelector('.folder-create-row')?.remove()
  const row = document.createElement('div')
  row.className = 'folder-row folder-create-row'
  row.style.setProperty('--depth', String(Number(parent.style.getPropertyValue('--depth')) + 1))
  const input = document.createElement('input')
  input.type = 'text'
  input.placeholder = '新建文件夹'
  input.setAttribute('aria-label', '新建文件夹名称')
  row.append(input)
  parent.after(row)

  let settled = false
  const finish = (commit: boolean) => {
    if (settled) return
    settled = true
    const name = input.value.trim()
    row.remove()
    if (commit && name) create(name)
    if (!commit) parent.querySelector<HTMLElement>('[data-folder]')?.focus()
  }
  input.addEventListener('blur', () => finish(true))
  input.addEventListener('keydown', event => {
    event.stopPropagation()
    if (event.isComposing || (event.key !== 'Enter' && event.key !== 'Escape')) return
    event.preventDefault()
    finish(event.key === 'Enter')
  })
  input.focus()
  return input
}
