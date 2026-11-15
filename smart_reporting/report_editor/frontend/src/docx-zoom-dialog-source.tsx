// GenOffice docs/src/renderer/components/ZoomDialog.tsx, mounted in the browser's shared modal.
import { useState } from 'react'
import { useI18n } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/locale'
import { buttonClasses } from './button'
import { clampZoom } from './docx-view-wheel'

export const DOCX_ZOOM_MIN = 10
export const DOCX_ZOOM_MAX = 500
export type DocxZoomFit = 'width' | 'text' | 'page'

const PRESETS = [200, 100, 75] as const
type Preset = (typeof PRESETS)[number]
type Choice = Preset | DocxZoomFit | 'custom'

interface ZoomDialogProps {
  zoom: number
  fitValue: (mode: DocxZoomFit) => number | null
  onApply: (target: number | DocxZoomFit) => void
  onClose: () => void
}

function isPreset(n: number): n is Preset {
  return (PRESETS as readonly number[]).includes(n)
}

export function DocxZoomDialog({ zoom, fitValue, onApply, onClose }: ZoomDialogProps) {
  const { t } = useI18n()
  const start = Math.round(zoom)
  const [choice, setChoice] = useState<Choice>(isPreset(start) ? start : 'custom')
  const [percent, setPercent] = useState(String(start))

  const pick = (c: Choice) => {
    setChoice(c)
    if (typeof c === 'number') setPercent(String(c))
    else if (c !== 'custom') {
      const v = fitValue(c)
      if (v != null) setPercent(String(v))
    }
  }
  const commitPercent = () => {
    const typed = percent.trim() === '' ? NaN : Number(percent)
    const n = clampZoom(Number.isFinite(typed) ? Math.round(typed) : start, DOCX_ZOOM_MIN, DOCX_ZOOM_MAX)
    setPercent(String(n))
    return n
  }
  const submit = () => {
    if (typeof choice === 'string' && choice !== 'custom') onApply(choice)
    else onApply(commitPercent())
    onClose()
  }
  const radio = (c: Preset | DocxZoomFit, label: string) => (
    <label className="zoom-dialog-radio">
      <input type="radio" name="zoom-to" checked={choice === c} disabled={typeof c === 'string' && fitValue(c) == null} onChange={() => pick(c)} />
      {label}
    </label>
  )

  return (
    <form className="zoom-dialog" noValidate onSubmit={(e) => { e.preventDefault(); submit() }}>
      <h2>{t('ribbonZoomDialog')}</h2>
      <fieldset className="zoom-dialog-group">
        <legend>{t('ribbonZoomTo')}</legend>
        <div className="zoom-dialog-radios">
          {radio(200, '200%')}
          {radio('width', t('ribbonPageWidth'))}
          {radio(100, '100%')}
          {radio('text', t('ribbonZoomTextWidth'))}
          {radio(75, '75%')}
          {radio('page', t('ribbonWholePage'))}
          <label className="zoom-dialog-radio"><input type="radio" name="zoom-to" disabled />{t('ribbonMultiPage')}</label>
        </div>
      </fieldset>
      <label className="zoom-dialog-percent">
        <span>{t('ribbonZoomPercent')}</span>
        <input
          type="number"
          aria-label="显示比例（%）"
          min={DOCX_ZOOM_MIN}
          max={DOCX_ZOOM_MAX}
          step={1}
          value={percent}
          onChange={(e) => {
            setPercent(e.target.value)
            const n = Number(e.target.value)
            setChoice(isPreset(n) ? n : 'custom')
          }}
          onBlur={commitPercent}
        />
        <span>%</span>
      </label>
      <div className="zoom-dialog-actions">
        <button type="button" className={buttonClasses('secondary')} onClick={onClose}>{t('ribbonCancel')}</button>
        <button type="submit" className={buttonClasses('primary')}>{t('ribbonOk')}</button>
      </div>
    </form>
  )
}
