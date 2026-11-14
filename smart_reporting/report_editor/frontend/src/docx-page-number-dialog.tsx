import { useLayoutEffect, useRef, useState } from 'react'
import { PAGE_NUMBER_FORMATS, type SectionChangeResult, type SectionValues } from './docx-operations'
import { installFocusTrap } from './focus-trap'
import { buttonClasses } from './button'

/** 布局页与插入菜单共用同一页码校验和格式列表。 */
export function DocxPageNumberDialog({ format, start, label, disabledReason, onChange, onClose }: {
  format?: string | null; start?: number | null; label?: string; disabledReason?: string
  onChange(values: SectionValues): SectionChangeResult; onClose(): void
}) {
  const [numberFormat, setNumberFormat] = useState(format ?? 'decimal')
  const [numberStart, setNumberStart] = useState(start == null ? '' : String(start))
  const [error, setError] = useState('')
  const [commitError, setCommitError] = useState('')
  const overlay = useRef<HTMLDivElement>(null)
  const status = useRef<HTMLParagraphElement>(null)
  // 浏览器禁用按钮时先失焦，保留该次焦点来源供布局阶段恢复。
  const confirmationFocused = useRef(false)
  useLayoutEffect(() => {
    if (disabledReason && confirmationFocused.current) { confirmationFocused.current = false; status.current?.focus() }
  }, [disabledReason])
  useLayoutEffect(() => {
    const dialog = overlay.current!, opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const release = installFocusTrap(dialog)
    dialog.querySelector('select')?.focus()
    return () => { release(); if (opener?.isConnected) opener.focus({ preventScroll:true }) }
  }, [])
  return <div ref={overlay} role="dialog" aria-modal="true" aria-label="页码格式" className="modal-overlay" onKeyDown={event => { if (event.nativeEvent.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.key === 'Escape') { event.preventDefault(); onClose() } }}><section className="modal-card docx-settings-dialog docx-page-number-dialog">
    <button type="button" aria-label="关闭页码格式" className={`modal-close ${buttonClasses('quiet', true)}`} onClick={onClose}><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
    <h2>页码格式</h2><form onSubmit={event => {
    event.preventDefault()
    if (disabledReason) return
    if (numberStart !== '' && (!/^\d+$/.test(numberStart) || !Number.isSafeInteger(Number(numberStart)))) { setError('起始页码必须为0或正整数，且不能超过9007199254740991。'); return }
    try {
      const result = onChange({ pageNumberFmt: numberFormat === 'decimal' ? null : numberFormat, pageNumberStart: numberStart === '' ? null : Number(numberStart) })
      if (result?.error) { setCommitError(result.error); return }
    }
    catch (error) { setCommitError(error instanceof Error ? error.message : String(error)); return }
    onClose()
  }}><p>{label ?? '当前节'}</p>
    <label>编号格式<select aria-label="页码编号格式" value={numberFormat} onChange={event => setNumberFormat(event.currentTarget.value)}>{PAGE_NUMBER_FORMATS.map((value, index) => <option key={value} value={value}>{['1, 2, 3, …', '— 1 —, — 2 —, …', 'a, b, c, …', 'A, B, C, …', 'i, ii, iii, …', 'I, II, III, …', '一, 二, 三, …'][index]}</option>)}</select></label>
    <label>起始页码<input aria-label="起始页码" aria-invalid={error ? true : undefined} type="number" min="0" step="1" value={numberStart} onChange={event => { setNumberStart(event.currentTarget.value); setError('') }} placeholder="留空以续前节" /></label><p>留空以续前节</p>
    <p ref={status} role="alert" aria-live="polite" tabIndex={-1}>{disabledReason || commitError || error}</p>
    <button type="button" data-source-action="page-number-cancel" data-action="cancel" className={buttonClasses('secondary')} onMouseDown={event => event.preventDefault()} onClick={onClose}>取消</button><button type="submit" disabled={!!disabledReason} className={buttonClasses('primary')} onFocus={() => { confirmationFocused.current = true }} onBlur={event => { if (!event.currentTarget.disabled) confirmationFocused.current = false }} onMouseDown={event => event.preventDefault()}>确定</button>
  </form></section></div>
}
