import type { MasterElementEdit } from './slides-master-elements-model'
import type { MasterTextPart } from './slides-master-text-model'

/** 固定源 masterEditStroke 的 1pt 实色/无描边入口。 */
export function mountMasterStrokeControls(host: HTMLElement, options: {
  edits: MasterElementEdit[]; isCurrent(): boolean; onApply(edits: MasterElementEdit[]): void
}) {
  const container = document.createElement('div'); container.className = 'slides-master-stroke'
  container.innerHTML = '<label>对象轮廓<input type="color" name="stroke-color" data-master-stroke-color aria-label="母版对象轮廓颜色"></label><button type="button" data-master-stroke-apply>应用轮廓到草稿</button><button type="button" data-master-stroke-none>无轮廓</button><p role="status"></p>'
  const color = container.querySelector<HTMLInputElement>('[data-master-stroke-color]')!, apply = container.querySelector<HTMLButtonElement>('[data-master-stroke-apply]')!, none = container.querySelector<HTMLButtonElement>('[data-master-stroke-none]')!, status = container.querySelector<HTMLElement>('p')!
  host.append(container)
  let part: MasterTextPart | undefined, selected: MasterTextPart['elements'][number] | undefined, disposed = false
  const commit = (stroke: { color: string; widthPt: 1 } | null) => {
    try {
      if (disposed || !part || !selected?.strokeEditable) return
      if (!options.isCurrent()) throw Error('来源或草稿已变化，请关闭并重新打开母版视图')
      const normalized = stroke ? { color: stroke.color.toUpperCase(), widthPt: 1 as const } : null
      const source = selected.strokeValue, same = normalized ? source === normalized.color : source === 'none'
      const previous = options.edits.findIndex(edit => edit.kind === 'setStroke' && edit.partPath === part!.partPath && edit.spid === selected!.spid)
      const edits = options.edits.filter(edit => !(edit.kind === 'setStroke' && edit.partPath === part!.partPath && edit.spid === selected!.spid))
      if (!same) edits.splice(previous < 0 ? edits.length : previous, 0, { kind: 'setStroke', partPath: part.partPath, spid: selected.spid, stroke: normalized })
      if (JSON.stringify(edits) === JSON.stringify(options.edits)) { status.textContent = '轮廓未变化，未新增草稿操作'; return }
      options.onApply(edits)
    } catch (error) { status.textContent = error instanceof Error ? error.message : '母版轮廓未能加入草稿' }
  }
  apply.addEventListener('click', () => commit({ color: color.value, widthPt: 1 }))
  none.addEventListener('click', () => commit(null))
  return {
    update(value?: MasterTextPart, element?: MasterTextPart['elements'][number]) {
      part = value; selected = element
      const pending = options.edits.find(edit => edit.kind === 'setStroke' && edit.partPath === part?.partPath && edit.spid === selected?.spid)
      const stroke = pending?.kind === 'setStroke' ? pending.stroke : selected?.strokeValue === 'none' ? null : selected?.strokeValue ? { color: selected.strokeValue, widthPt: 1 as const } : undefined
      color.value = stroke?.color && /^#[0-9A-Fa-f]{6}$/.test(stroke.color) ? stroke.color : '#000000'
      color.disabled = apply.disabled = none.disabled = !selected?.strokeEditable
      status.textContent = selected?.strokeEditable ? `${pending ? '草稿' : '来源'}轮廓：${stroke === null ? '无轮廓' : stroke?.color ?? '复杂或继承轮廓（选色后替换）'}` : '当前对象轮廓不可写'
    },
    dispose() { disposed = true; container.remove() },
  }
}
