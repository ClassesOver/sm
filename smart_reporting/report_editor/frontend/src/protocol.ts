export type ProtocolMarkerKind = 'section' | 'citation' | 'analysis' | 'claim' | 'table' | 'table-close'

export interface ProtocolMarker {
  kind: ProtocolMarkerKind
  raw: string
  value: string
  start: number
  end: number
}

// table 协议块由服务端装配器生成；编辑器侧只读保护并隐藏，避免结束标记被
// Milkdown 表格解析器渲染为表格行。
const MARKER_PATTERN = /\[\[(\/?table|section|citation|analysis|claim):([A-Za-z0-9_.:-]{1,128})\]\]/g

// Milkdown 的 markdown 序列化器会把字面量 [[ 转义为 \[\[（下划线等同理），
// 存储前必须还原，否则正式章节/引用/分析标识在导出渲染时无法识别。
const ESCAPED_MARKER_PATTERN = /\\\[\\\[((?:\\.|[^\]]){1,256})]]/g
const MARKER_VALUE_PATTERN = /^(?:\/table:)?[A-Za-z0-9_.:-]{1,128}$/

export function restoreProtocolMarkers(markdown: string): string {
  return markdown.replace(ESCAPED_MARKER_PATTERN, (raw, inner: string) => {
    const value = inner.replace(/\\(.)/gs, '$1')
    return MARKER_VALUE_PATTERN.test(value) ? `[[${value}]]` : raw
  })
}

export function findProtocolMarkers(markdown: string): ProtocolMarker[] {
  return Array.from(markdown.matchAll(MARKER_PATTERN), (match) => {
    const rawKind = match[1] as ProtocolMarkerKind | '/table'
    const kind: ProtocolMarkerKind = rawKind === '/table' ? 'table-close' : rawKind
    return {
      kind,
      raw: match[0],
      value: match[2],
      start: match.index,
      end: match.index + match[0].length,
    }
  })
}

export function protocolMarkersUnchanged(before: string, after: string): boolean {
  const previous = findProtocolMarkers(before).map((marker) => marker.raw)
  const next = findProtocolMarkers(after).map((marker) => marker.raw)
  return previous.length === next.length && previous.every((value, index) => value === next[index])
}
