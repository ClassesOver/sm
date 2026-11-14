import { useEffect, useRef, useState } from 'react'
import { useI18n, type StringKey } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { useModalKeys } from './vendor/genoffice-docs/apps/docs/src/renderer/components/modal-keys'
import { LengthInput } from './vendor/genoffice-docs/apps/docs/src/renderer/components/LengthInput'

import { marginsFitPage, type PageMargins } from './docx-page-setup'
type Side = 'top' | 'bottom' | 'left' | 'right'

const SIDES: Array<[Side, StringKey]> = [
  ['top', 'ribbonMarginTop'],
  ['bottom', 'ribbonMarginBottom'],
  ['left', 'ribbonMarginLeft'],
  ['right', 'ribbonMarginRight'],
]

export function MarginDialog({
  margins,
  disabledReason, mirrorReason,
  mirror: initialMirror,
  pageWidth,
  pageHeight,
  onApply,
  onClose,
}: {
  disabledReason?: string
  mirrorReason?: string
  margins: PageMargins
  /** w:mirrorMargins: left/right are inside/outside (Word's Multiple pages: Mirror margins) */
  mirror: boolean
  pageWidth: number
  pageHeight: number
  onApply: (next: PageMargins, mirror: boolean) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [error, setError] = useState('')
  const [next, setNext] = useState<PageMargins>(margins)
  const [mirror, setMirror] = useState(initialMirror)
  // Enter inside a field commits its value first; submit runs on the flushed state
  const [submitTick, setSubmitTick] = useState(0)
  const modalKeys = useModalKeys(onClose)
  const tooLarge = !marginsFitPage(next, pageWidth, pageHeight)

  const submit = () => {
    if (tooLarge || disabledReason) return
    try { onApply(next, mirror); onClose() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const submitRef = useRef(submit)
  submitRef.current = submit
  useEffect(() => {
    if (submitTick) submitRef.current()
  }, [submitTick])

  const sideLabel = (side: Side, labelKey: StringKey): string => {
    if (!mirror) return t(labelKey)
    return t(
      side === 'left' ? 'ribbonMarginInside' : side === 'right' ? 'ribbonMarginOutside' : labelKey,
    )
  }
  const field = ([side, labelKey]: [Side, StringKey]) => (
    <label key={side}>
      {sideLabel(side, labelKey)}
      <LengthInput
        value={next[side]}
        min={0}
        max={side === 'left' || side === 'right' ? pageWidth : pageHeight}
        ariaLabel={sideLabel(side, labelKey)}
        live
        disabled={!!disabledReason}
        onCommit={(twips) => setNext((m) => ({ ...m, [side]: twips ?? 0 }))}
        onEnter={() => setSubmitTick((n) => n + 1)}
      />
    </label>
  )

  return (
    <div
      role="dialog" aria-modal="true" aria-label={t('ribbonMarginDialogTitle')}
      className="modal-backdrop"
      ref={modalKeys.ref}
      onKeyDown={modalKeys.onKeyDown}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal">
        <h2>{t('ribbonMarginDialogTitle')}</h2>
        <div className="modal-row margin-row">{SIDES.slice(0, 2).map(field)}</div>
        <div className="modal-row margin-row">{SIDES.slice(2).map(field)}</div>
        <div className="modal-row margin-row">
          <label>
            {t('ribbonMarginPages')}
            <select
              aria-label={t('ribbonMarginPages')} disabled={!!disabledReason || !!mirrorReason} title={mirrorReason}
              value={mirror ? 'mirror' : 'normal'}
              onChange={(e) => setMirror(e.target.value === 'mirror')}
            >
              <option value="normal">{t('ribbonMarginPagesNormal')}</option>
              <option value="mirror">{t('ribbonMarginPagesMirror')}</option>
            </select>
          </label>
        </div>
        {(disabledReason || error) && <p role="alert">{disabledReason || error}</p>}
        {tooLarge && <div className="modal-error">{t('ribbonMarginTooLarge')}</div>}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={onClose}>
            {t('appCancel')}
          </button>
          <button className="btn-primary" data-page-setup-apply disabled={tooLarge || !!disabledReason} onClick={submit}>
            {t('appOk')}
          </button>
        </div>
      </div>
    </div>
  )
}
