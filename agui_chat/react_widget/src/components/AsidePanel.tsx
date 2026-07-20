import { GripVertical, X } from 'lucide-react'
import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState
} from 'react'
import { IconButton } from './IconButton'

const DEFAULT_WIDTH = 620
const MIN_WIDTH = 360
const MAX_WIDTH = 920
const MIN_MAIN_WIDTH = 420
const KEYBOARD_STEP = 24

export interface AsidePanelProps {
  ariaLabel: string
  eyebrow: string
  title: string
  icon: ReactNode
  actions?: ReactNode
  closeLabel: string
  resizeLabel?: string
  onClose: () => void
  children: ReactNode
  className?: string
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
  minMainWidth?: number
}

export function AsidePanel({
  ariaLabel,
  eyebrow,
  title,
  icon,
  actions,
  closeLabel,
  resizeLabel = '调整侧栏宽度',
  onClose,
  children,
  className = '',
  defaultWidth = DEFAULT_WIDTH,
  minWidth = MIN_WIDTH,
  maxWidth = MAX_WIDTH,
  minMainWidth = MIN_MAIN_WIDTH
}: AsidePanelProps) {
  const panelRef = useRef<HTMLElement | null>(null)
  const [width, setWidth] = useState(defaultWidth)

  const clampWidth = useCallback((nextWidth: number) => {
    const panel = panelRef.current
    let main = panel?.previousElementSibling
    while (main?.classList.contains('agui-aside-backdrop')) main = main.previousElementSibling
    const available = main instanceof HTMLElement && panel
      ? main.getBoundingClientRect().width + panel.getBoundingClientRect().width
      : Number.POSITIVE_INFINITY
    const availableMax = Math.max(minWidth, available - minMainWidth)
    return Math.min(Math.max(nextWidth, minWidth), maxWidth, availableMax)
  }, [maxWidth, minMainWidth, minWidth])

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const handleResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = panelRef.current?.getBoundingClientRect().width || width
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handlePointerMove = (moveEvent: PointerEvent) => {
      setWidth(clampWidth(startWidth + startX - moveEvent.clientX))
    }
    const handlePointerUp = () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp, { once: true })
  }, [clampWidth, width])

  const style = { '--agui-aside-width': `${width}px` } as CSSProperties

  return <>
    <button type="button" className="agui-aside-backdrop" aria-label={closeLabel} onClick={onClose} />
    <aside ref={panelRef} className={`agui-aside ${className}`.trim()} style={style} aria-label={ariaLabel}>
      <button
        type="button"
        className="agui-aside-resize"
        aria-label={resizeLabel}
        onPointerDown={handleResizeStart}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') {
            event.preventDefault()
            setWidth((current) => clampWidth(current + KEYBOARD_STEP))
          } else if (event.key === 'ArrowRight') {
            event.preventDefault()
            setWidth((current) => clampWidth(current - KEYBOARD_STEP))
          }
        }}
      >
        <GripVertical size={16} strokeWidth={1.8} />
      </button>
      <header className="agui-aside-head">
        <div className="agui-aside-title">
          <span>{icon}{eyebrow}</span>
          <strong title={title}>{title}</strong>
        </div>
        <div className="agui-aside-actions">
          {actions}
          <IconButton label={closeLabel} size="md" variant="outline" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>
      </header>
      <div className="agui-aside-body">{children}</div>
    </aside>
  </>
}
