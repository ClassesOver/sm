import { useEffect, useRef, useState } from 'react'
import { IconCaret, IconPageColor } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { RibbonColorPalette } from './vendor/genoffice-docs/apps/docs/src/renderer/components/ribbon-color-palette'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { useDismissablePopover } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'

/** GenOffice DesignTab page color button and the shared Word palette. */
export function DocxPageColorSource({ current, reason, onPick }: {
  current: string | null
  reason: string | null
  onPick(color: string | null): void
}) {
  const [open, setOpen] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const visible = open && !reason
  useEffect(() => { if (reason) setOpen(false) }, [reason])
  useDismissablePopover(visible, () => setOpen(false), { inside: () => [wrapper.current], escape: true })
  return (
    <div className="rb-split-wrap" ref={wrapper} onKeyDown={event => {
      if (!visible || event.key !== 'Escape' || event.nativeEvent.isComposing) return
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      trigger.current?.focus()
    }}>
      <button type="button" ref={trigger} className="rb-big" data-action="page-color"
        aria-label={zh.ribbonPageColor} aria-expanded={visible} aria-description={reason??undefined}
        disabled={!!reason} title={reason??`${zh.ribbonPageColor}：${current?`#${current}`:zh.ribbonNoColor}`}
        onMouseDown={event=>event.preventDefault()} onClick={()=>setOpen(value=>!value)}>
        <span className="rb-big-icon rb-big-icon-colored">
          <IconPageColor size={28} />
          <span className="rb-color-bar" style={{background:current?`#${current}`:'#fff'}} />
          <IconCaret />
        </span>
        <span>{zh.ribbonPageColor}</span>
      </button>
      {visible && <RibbonColorPalette current={current} noneLabel={zh.ribbonNoColor} onPick={color=>{
        setOpen(false)
        onPick(color)
      }} />}
    </div>
  )
}
