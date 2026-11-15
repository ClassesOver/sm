// From the pinned GenOffice Slides renderer components/ribbon-shared.tsx.
const STYLE_ACCENTS = [
  '#5A5A5A',
  '#C43E1C',
  '#E97132',
  '#FFC000',
  '#4EA72E',
  '#0F9ED5',
  '#0A50A1',
  '#7030A0',
]

/** Blend a hex color toward white (f > 0) or black (f < 0) */
function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const ch = (v: number) => Math.round(f >= 0 ? v + (255 - v) * f : v * (1 + f))
  const rgb = (ch((n >> 16) & 255) << 16) | (ch((n >> 8) & 255) << 8) | ch(n & 255) | (1 << 24)
  return `#${rgb.toString(16).slice(1).toUpperCase()}`
}

interface ShapeStylePreset {
  fill: string
  stroke: string
  dash?: 'dash'
}

export const RIBBON_SHAPE_STYLES: ShapeStylePreset[] = [
  ...STYLE_ACCENTS.map((c) => ({ fill: '#FFFFFF', stroke: c })),
  ...STYLE_ACCENTS.map((c) => ({ fill: shade(c, 0.8), stroke: c })),
  ...STYLE_ACCENTS.map((c) => ({ fill: c, stroke: shade(c, -0.35) })),
  ...STYLE_ACCENTS.map((c) => ({ fill: '#FFFFFF', stroke: c, dash: 'dash' as const })),
]
