import { CellValueType, type CellValue, type ICellData, type IRange, type Nullable } from '@univerjs/core'
import { dedupeRows, type DedupeValue } from './workbook-vendor/core/dedupe'
import { createModal } from './modal'

type DedupeRange = { getRange(): IRange; getCellDatas(): Nullable<ICellData>[][]; getValues(): Nullable<CellValue>[][] }
export function planWorkbookDedupe(active: DedupeRange, hasHeader: boolean) {
  const range = active.getRange(), height = range.endRow - range.startRow + 1, width = range.endColumn - range.startColumn + 1
  if (height < 2) throw new Error('请选择至少两行数据')
  if (height * width > 2000) throw new Error('删除重复值单次最多处理 2000 个单元格，请缩小选区')
  const cells = active.getCellDatas()
  const values = active.getValues().map((row, r) => Array.from({ length: width }, (_, c) => {
    const cell = cells[r]?.[c]
    if ((cell?.f || cell?.si) && (row[c] === null || row[c] === undefined)) throw new Error('选区公式尚无可读取的计算结果，请先重新计算后再删除重复值')
    const value = row[c] ?? null
    return cells[r]?.[c]?.t === CellValueType.BOOLEAN && (value === 0 || value === 1) ? value === 1 : value
  }))
  const result = dedupeRows(values, hasHeader)
  const value: Record<number, Record<number, ICellData>> = {}
  if (!result.removed) return { value, removed: 0 }
  for (let r = 0; r < height; r++) {
    const row: DedupeValue[] = result.rows[r] ?? Array.from({ length: width }, () => null)
    if (r < result.rows.length && row.every((item, c) => item === values[r]?.[c])) continue
    for (let c = 0; c < width; c++) {
      const v = row[c] ?? null
      ;(value[range.startRow + r] ??= {})[range.startColumn + c] = {
        v, f: null, si: null, p: null,
        t: typeof v === 'string' ? CellValueType.STRING : typeof v === 'boolean' ? CellValueType.BOOLEAN : CellValueType.NUMBER,
      }
    }
  }
  return { value, removed: result.removed }
}

/** 固定源 RemoveDuplicatesDialog：整行比较、默认保留标题。 */
export function createDedupeDialog(root: HTMLElement, apply: (hasHeader: boolean) => void) {
  const modal = createModal({ root, label: '删除重复值', closeLabel: '关闭', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog', content: `
    <h2>删除重复值</h2><form class="workbook-ribbon-format-form">
      <p>比较所选区域的所有列，文本不区分大小写。保留首次出现的行，清空选区尾部；移动的公式转为计算值。</p>
      <label><input type="checkbox" checked>数据包含标题</label>
      <p role="alert" class="workbook-ribbon-format-error"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" data-cancel>取消</button><button type="submit">确定</button></div>
    </form>` })
  const header = modal.card.querySelector<HTMLInputElement>('input')!, error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('[data-cancel]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { apply(header.checked); modal.close() } catch (cause) { error.textContent = (cause as Error).message }
  })
  return { open() { header.checked = true; error.textContent = ''; modal.open(header) }, dispose: modal.remove }
}
