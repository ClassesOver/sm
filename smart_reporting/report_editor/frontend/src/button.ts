export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger'

export function buttonClasses(variant: ButtonVariant = 'secondary', iconOnly = false): string {
  return ['ui-button', `ui-button--${variant}`, iconOnly ? 'ui-button--icon' : ''].filter(Boolean).join(' ')
}
