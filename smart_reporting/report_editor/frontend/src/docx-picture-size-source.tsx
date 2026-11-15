import { useState } from 'react'
import type { createDocxPictureFormatControls } from './docx-picture-format-controls'
import { LengthInput } from './vendor/genoffice-docs/apps/docs/src/renderer/components/LengthInput'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { pxToTwips } from './vendor/genoffice-docs/apps/docs/src/renderer/units'

// GenOffice Ribbon.tsx Picture Format Size bounds.
const PICTURE_TWIPS_MIN = 14
const PICTURE_TWIPS_MAX = 31680
type Controls = ReturnType<typeof createDocxPictureFormatControls>

export function DocxPictureSizeSource({ controls }: { controls: Controls }) {
  const [lockAspect, setLockAspect] = useState(true)
  const size = controls.size()
  const reason = controls.reason()
  const field = (side: 'h' | 'w', label: string, pixels: number | undefined) => (
    <label>
      {label}
      <LengthInput
        value={pixels === undefined ? null : pxToTwips(pixels)}
        min={PICTURE_TWIPS_MIN}
        max={PICTURE_TWIPS_MAX}
        ariaLabel={label}
        disabled={reason !== null || !size}
        onCommit={twips => { if (twips !== null) size?.resize(side, twips, lockAspect) }}
      />
    </label>
  )
  return (
    <>
      <div className="table-tool-row table-size-inputs" key={size?.key}>
        {field('h', zh.ribbonPicHeight, size?.height)}
        {field('w', zh.ribbonPicWidth, size?.width)}
      </div>
      <div className="table-tool-row">
        <label className="table-tool-check">
          <input type="checkbox" checked={lockAspect} disabled={reason !== null || !size} onChange={event => setLockAspect(event.target.checked)} />
          {zh.ribbonLockAspectRatio}
        </label>
        <button type="button" data-action="picture-format-resetSize" disabled={reason !== null} title={reason ?? zh.ribbonResetSizeTip} onClick={() => controls.open('resetSize')}>
          {zh.ribbonResetSize}
        </button>
      </div>
      <div className="ribbon-group-label">{zh.ribbonGroupSize}</div>
    </>
  )
}
