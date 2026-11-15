import { useEffect, useRef, useState } from 'react'
import { IconCaret, IconShading } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { RibbonColorPalette } from './vendor/genoffice-docs/apps/docs/src/renderer/components/ribbon-color-palette'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { useDismissablePopover } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
import './vendor/genoffice-slides/ui/color-picker.css'

export function DocxTableShadingSource({ current, reason, onPick }: {
  current: string | null
  reason: string | null
  onPick(fill: string | null): void
}) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const visible = open && !reason
  useEffect(() => { if (reason) setOpen(false) }, [reason])
  useDismissablePopover(visible, () => setOpen(false), { inside: () => [wrap.current], escape: true })
  return (
    <div className="rb-split-wrap" ref={wrap} onKeyDown={event => {
      if (!visible || event.key !== 'Escape' || event.nativeEvent.isComposing) return
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      trigger.current?.focus()
    }}>
      <button type="button" ref={trigger} className="table-command-button" data-action="table-cell-shading"
        aria-label="单元格底纹" aria-expanded={visible} disabled={!!reason} title={reason ?? zh.ribbonGroupShading}
        onMouseDown={event => event.preventDefault()} onClick={() => setOpen(value => !value)}>
        <IconShading />
        <span className="table-command-copy"><span>{zh.ribbonGroupShading}</span></span>
        <IconCaret size={12} />
      </button>
      {visible && <RibbonColorPalette current={current} noneLabel={zh.ribbonNoColor} onPick={fill => {
        setOpen(false)
        onPick(fill)
      }} />}
    </div>
  )
}
