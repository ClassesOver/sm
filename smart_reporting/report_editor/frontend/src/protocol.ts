export type ProtocolMarkerKind = 'section' | 'citation'

export interface ProtocolMarker {
  kind: ProtocolMarkerKind
  raw: string
  value: string
  start: number
  end: number
}

const MARKER_PATTERN = /\[\[(section|citation):([A-Za-z0-9_.:-]{1,128})\]\]/g

export function findProtocolMarkers(markdown: string): ProtocolMarker[] {
  return Array.from(markdown.matchAll(MARKER_PATTERN), (match) => ({
    kind: match[1] as ProtocolMarkerKind,
    raw: match[0],
    value: match[2],
    start: match.index,
    end: match.index + match[0].length,
  }))
}

export function protocolMarkersUnchanged(before: string, after: string): boolean {
  const previous = findProtocolMarkers(before).map((marker) => marker.raw)
  const next = findProtocolMarkers(after).map((marker) => marker.raw)
  return previous.length === next.length && previous.every((value, index) => value === next[index])
}
