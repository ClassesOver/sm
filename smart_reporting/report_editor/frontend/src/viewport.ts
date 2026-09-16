export type ToolbarMode = 'compact' | 'full'

export function toolbarMode(width: number): ToolbarMode {
  return width <= 768 ? 'compact' : 'full'
}
