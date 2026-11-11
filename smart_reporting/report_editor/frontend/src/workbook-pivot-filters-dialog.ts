import { createModal } from './modal'
import { parseAddress, formatAddress } from '@sheets-web/xlsx-engine'
import { readPivotControls, type PivotControl, type PivotControlRequest } from '@sheets-web/xlsx-engine/pivot-controls'
import type { PivotConfig, WorkbookPivot } from './workbook-pivot'
import { readPivotFilterFields, pivotMemberFilterConfig, pivotTimelineFilterConfig, PIVOT_FILTER_SAVE_NOTICE, type PivotFilterField } from './workbook-pivot-filters'

interface Input { bytes: Uint8Array; pivots: WorkbookPivot[]; selectedTablePath?: string; mode: 'slicer' | 'timeline' }

export function createPivotFilterDialog(root: HTMLElement, apply: (config: PivotConfig, tablePath: string, control?: PivotControlRequest) => Promise<void>, remove?: (control: PivotControl) => Promise<void>) {
  let input: Input, selected: WorkbookPivot | undefined, fields: PivotFilterField[] = [], busy = false, epoch = 0, controls: PivotControl[] = []
  const modal = createModal({ root, label: '透视表筛选', closeLabel: '关闭透视表筛选', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', onRequestClose: () => { if (!busy) { epoch++; modal.close() } }, content:
    '<h2 data-title></h2><form class="workbook-ribbon-format-form"><label>选择透视表<select aria-label="筛选透视表"></select></label><label>筛选字段<select aria-label="筛选字段"></select></label><div data-selection><button type="button" data-action="all">全选</button><div data-members></div></div><div data-dates><label>开始日期<input type="date" aria-label="开始日期"></label><label>结束日期<input type="date" aria-label="结束日期"></label></div><button type="button" data-action="reset">清除当前字段的成员筛选</button><fieldset><legend>Excel 原生控件</legend><label><input type="checkbox" data-native-control>保存原生控件</label><label>控件名称<input aria-label="控件名称"></label><label>控件标题<input aria-label="控件标题"></label><label>左上角单元格<input data-control-geometry aria-label="控件左上角单元格" placeholder="H1"></label><label>宽度（像素）<input type="number" min="96" max="2000" step="1" data-control-geometry aria-label="控件宽度（像素）"></label><label>高度（像素）<input type="number" min="80" max="2000" step="1" data-control-geometry aria-label="控件高度（像素）"></label><button type="button" data-action="delete-control" hidden>删除原生控件，保留当前筛选</button></fieldset><p data-notice></p><p role="alert" class="workbook-ribbon-format-error"></p><div class="workbook-ribbon-format-actions"><button type="button" data-action="cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">应用筛选</button></div></form>' })
  const find = <T extends HTMLElement>(selector: string) => modal.card.querySelector<T>(selector)!
  const pivots = find<HTMLSelectElement>('[aria-label="筛选透视表"]'), chooser = find<HTMLSelectElement>('[aria-label="筛选字段"]'), error = find('[role="alert"]'), members = find('[data-members]'), from = find<HTMLInputElement>('[aria-label="开始日期"]'), to = find<HTMLInputElement>('[aria-label="结束日期"]')
  find('[data-notice]').textContent = PIVOT_FILTER_SAVE_NOTICE
  const option = (value: string, label: string) => { const result = document.createElement('option'); result.value = value; result.textContent = label; return result }
  const setBusy = (value: boolean) => { busy = value; modal.card.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input, select, button').forEach(element => { element.disabled = value || element.matches('[data-control-geometry]') && !find<HTMLInputElement>('[data-native-control]').checked || element.matches('[data-native-control]') && controls.some(control => control.tablePath === selected?.tablePath && control.field === chooser.value && control.kind === input.mode) }) }
  const render = () => {
    members.replaceChildren(); error.textContent = ''; from.value = to.value = ''
    const field = fields.find(field => field.name === chooser.value)
    if (!field || !selected) return
    const owned = controls.find(control => control.tablePath === selected!.tablePath && control.field === field.name && control.kind === input.mode)
    find<HTMLButtonElement>('[data-action="delete-control"]').hidden = !owned || !remove
    find<HTMLInputElement>('[data-native-control]').checked = Boolean(owned)
    find<HTMLInputElement>('[data-native-control]').disabled = Boolean(owned)
    find<HTMLInputElement>('[aria-label="控件名称"]').value = owned?.name ?? (input.mode === 'timeline' ? 'Timeline' : 'Slicer') + '_P' + selected.tablePath.match(/(\d+)\.xml$/)?.[1] + '_F' + selected.fieldNames.indexOf(field.name)
    find<HTMLInputElement>('[aria-label="控件标题"]').value = owned?.caption ?? field.name
    const anchor = owned?.anchor ?? { row: selected.location.startRow, column: Math.min(16383, selected.location.endColumn + 2) }
    find<HTMLInputElement>('[aria-label="控件左上角单元格"]').value = formatAddress(anchor.row, anchor.column)
    find<HTMLInputElement>('[aria-label="控件宽度（像素）"]').value = String(anchor.width ?? (input.mode === 'slicer' ? 192 : 480))
    find<HTMLInputElement>('[aria-label="控件高度（像素）"]').value = String(anchor.height ?? (input.mode === 'slicer' ? 260 : 160))
    const hidden = new Set(selected.hiddenMembers?.[field.axis]?.[field.level] ?? [])
    if (input.mode === 'timeline') {
      const dates = field.members.filter(member => member.date && !hidden.has(member.value)).map(member => member.date!).sort()
      from.value = owned?.from ?? dates[0] ?? ''; to.value = owned?.to ?? dates.at(-1) ?? ''
    } else for (const member of field.members) {
      const label = document.createElement('label'), check = document.createElement('input')
      check.type = 'checkbox'; check.value = member.value; check.checked = !hidden.has(member.value)
      label.append(check, document.createTextNode(member.value || '（空白）')); members.append(label)
    }
  }
  const populate = async () => {
    const generation = ++epoch; fields = []; chooser.replaceChildren(); members.replaceChildren(); error.textContent = ''; setBusy(true)
    selected = input.pivots.find(pivot => pivot.tablePath === pivots.value)
    try {
      if (!selected) throw new Error('请选择透视表')
      const available = await readPivotFilterFields(input.bytes, selected)
      controls = await readPivotControls(input.bytes)
      if (generation !== epoch) return
      fields = input.mode === 'timeline' ? available.filter(field => field.timeline) : available
      chooser.replaceChildren(...fields.map(field => option(field.name, field.name)))
      if (!fields.length) throw new Error(input.mode === 'timeline' ? '没有可筛选的日期字段；支持 ISO 日期文本或有日期格式的 Excel 日期序列，分组日期请使用成员筛选。' : '请先将筛选字段放入透视表的行轴或列轴')
      render()
    } catch (cause) { if (generation === epoch) error.textContent = (cause as Error).message }
    finally { if (generation === epoch) setBusy(false) }
  }
  find('[data-native-control]').addEventListener('change', () => { if (!busy) setBusy(false) })
  chooser.addEventListener('change', () => { render(); setBusy(busy) })
  pivots.addEventListener('change', () => { void populate() })
  const submit = (config: PivotConfig) => {
    if (busy || !selected) return
    const existing = controls.find(control => control.tablePath === selected!.tablePath && control.field === chooser.value && control.kind === input.mode)
    let anchor: PivotControlRequest['anchor']
    if (find<HTMLInputElement>('[data-native-control]').checked || existing) {
      try { anchor = parseAddress(find<HTMLInputElement>('[aria-label="控件左上角单元格"]').value.trim().toUpperCase()) }
      catch { throw new Error('控件位置请输入 A1 至 XFD1048576 内的单元格地址') }
      if (!Number.isInteger(anchor.row) || !Number.isInteger(anchor.column) || anchor.row < 0 || anchor.row > 1048575 || anchor.column < 0 || anchor.column > 16383) throw new Error('控件位置超出工作表范围')
      const width = Number(find<HTMLInputElement>('[aria-label="控件宽度（像素）"]').value), height = Number(find<HTMLInputElement>('[aria-label="控件高度（像素）"]').value)
      if (!Number.isInteger(width) || width < 96 || width > 2000 || !Number.isInteger(height) || height < 80 || height > 2000) throw new Error('控件宽度须为 96–2000、高度须为 80–2000 的整数像素')
      anchor = { ...anchor, width, height }
    }
    const control: PivotControlRequest | undefined = (find<HTMLInputElement>('[data-native-control]').checked || existing) ? { kind: input.mode, tablePath: selected.tablePath, field: chooser.value, name: find<HTMLInputElement>('[aria-label="控件名称"]').value.trim(), caption: find<HTMLInputElement>('[aria-label="控件标题"]').value, ...(input.mode === 'timeline' ? { from: from.value, to: to.value } : {}), anchor: anchor! } : undefined
    setBusy(true)
    void apply(config, selected.tablePath, control).then(() => { epoch++; modal.close() }, cause => { error.textContent = (cause as Error).message }).finally(() => { setBusy(false) })
  }
  find('[data-action="delete-control"]').addEventListener('click', () => {
    const control = controls.find(item => item.tablePath === selected?.tablePath && item.field === chooser.value && item.kind === input.mode)
    if (busy || !control || !remove) return
    setBusy(true)
    void remove(control).then(() => { epoch++; modal.close() }, cause => { error.textContent = (cause as Error).message }).finally(() => { setBusy(false) })
  })
  find('[data-action="reset"]').addEventListener('click', () => {
    if (busy || !selected) return
    try {
      if(input.mode === 'timeline'){const dates=fields.find(field=>field.name===chooser.value)?.members.flatMap(member=>member.date?[member.date]:[]).sort()??[];from.value=dates[0]??'';to.value=dates.at(-1)??''}
      submit(pivotMemberFilterConfig(selected, fields, chooser.value, fields.find(field => field.name === chooser.value)?.members.map(member => member.value) ?? []))
    }
    catch (cause) { error.textContent = (cause as Error).message }
  })
  find('[data-action="all"]').addEventListener('click', () => { members.querySelectorAll<HTMLInputElement>('input').forEach(check => { check.checked = true }) })
  find('[data-action="cancel"]').addEventListener('click', () => { if (!busy) { epoch++; modal.close() } })
  find('form').addEventListener('submit', event => {
    event.preventDefault()
    if (busy || !selected) return
    try {
      const config = input.mode === 'timeline' ? pivotTimelineFilterConfig(selected, fields, chooser.value, from.value, to.value) : pivotMemberFilterConfig(selected, fields, chooser.value, [...members.querySelectorAll<HTMLInputElement>('input:checked')].map(check => check.value))
      submit(config)
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    async open(value: Input) {
      if (!value.pivots.length) throw new Error('当前工作簿没有可筛选的数据透视表')
      input = value
      find('[data-title]').textContent = value.mode === 'timeline' ? '时间线：日期区间筛选' : '切片器：透视成员筛选'
      find('[data-selection]').hidden = value.mode === 'timeline'; find('[data-dates]').hidden = value.mode !== 'timeline'
      pivots.replaceChildren(...value.pivots.map(pivot => option(pivot.tablePath, pivot.name + ' · ' + pivot.targetSheetName)))
      pivots.value = value.pivots.find(pivot => pivot.tablePath === value.selectedTablePath)?.tablePath ?? value.pivots[0]!.tablePath
      modal.open(pivots); await populate()
    },
    dispose() { epoch++; modal.remove() },
  }
}
