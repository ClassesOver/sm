/** 固定源 shared/ipc.ts 动画类型摘录；无IPC实现。 */
export type AnimDirection = 'top' | 'bottom' | 'left' | 'right'

export type AnimEffectKind =
  | 'appear'
  | 'fade'
  | 'flyIn'
  | 'wipe'
  /** Write-compatible alias for wipe with direction 'top' (the same preset subtype). */
  | 'wipeDown'
  | 'splitIn'
  | 'bounce'
  | 'flipIn'
  | 'zoom' // entrance
  | 'pulse'
  | 'spin'
  | 'grow'
  | 'teeter' // emphasis
  | 'disappear'
  | 'fadeOut'
  | 'flyOut'
  | 'wipeOut'
  | 'shrink'
  | 'zoomOut' // exit
  | 'motionPath' // motion path (move along a path)
  | 'mediaPlay'
  | 'mediaPause'
  | 'mediaStop' // media commands on a video/audio shape

export type AnimTrigger = 'onClick' | 'withPrev' | 'afterPrev'

/** One animation (list order = play order); sourceId locates the target element. */
export interface AnimationItem {
  sourceId: string
  /** Target element display name (shown in the animation pane, filled by the main process) */
  targetName: string
  effect: AnimEffectKind
  trigger: AnimTrigger
  durationMs: number
  delayMs: number
  /** Path when effect='motionPath' (SVG subset M/L/C/Z, coordinates 0..1 relative to slide width/height) */
  motionPath?: string
  /** Wipe/fly direction (enters only when the engine models one); the player reads it
   *  so a top wipe does not play bottom-up. Defaults per effect when absent. */
  direction?: AnimDirection
  /** Per-paragraph animation: 0-based paragraph number; default = the whole shape */
  paragraph?: number
}

