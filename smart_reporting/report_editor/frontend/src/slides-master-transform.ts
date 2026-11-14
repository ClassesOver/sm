import type { MasterElementEdit } from './slides-master-elements-model'
import type { MasterTextPart } from './slides-master-text-model'

/** 顶层对象几何沿固定源 setTransform 事务写回。 */
export function mountMasterTransformControls(host: HTMLElement, options: {
  edits: MasterElementEdit[]; isCurrent(): boolean; onApply(edits: MasterElementEdit[]): void
}) {
  const container = document.createElement('fieldset'); container.className = 'slides-master-transform'
  container.innerHTML = '<legend>对象位置与旋转</legend><div></div><button type="button" data-master-transform-apply>应用几何到草稿</button><p role="status"></p>'
  const fields = container.querySelector<HTMLDivElement>('div')!, apply = container.querySelector<HTMLButtonElement>('button')!, status = container.querySelector<HTMLElement>('p')!
  const names = [['x', '横向位置'], ['y', '纵向位置'], ['width', '宽度'], ['height', '高度'], ['rotationDeg', '旋转角度']] as const
  for (const [name, label] of names) {
    const field = document.createElement('label'); field.textContent = label
    const input = document.createElement('input'); input.type = 'number'; input.name = name; input.step = 'any'; field.append(input); fields.append(field)
  }
  host.append(container)
  let part: MasterTextPart | undefined, selected: MasterTextPart['elements'][number] | undefined, disposed = false
  apply.addEventListener('click', () => {
    try {
      if (disposed || !part || !selected?.transformEditable || !selected.transformValue) return
      if (!options.isCurrent()) throw Error('来源或草稿已变化，请关闭并重新打开母版视图')
      const box = Object.fromEntries(names.map(([name]) => [name, Number(fields.querySelector<HTMLInputElement>(`[name=${name}]`)!.value)])) as { x: number; y: number; width: number; height: number; rotationDeg: number }
      if (Object.values(box).some(value => !Number.isFinite(value)) || box.width <= 0 || box.height <= 0 || Math.abs(box.x) > 100000 || Math.abs(box.y) > 100000 || box.width > 100000 || box.height > 100000 || Math.abs(box.rotationDeg) > 360) throw Error('位置/尺寸需在 0 至 100000 像素内，旋转需在 ±360 度内')
      const source = selected.transformValue, previous = options.edits.findIndex(edit => edit.kind === 'setTransform' && edit.partPath === part!.partPath && edit.spid === selected!.spid)
      const edits = options.edits.filter(edit => !(edit.kind === 'setTransform' && edit.partPath === part!.partPath && edit.spid === selected!.spid))
      if (JSON.stringify(box) !== JSON.stringify(source)) edits.splice(previous < 0 ? edits.length : previous, 0, { kind: 'setTransform', partPath: part.partPath, spid: selected.spid, box })
      if (JSON.stringify(edits) === JSON.stringify(options.edits)) { status.textContent = '几何未变化，未新增草稿操作'; return }
      options.onApply(edits)
    } catch (error) { status.textContent = error instanceof Error ? error.message : '母版对象几何未能加入草稿' }
  })
  return {
    update(value?: MasterTextPart, element?: MasterTextPart['elements'][number]) {
      part = value; selected = element
      const pending = options.edits.find(edit => edit.kind === 'setTransform' && edit.partPath === part?.partPath && edit.spid === selected?.spid)
      const box = pending?.kind === 'setTransform' ? pending.box : selected?.transformValue
      for (const [name] of names) fields.querySelector<HTMLInputElement>(`[name=${name}]`)!.value = box ? String(box[name]) : ''
      for (const input of fields.querySelectorAll('input')) input.disabled = !selected?.transformEditable
      apply.disabled = !selected?.transformEditable
      status.textContent = selected?.transformEditable ? `${pending ? '草稿' : '来源'}几何` : '当前对象几何不可写'
    },
    dispose() { disposed = true; container.remove() },
  }
}
