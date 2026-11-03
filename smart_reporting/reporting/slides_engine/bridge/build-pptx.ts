import { readFile, writeFile } from 'node:fs/promises'
import { buildDeckPptx, type DeckSpec } from '../packages/pipelines/src/slides/deck-spec.ts'
import { SPEC_CANVAS_H } from '../packages/pipelines/src/slides/page-spec.ts'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'
import { openPptx, savePptx, setSlideNotes } from '@genoffice/pptx-engine'

type Input = {
  output: string
  title: string
  period: string
  theme: 'executive' | 'clinical' | 'modern'
  slides: { title: string; bullets: string[]; evidenceIds?: string[]; chartPath?: string }[]
}

const palettes = {
  executive: { background: '#F4F6F8', ink: '#183247', accent: '#147D75', muted: '#566773' },
  clinical: { background: '#F5F8F7', ink: '#173B36', accent: '#287F70', muted: '#5B706A' },
  modern: { background: '#F7F7F4', ink: '#293846', accent: '#C45A3C', muted: '#5F6B70' },
} as const

function text(x: number, y: number, w: number, h: number, value: string, size: number, color: string, bold = false) {
  return { type: 'text' as const, x, y, w, h, paragraphs: [{ runs: [{ text: value, sizePt: size, color, bold }] }] }
}

const inputPath = process.argv[2]
if (!inputPath) throw new Error('input JSON path required')
const input = JSON.parse(await readFile(inputPath, 'utf8')) as Input
const colors = palettes[input.theme]
const pages: DeckSpec['pages'] = [
  {
    background: colors.background,
    elements: [
      { type: 'shape', shape: 'rect', x: 0, y: 0, w: 18, h: SPEC_CANVAS_H, fill: colors.accent },
      text(96, 220, 1080, 130, input.title, 34, colors.ink, true),
      text(100, 370, 1020, 60, input.period, 18, colors.muted),
      text(100, 620, 1020, 38, '管理分析报告', 12, colors.accent, true),
    ],
  },
  ...input.slides.map((slide, index) => {
    const elements = [
      { type: 'shape' as const, shape: 'rect', x: 72, y: 76, w: 8, h: 50, fill: colors.accent },
      text(100, 76, 1080, 52, slide.title, 25, colors.ink, true),
      { type: 'shape' as const, shape: 'line', x: 100, y: 148, w: 1080, h: 1, stroke: { color: '#D5DEDF', widthPt: 1 } },
      ...slide.bullets.slice(0, 5).map((bullet, bulletIndex) => [
        { type: 'shape' as const, shape: 'ellipse', x: 112, y: 190 + bulletIndex * 72, w: 10, h: 10, fill: colors.accent },
        text(140, 174 + bulletIndex * 72, 1020, 54, bullet, 17, colors.ink),
      ]).flat(),
      text(1090, 660, 100, 24, `${index + 2}`, 10, colors.muted),
    ]
    if (slide.chartPath) {
      elements.push({ type: 'image' as const, url: `file://${slide.chartPath}`, x: 700, y: 220, w: 460, h: 320 })
    }
    return { background: colors.background, elements }
  }),
]

const deck = await buildDeckPptx({ pages }, {
  fetchImage: async (url) => {
    if (!url.startsWith('file://')) return null
    const path = decodeURIComponent(new URL(url).pathname)
    const bytes = new Uint8Array(await readFile(path))
    const ext = path.toLowerCase().endsWith('.jpg') || path.toLowerCase().endsWith('.jpeg') ? 'jpg' : 'png'
    return { bytes, ext }
  },
})
const opened = await openPptx(deck.bytes)
setSlideNotes(opened, 0, `报告期间：${input.period}`)
for (const [index, slide] of input.slides.entries()) {
  setSlideNotes(opened, index + 1, `分析证据：${(slide.evidenceIds ?? []).join(', ') || '未登记'}`)
}
const bytes = await savePptx(opened)
const issues = await auditDeck(bytes)
await writeFile(input.output, bytes)
process.stdout.write(JSON.stringify({ slideCount: pages.length, issues: issues.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message }))) }))
