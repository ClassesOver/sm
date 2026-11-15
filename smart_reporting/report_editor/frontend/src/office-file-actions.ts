import { officeRequest, type OfficeLibrary, type OfficeSpace } from './office-client'

type FileTarget = { id: string; name: string; folder: string; version: number }
type FolderTarget = { id: string; name: string; parent: string }

export type OfficeFileAction = 'rename' | 'move' | 'delete'

export async function showOfficeFileActions(host: HTMLElement, options: {
  space: string; spaces: OfficeSpace[]; file?: FileTarget; files?: FileTarget[]; folder?: FolderTarget
  mode?: OfficeFileAction
  onChanged(deleted: boolean): Promise<void>
  onCopy?(): Promise<void>
}) {
  const target = options.file ?? options.folder
  const selected = options.files ?? []
  const panel = document.createElement('dialog')
  panel.className = 'office-administration'
  panel.addEventListener('click', event => event.stopPropagation())
  const title = document.createElement('h2')
  const {mode} = options
  title.textContent = mode ? {rename:'重命名',move:'移动到文件夹',delete:'删除'}[mode] : options.file ? '管理文件' : '管理文件夹'
  const form = document.createElement('form')
  const name = document.createElement('input')
  name.value = target?.name ?? ''; name.required = mode !== 'move'; name.maxLength = 200
  name.setAttribute('aria-label', '名称')
  const space = document.createElement('select')
  space.setAttribute('aria-label', '目标工作区')
  for (const item of options.spaces.filter(item => item.id === options.space ||
    ((options.file || selected.length) && item.role !== 'viewer' && !item.archived))) {
    space.add(new Option(item.name, item.id, false, item.id === options.space))
  }
  const folder = document.createElement('select')
  folder.setAttribute('aria-label', '目标文件夹')
  const save = document.createElement('button')
  save.textContent = '保存'; save.type = 'submit'
  const remove = document.createElement('button')
  remove.textContent = '删除'; remove.type = 'button'
  const close = document.createElement('button')
  close.textContent = '取消'; close.type = 'button'; close.onclick = () => panel.close()
  const status = document.createElement('p'); status.setAttribute('role', 'status')
  if (mode !== 'delete') {
    form.append(name, space, folder, save)
    name.hidden = mode === 'move'
    space.hidden = folder.hidden = mode === 'rename'
    panel.append(title)
    if (selected.length) panel.append(document.createTextNode(`已选 ${selected.length} 个文件`))
    panel.append(form, status)
  } else panel.append(title, document.createTextNode(target?.name ?? ''), status)
  if (!mode || mode === 'delete') panel.append(remove)
  if (!mode && options.onCopy) {
    const copy = document.createElement('button')
    copy.type = 'button'
    copy.textContent = '复制文件'
    const onCopy = options.onCopy
    copy.onclick = () => void run(async () => { await onCopy(); panel.close() })
    panel.append(copy)
  }
  panel.append(close)
  panel.onclose = () => panel.remove()
  host.append(panel); panel.showModal()
  let changing = false

  async function run(action: () => Promise<void>) {
    if (changing) return
    changing = true; save.disabled = remove.disabled = space.disabled = true
    try { await action(); status.textContent = '' }
    catch (error) { status.textContent = error instanceof Error ? error.message : '操作失败。' }
    finally { changing = false; save.disabled = remove.disabled = space.disabled = false }
  }

  async function folders() {
    const result = await officeRequest<OfficeLibrary>(`/workspaces/${encodeURIComponent(space.value)}/library`)
    folder.replaceChildren(new Option('根目录', 'root'))
    const excluded = new Set(options.folder ? [options.folder.id] : [])
    let updated = true
    while (updated) {
      updated = false
      for (const item of result.folders) if (item.parent && excluded.has(item.parent) && !excluded.has(item.id)) {
        excluded.add(item.id); updated = true
      }
    }
    const labels = new Map<string, string>()
    function path(id: string, visited = new Set<string>()): string {
      if (labels.has(id)) return labels.get(id)!
      const item = result.folders.find(item => item.id === id)
      if (!item || visited.has(id)) return ''
      visited.add(id)
      const label = (item.parent ? `${path(item.parent, visited)}/` : '') + item.name
      labels.set(id, label); return label
    }
    for (const item of result.folders) if (!excluded.has(item.id)) folder.add(new Option(path(item.id), item.id))
    folder.value = space.value === options.space ? (options.file?.folder ?? options.folder?.parent ?? 'root') : 'root'
    if (!folder.value) folder.value = 'root'
  }
  space.onchange = () => void run(folders)
  form.onsubmit = event => {
    event.preventDefault()
    void run(async () => {
      const destination = folder.value === 'root' ? null : folder.value
      const naming = mode === 'move' ? {} : {name: name.value.trim()}
      if (selected.length) await officeRequest(`/workspaces/${encodeURIComponent(options.space)}/files/bulk`, 'POST', {
        action: 'move', destination: space.value, folder: destination,
        versions: Object.fromEntries(selected.map(file => [file.id, file.version])),
      })
      else if (options.file) await officeRequest(`/files/${options.file.id}`, 'PATCH', {
        expectedVersion: options.file.version, ...naming,
        ...(mode === 'rename' ? {} : {space: space.value, folder: destination}),
      })
      else if (options.folder) await officeRequest(`/workspaces/${options.space}/folders/${options.folder.id}`, 'PATCH', {
        ...naming, ...(mode === 'rename' ? {} : {parent: destination}),
      })
      await options.onChanged(false); panel.close()
    })
  }
  remove.onclick = () => {
    if (!target || !confirm(options.folder ? `删除“${target.name}”及其全部子文件夹和文件？` : `删除“${target.name}”？`)) return
    void run(async () => {
      if (options.file) await officeRequest(`/files/${target.id}`, 'PATCH', { expectedVersion: options.file.version, deleted: true })
      else await officeRequest(`/workspaces/${options.space}/folders/${target.id}`, 'DELETE')
      await options.onChanged(true); panel.close()
    })
  }
  if (!mode || mode === 'move') await run(folders)
}
