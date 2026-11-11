import { useState } from 'react'
import { PAGE_NUMBER_FORMATS, type SectionValues } from './docx-operations'

/** 布局页与插入菜单共用同一页码校验和格式列表。 */
export function DocxPageNumberDialog({ format, start, label, onChange, onClose }: {
  format?: string | null; start?: number | null; label?: string
  onChange(values: SectionValues): void; onClose(): void
}) {
  const [numberFormat, setNumberFormat] = useState(format ?? 'decimal')
  const [numberStart, setNumberStart] = useState(start == null ? '' : String(start))
  return <div role="dialog" aria-modal="true" aria-label="页码格式" className="modal-overlay" onKeyDown={event => { if (event.key === 'Escape') onClose() }}><form className="modal-card" onSubmit={event => {
    event.preventDefault()
    if (numberStart !== '' && (!/^\d+$/.test(numberStart) || !Number.isSafeInteger(Number(numberStart)))) return
    onChange({ pageNumberFmt: numberFormat === 'decimal' ? null : numberFormat, pageNumberStart: numberStart === '' ? null : Number(numberStart) })
    onClose()
  }}><h3>页码格式</h3><p>{label ?? '当前节'}</p>
    <label>编号格式<select aria-label="页码编号格式" value={numberFormat} onChange={event => setNumberFormat(event.currentTarget.value)}>{PAGE_NUMBER_FORMATS.map((value, index) => <option key={value} value={value}>{['1, 2, 3, …', '— 1 —, — 2 —, …', 'a, b, c, …', 'A, B, C, …', 'i, ii, iii, …', 'I, II, III, …', '一, 二, 三, …'][index]}</option>)}</select></label>
    <label>起始页码<input aria-label="起始页码" type="number" min="0" step="1" value={numberStart} onChange={event => setNumberStart(event.currentTarget.value)} placeholder="留空以续前节" /></label><p>留空以续前节</p>
    <button type="button" data-source-action="page-number-cancel" onMouseDown={event => event.preventDefault()} onClick={onClose}>取消</button><button type="submit" onMouseDown={event => event.preventDefault()}>确定</button>
  </form></div>
}
