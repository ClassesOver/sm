import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../lib'

interface PickerOptionProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-selected'> {
  active: boolean
  selected?: boolean
  density?: 'compact' | 'default' | 'roomy'
}

export function PickerOption({
  active,
  selected = active,
  density = 'default',
  className,
  children,
  ...props
}: PickerOptionProps) {
  return <button
    type="button"
    role="option"
    aria-selected={selected}
    className={cn(
      'flex w-full items-center gap-2 border-l-2 border-l-transparent bg-white text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary',
      density === 'compact' && 'min-h-10 px-2.5 py-2',
      density === 'default' && 'min-h-11 px-2 py-1.5',
      density === 'roomy' && 'h-12 px-2',
      active && 'border-l-primary bg-background-secondary text-primary',
      className
    )}
    {...props}
  >
    {children}
  </button>
}
