import { useState } from 'react'
import { parseCalibration } from './measure'
import type { TFunc } from './i18n/locale'
import { useModalDialog } from './modal-dialog'

/**
 * First-run calibration for the measure tool: the user draws a line over a
 * distance they know (a doorway, a scale bar) and types what it is in the real
 * world. The scale lives in the session only — the file stays geometry-only,
 * and every measurement recomputes from it at commit time.
 */
export function MeasureScaleDialog({
  t,
  drawnPts,
  onApply,
  onClose,
}: {
  t: TFunc
  /** the reference line's PDF length: the ruler the real length is measured against */
  drawnPts: number
  onApply: (unitsPerPt: number, unit: string) => void | Promise<void>
  onClose: () => void
}): React.JSX.Element {
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('m')
  const [error, setError] = useState<string | null>(null)

  const [busy, setBusy] = useState(false)
  const dialogRef = useModalDialog(onClose)
  const apply = async (): Promise<void> => {
    if (busy) return
    const scale = parseCalibration(value, unit, drawnPts)
    if (!scale) {
      setError(t('measureScaleErr'))
      return
    }
    setBusy(true)
    setError(null)
    try { await onApply(scale.unitsPerPt, scale.unit) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  return (
    <div className="pdf-modal-mask" onClick={onClose}>
      <div
        ref={dialogRef}
        className="pdf-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pdf-modal-title">{t('measureScaleTitle')}</div>
        <div className="pdf-modal-hint">{t('measureScalePrompt')}</div>
        <div className="pdf-field">
          <label className="pdf-perm-row">
            <span>{t('measureScaleValue')}</span>
            <input
              disabled={busy}
              type="number"
              className="pdf-modal-input"
              value={value}
              autoFocus
              step="any"
              min="0"
              onChange={(e) => {
                setValue(e.target.value)
                setError(null)
              }}
            />
          </label>
          <label className="pdf-perm-row">
            <span>{t('measureScaleUnit')}</span>
            <input
              disabled={busy}
              type="text"
              className="pdf-modal-input"
              value={unit}
              maxLength={12}
              onChange={(e) => {
                setUnit(e.target.value)
                setError(null)
              }}
            />
          </label>
          {error && (
            <div className="pdf-cert-error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="pdf-modal-actions">
          <button className="pdf-modal-btn" onClick={onClose}>
            {t('cancel')}
          </button>
          <button className="pdf-modal-btn primary" disabled={busy} onClick={() => void apply()}>
            {t('measureScaleApply')}
          </button>
        </div>
      </div>
    </div>
  )
}
