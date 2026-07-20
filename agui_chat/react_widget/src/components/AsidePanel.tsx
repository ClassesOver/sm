import { GripVertical, X } from 'lucide-react'
import { type ReactNode, useEffect } from 'react'
import { IconButton } from './IconButton'
import { useAsideResize } from './useAsideResize'

const DEFAULT_WIDTH = 620
const MIN_WIDTH = 360
const MAX_WIDTH = 920
const MIN_MAIN_WIDTH = 420

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
  const resize = useAsideResize({ defaultWidth, minWidth, maxWidth, minMainWidth })

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return <>
    <button type="button" className="agui-aside-backdrop" aria-label={closeLabel} onClick={onClose} />
    <aside ref={resize.panelRef} className={`agui-aside ${className}`.trim()} style={resize.style} aria-label={ariaLabel}>
      <button
        type="button"
        className="agui-aside-resize"
        aria-label={resizeLabel}
        onPointerDown={resize.handleResizeStart}
        onKeyDown={resize.handleResizeKeyDown}
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
