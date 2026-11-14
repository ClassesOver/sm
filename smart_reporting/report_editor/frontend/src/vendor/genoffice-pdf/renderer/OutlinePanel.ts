// Type-only excerpt from apps/pdf/src/renderer/OutlinePanel.tsx at f8c17004fb730df11f0f743164ffd8b4281bb38c.
export interface OutlineNode {
  title: string
  bold?: boolean
  italic?: boolean
  dest?: unknown
  url?: string
  items?: OutlineNode[]
}
