// 固定源 App.tsx:205–235 原函数提取；只增加模块导出，不改变正文。
import type { RenderSlide, RenderNode } from '@genoffice/pptx-render'

export function outlineOf(s: RenderSlide): { title: string; lines: string[] } {
  const texts: Array<{ y: number; fontSize: number; text: string }> = []
  const walk = (nodes: readonly RenderNode[]) => {
    for (const n of nodes) {
      if ((n.type === 'shape' || n.type === 'text') && n.text?.lines?.length) {
        const text = n.text.lines
          .map((l) => l.runs.map((r) => r.text).join(''))
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim()
        if (text) {
          texts.push({
            y: n.box?.y ?? 0,
            fontSize: n.text.lines[0]?.runs[0]?.fontSizePx ?? 0,
            text,
          })
        }
      }
      if (n.type === 'group' && Array.isArray(n.children)) walk(n.children)
    }
  }
  walk(s.nodes)
  if (texts.length === 0) return { title: '', lines: [] }
  const title = [...texts].sort((a, b) => b.fontSize - a.fontSize || a.y - b.y)[0]!
  const lines = texts
    .filter((t) => t !== title)
    .sort((a, b) => a.y - b.y)
    .map((t) => t.text)
  return { title: title.text, lines }
}
