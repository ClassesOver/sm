import { readFile, writeFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { buildDeckPptx, type DeckSpec } from '../packages/pipelines/src/slides/deck-spec.ts'
import { SPEC_CANVAS_H } from '../packages/pipelines/src/slides/page-spec.ts'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'
import { openPptx, savePptx, setSlideNotes } from '@genoffice/pptx-engine'
import { HeuristicMetrics, imageAspect, layoutText } from '@genoffice/pptx-render'

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

function chartBulletHeight(value: string) {
  const layout = layoutText({
    body: {
      paragraphs: [{ runs: [{ text: value, fontSize: 17 }] }],
      wrap: true, anchor: 'top', insets: { l: 0, t: 0, r: 0, b: 0 },
    },
    boxWidthPx: 520, boxHeightPx: SPEC_CANVAS_H, metrics: new HeuristicMetrics(),
    vp: { widthPx: 1280, heightPx: SPEC_CANVAS_H, scale: 1 },
  })
  return Math.max(54, Math.ceil(Math.max(layout.contentHeight, layout.inkBottom ?? 0)) + 4)
}

const inputPath = process.argv[2]
if (!inputPath) throw new Error('input JSON path required')
const input = JSON.parse(await readFile(inputPath, 'utf8')) as Input
const colors = palettes[input.theme]
const chartUrls = input.slides.map((slide) => slide.chartPath ? pathToFileURL(slide.chartPath).href : undefined)
const charts = new Map<string, { bytes: Buffer; ext: string; aspect: number } | null>()
for (const url of new Set(chartUrls)) {
  if (!url) continue
  const file = new URL(url)
  const bytes = await readFile(file).catch(() => null)
  const ext = /\.jpe?g$/i.test(file.pathname) ? 'jpg' : 'png'
  charts.set(url, bytes ? {
    bytes, ext, aspect: imageAspect(`data:image/${ext};base64,${bytes.subarray(0, 64 * 1024).toString('base64')}`),
  } : null)
}
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
    const bullets = slide.chartPath ? slide.bullets : slide.bullets.slice(0, 5)
    const heights = bullets.map((bullet) => slide.chartPath ? chartBulletHeight(bullet) : 54)
    const gap = slide.chartPath && bullets.length > 1
      ? Math.max(8, Math.min(18, (466 - heights.reduce((sum, height) => sum + height, 0)) / (bullets.length - 1)))
      : 18
    let bulletY = 174
    const elements: DeckSpec['pages'][number]['elements'] = [
      { type: 'shape' as const, shape: 'rect', x: 72, y: 76, w: 8, h: 50, fill: colors.accent },
      text(100, 76, 1080, 52, slide.title, 25, colors.ink, true),
      { type: 'shape' as const, shape: 'line', x: 100, y: 148, w: 1080, h: 1, stroke: { color: '#D5DEDF', widthPt: 1 } },
      ...bullets.flatMap((bullet, bulletIndex) => {
        const y = bulletY
        const height = heights[bulletIndex]!
        bulletY += height + gap
        return [
          { type: 'shape' as const, shape: 'ellipse', x: 112, y: y + 16, w: 10, h: 10, fill: colors.accent },
          text(140, y, slide.chartPath ? 520 : 1020, height, bullet, 17, colors.ink),
        ]
      }),
      text(1090, 660, 100, 24, `${index + 2}`, 10, colors.muted),
    ]
    const url = chartUrls[index]
    if (url) {
      const aspect = charts.get(url)?.aspect ?? 460 / 320
      const w = Math.min(460, 320 * aspect)
      const h = w / aspect
      elements.push({ type: 'image' as const, url, x: 700 + (460 - w) / 2, y: 220 + (320 - h) / 2, w, h })
    }
    return { background: colors.background, elements }
  }),
]

const deck = await buildDeckPptx({ pages }, {
  fetchImage: async (url) => charts.get(url) ?? null,
})
const opened = await openPptx(deck.bytes)
setSlideNotes(opened, 0, `报告期间：${input.period}`)
for (const [index, slide] of input.slides.entries()) {
  setSlideNotes(opened, index + 1, `分析证据：${(slide.evidenceIds ?? []).join(', ') || '未登记'}`)
}
const bytes = await savePptx(opened)
await writeFile(input.output, bytes)
let issues: { page: number; message: string }[]
try {
  const audited = await auditDeck(bytes)
  issues = audited.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message })))
} catch (error) {
  issues = [{ page: 0, message: `PPTX layout audit failed: ${error instanceof Error ? error.message : String(error)}` }]
}
process.stdout.write(JSON.stringify({ slideCount: pages.length, issues }))
