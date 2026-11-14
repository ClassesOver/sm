/** Apache-2.0 GenOffice f8c17004 shared/ipc.ts: unchanged TextInsertInput excerpt. */
export interface TextInsertInput {
  pageIndex: number
  /** First-line baseline origin in PDF user space. */
  origin: [number, number]
  /** Text to insert; '\n' creates stacked text objects. */
  text: string
  fontSize: number
  color: [number, number, number]
  font?: string
  bold?: boolean
  italic?: boolean
  lineLeading?: number
  lineXOffsets?: number[]
  align?: 'left' | 'center' | 'right'
  /** Final displayed page rotation; insertion matrix counter-rotates text into screen space. */
  rotate?: number
  /** PDF text render mode 3 — present, selectable and searchable, never painted.
      The OCR bake layer's inserts: white glyphs would still show on grey paper,
      photos and dark headers, and light up under selection. */
  invisible?: boolean
}

