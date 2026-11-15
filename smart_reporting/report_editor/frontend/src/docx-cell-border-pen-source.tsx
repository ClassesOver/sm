import { useRef, useState } from 'react'
import { DOCX_CELL_BORDER_STYLES, DOCX_CELL_BORDER_WIDTHS, type DocxCellBorderPen } from '../../../reporting/doc_engine/bridge/docx-cell-borders-spec'
import { IconCaret } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { RibbonColorPalette } from './vendor/genoffice-docs/apps/docs/src/renderer/components/ribbon-color-palette'
import { zh } from './vendor/genoffice-docs/apps/docs/src/renderer/i18n/ribbon/zh'
import { Dropdown } from './vendor/genoffice-docs/packages/ui/src/dropdown'
import { useDismissablePopover } from './vendor/genoffice-docs/packages/ui/src/popover-dismiss'
import './vendor/genoffice-docs/packages/ui/src/dropdown.css'

// Source Ribbon.tsx BORDER_STYLE_OPTIONS and border pen widths.
const glyphs = ['─────', '━━━━━', '═════', '≡≡≡≡≡', '┄┄┄┄┄', '╌╌╌╌╌', '─·─·─', '─··─··']
const styles = DOCX_CELL_BORDER_STYLES.map((value, index) => ({ value, label:glyphs[index]! }))
const widths = DOCX_CELL_BORDER_WIDTHS.map(value => ({ value:String(value), label:zh.ribbonPtValue.replace('{n}',String(value/8)) }))

export function DocxCellBorderPenSource({ pen, reason, onChange }: {
  pen: DocxCellBorderPen
  reason: string | null
  onChange(pen: DocxCellBorderPen): void
}) {
  const [open,setOpen] = useState(false)
  const colorWrap = useRef<HTMLDivElement>(null)
  const colorTrigger = useRef<HTMLButtonElement>(null)
  const label = (text: string) => reason ? `${text}，${reason}` : text
  useDismissablePopover(open,()=>setOpen(false),{inside:()=>[colorWrap.current],escape:true})
  return <>
    <div data-action="table-border-style" title={reason ?? undefined}>
      <Dropdown className="table-border-style" value={pen.style} options={styles}
        ariaLabel={label(zh.ribbonBorderStyle)} tip={zh.ribbonBorderStyle} disabled={!!reason}
        onPick={style=>onChange({...pen,style})} />
    </div>
    <div data-action="table-border-width" title={reason ?? undefined}>
      <Dropdown value={String(pen.szEighths)} options={widths}
        ariaLabel={label(zh.ribbonBorderWidth)} tip={zh.ribbonBorderWidth} disabled={!!reason}
        onPick={width=>onChange({...pen,szEighths:Number(width)})} />
    </div>
    <div className="rb-split-wrap" ref={colorWrap} onKeyDown={event=>{
      if(!open || event.key!=='Escape' || event.nativeEvent.isComposing)return
      event.preventDefault();event.stopPropagation();setOpen(false);colorTrigger.current?.focus()
    }}>
      <button type="button" ref={colorTrigger} className={`table-pen-color${open?' active':''}`}
        data-action="table-border-color" title={reason??zh.ribbonBorderColor}
        aria-label={label(zh.ribbonBorderColor)} aria-expanded={open} disabled={!!reason}
        onMouseDown={event=>event.preventDefault()} onClick={()=>setOpen(value=>!value)}>
        <span className="table-pen-swatch" style={{background:`#${pen.color}`}} />
        <IconCaret size={12} />
      </button>
      {open && !reason && <RibbonColorPalette current={pen.color} noneLabel={zh.ribbonAutomatic} onPick={color=>{
        setOpen(false)
        onChange({...pen,color:color??'000000'})
      }} />}
    </div>
  </>
}
