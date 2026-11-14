import type { MasterElementEdit } from './slides-master-elements-model'
import type { MasterTextPart } from './slides-master-text-model'

/** 源母版右键填充的实色/none切片；能力独立于文字可写性。 */
export function mountMasterFillControls(host: HTMLElement, options: {
  edits: MasterElementEdit[]; isCurrent(): boolean; onApply(edits: MasterElementEdit[]): void
}) {
  const container = document.createElement('div'); container.className = 'slides-master-fill'
  container.innerHTML = '<label>对象填充<input type="color" data-master-fill-color aria-label="母版对象填充颜色"></label><button type="button" data-master-fill-apply>应用填充到草稿</button><button type="button" data-master-fill-none>无填充</button><p data-master-fill-status role="status"></p>'
  host.append(container)
  const color = container.querySelector<HTMLInputElement>('[data-master-fill-color]')!, apply = container.querySelector<HTMLButtonElement>('[data-master-fill-apply]')!, none = container.querySelector<HTMLButtonElement>('[data-master-fill-none]')!, status = container.querySelector<HTMLElement>('[data-master-fill-status]')!
  let part: MasterTextPart | undefined, selected: MasterTextPart['elements'][number] | undefined, disposed = false
  const commit = (fill: string) => {
    try {
      if (disposed || !part || !selected?.fillEditable) return
      if (!options.isCurrent()) throw Error('来源或草稿已变化，请关闭并重新打开母版视图')
      if (!/^(?:none|#[0-9A-Fa-f]{6})$/.test(fill)) throw Error('填充只能是实色或无填充')
      const source = selected.fillValue, normalized = fill === 'none' ? fill : fill.toUpperCase()
      const previous = options.edits.findIndex(edit => edit.kind === 'setFill' && edit.partPath === part!.partPath && edit.spid === selected!.spid)
      const edits = options.edits.filter(edit => !(edit.kind === 'setFill' && edit.partPath === part!.partPath && edit.spid === selected!.spid))
      if (normalized !== (source?.startsWith('#') ? source.toUpperCase() : source)) edits.splice(previous < 0 ? edits.length : previous, 0, { kind: 'setFill', partPath: part.partPath, spid: selected.spid, fill: normalized })
      if (JSON.stringify(edits) === JSON.stringify(options.edits)) { status.textContent = '填充未变化，未新增草稿操作'; return }
      options.onApply(edits)
    } catch (error) { status.textContent = error instanceof Error ? error.message : '母版填充未能加入草稿' }
  }
  apply.addEventListener('click', () => commit(color.value))
  none.addEventListener('click', () => commit('none'))
  return {
    update(value?: MasterTextPart, element?: MasterTextPart['elements'][number]) {
      part = value; selected = element
      const pending = options.edits.find(edit => edit.kind === 'setFill' && edit.partPath === part?.partPath && edit.spid === selected?.spid)
      const fill = pending?.kind === 'setFill' ? pending.fill : selected?.fillValue
      color.value = fill && /^#[0-9A-Fa-f]{6}$/.test(fill) ? fill : '#000000'
      color.disabled = apply.disabled = none.disabled = !selected?.fillEditable
      status.textContent = selected?.fillEditable ? `${pending ? '草稿' : '来源'}：${fill === 'none' ? '无填充' : fill ? `实色 ${fill}` : '复杂或继承填充（选色后替换为实色）'}` : selected?.fillReason ?? '当前对象不能修改填充'
    },
    dispose() { disposed = true; container.remove() },
  }
}
