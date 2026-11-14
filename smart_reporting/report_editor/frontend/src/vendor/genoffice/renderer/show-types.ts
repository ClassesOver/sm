import type { NamedAction } from '@genoffice/pptx-engine/named-action'
export type TransitionKind = 'none' | 'morph' | 'fade' | 'push' | 'wipe' | 'split' | 'circle' | 'cover' | 'pull' | 'dissolve' | 'zoom' | 'random'
/** Pinned shared/ipc.ts ShapeKey; missing host cNvPr ids remain null, never invented. */
export interface ShapeKey { sourceId: string; spid: number | null; name: string }
/** Pinned pptx-ops LinkTargetOp. */
export type LinkTargetOp = { kind: 'url'; url: string } | { kind: 'slide'; slideIndex: number } | { kind: 'action'; action: NamedAction }
