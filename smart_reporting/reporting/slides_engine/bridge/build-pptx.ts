import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import { buildDeckPptx, type DeckSpec } from '../packages/pipelines/src/slides/deck-spec.ts'
import { SPEC_CANVAS_H } from '../packages/pipelines/src/slides/page-spec.ts'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'
import { addElement, addTable, editTableCellText, editTableStyle, openPptx, savePptx, setSlideNotes, setSlideSize } from '@genoffice/pptx-engine'
import { HeuristicMetrics, imageAspect, layoutText } from '@genoffice/pptx-render'

type Input = {
  output: string
  title: string
  period: string
  theme: 'executive' | 'clinical' | 'modern'
  preferences?: any
  slides: { title: string; bullets: string[]; evidenceIds?: string[]; chartPath?: string; tables?: NativeTable[] }[]
}

type NativeTable = { tableId: string; caption: string; headers: string[]; rows: string[][] }
type TablePage = { grid: string[][]; heights: number[]; role: any; hasHeader: boolean; startRow: number; y: number }

const palettes = {
  executive: { background: '#F4F6F8', ink: '#183247', accent: '#147D75', muted: '#566773' },
  clinical: { background: '#F5F8F7', ink: '#173B36', accent: '#287F70', muted: '#5B706A' },
  modern: { background: '#F7F7F4', ink: '#293846', accent: '#C45A3C', muted: '#5F6B70' },
} as const

function text(x: number, y: number, w: number, h: number, value: string, size: number, color: string, bold = false) {
  return { type: 'text' as const, x, y, w, h, paragraphs: [{ runs: [{ text: value, sizePt: size, color, bold }] }] }
}

function chartBulletHeight(value: string, width = 520, size = 17, minimum = 54, lineHeight = 1, bold = false,
  spaceBefore = 0, spaceAfter = 0, fontFamily?: string, indentPt = 0, hardParagraphs = false) {
  const lines = hardParagraphs ? value.split('\n') : [value]
  const layout = layoutText({
    body: {
      paragraphs: lines.map((line, index) => ({ runs: [{ text: line, fontSize: size, bold, fontFamily }],
        lineHeight: lineHeight * 100, spaceBefore: index === 0 ? spaceBefore : 0,
        spaceAfter: index === lines.length - 1 ? spaceAfter : 0, indent: Math.round(indentPt * 12700) })),
      wrap: true, anchor: 'top', insets: { l: 0, t: 0, r: 0, b: 0 },
    },
    boxWidthPx: width, boxHeightPx: SPEC_CANVAS_H, metrics: new HeuristicMetrics(),
    vp: { widthPx: 1280, heightPx: SPEC_CANVAS_H, scale: 1 },
  })
  return Math.max(minimum, Math.ceil(Math.max(layout.contentHeight, layout.inkBottom ?? 0)) + 4)
}

const inputPath = process.argv[2]
if (!inputPath) throw new Error('input JSON path required')
const input = JSON.parse(await readFile(inputPath, 'utf8')) as Input
const prefs = input.preferences
const preferenceWarnings: { page: number; code: string; message: string }[] = []
const finalWidth = (width: number) => width * (prefs?.aspectRatio === '4:3' ? 0.75 : 1)
const roleHeight = (value: string, width: number, role: any, minimum = 0) => chartBulletHeight(
  value, finalWidth(width), role.size, minimum, role.lineHeight, role.bold,
  role.spaceBefore, role.spaceAfter, prefs.fontNames[role.font], role.indent)
// 首段段前遵循 PowerPoint 原生规则；段后需要计入文本框和后续区域预算。
function fitRole(value: string, width: number, requested: any, budget: number) {
  const role = { ...requested }
  while (role.size > 6 && roleHeight(value, width, role) > budget) role.size = Math.max(6, role.size - 0.5)
  return role
}
const footerRole = prefs ? { ...prefs.footerStyle } : null
let footerHeight = 40
let footerContentUnfit = false
if (prefs) {
  const values = (Object.values(prefs.resolvedFooter) as any[][]).filter(parts => parts.length)
    .map(parts => parts.map(part => part.field ? '9999' : part.text).join(''))
  const measured = () => Math.max(40, ...values.map(value => roleHeight(value, 360, footerRole)))
  while (footerRole.size > 6 && measured() > 200) footerRole.size = Math.max(6, footerRole.size - 0.5)
  const required = measured()
  footerContentUnfit = required > 200
  footerHeight = Math.min(200, required)
}
const footerY = Math.min(660, 700 - footerHeight)
const contentBottom = Math.min(640, footerY - 20)
function titleLayout(value: string, cover = false, chartLayout?: 'text' | 'side') {
  let budget = (cover ? 130 : 64) + prefs.typography.h1.spaceAfter * 96 / 72
  if (chartLayout) {
    const captionMinimum = roleHeight('图 999 国', chartLayout === 'text' ? 1020 : 460,
      { ...prefs.typography.caption, size: 6 })
    budget = Math.min(budget, contentBottom - 114 - captionMinimum - (chartLayout === 'text' ? 102 : 92))
  }
  const role = fitRole(value, 1080, prefs.typography.h1, budget)
  const height = Math.max(cover ? 130 : 52, roleHeight(value, 1080, role))
  const dividerY = Math.max(148, 76 + height + 12)
  return { role, height, dividerY, bodyY: dividerY + 26 }
}
type CaptionedSlide = Input['slides'][number] & {
  chartCaption?: string; captionPrefix?: string; captionBudget?: number; captionContinuation?: boolean; shortenedChartTitle?: boolean
  bodyRole?: any; titleChartLayout?: 'text' | 'side'
  tablePage?: TablePage
}
function paginateSlide(slide: CaptionedSlide): CaptionedSlide[] {
  const compact = prefs.density === 'compact'
  const stacked = slide.chartPath && prefs.layout === 'text'
  const width = slide.chartPath && !stacked ? 520 : 1020
  const minimum = compact ? 40 : 54
  const gap = compact ? 10 : 18
  const chartLayout = slide.chartPath ? stacked ? 'text' : 'side' : undefined
  const bodyY = Math.max(titleLayout(slide.title, false, chartLayout).bodyY,
    titleLayout(slide.title + '（续 999）', false, chartLayout).bodyY)
  const available = contentBottom - bodyY
  const captionMinimum = roleHeight((slide.captionPrefix ?? '') + '国', stacked ? 1020 : 460,
    { ...prefs.typography.caption, size: 6 })
  const captionAvailable = stacked ? available : Math.min(320, contentBottom - Math.max(220, bodyY))
  const firstCaptionBudget = Math.max(captionMinimum, Math.min(96 + prefs.typography.caption.spaceAfter * 96 / 72,
    captionAvailable - (stacked ? 102 : 92)))
  const stackedBudget = Math.min(246, available - firstCaptionBudget - 92)
  // 大间距无法让正文和图注同页时，正文独立分页，图片与完整图注留在随后页面。
  const separateChart = Boolean(stacked && slide.bullets.length &&
    stackedBudget < roleHeight('国', width, prefs.typography.body, minimum))
  const budget = stacked && !separateChart ? stackedBudget : available
  const bodyRole = fitRole('国😀W', width, prefs.typography.body, budget)
  const height = (value: string) => roleHeight(value, width, bodyRole, minimum)
  const chunks: string[] = []
  for (const bullet of slide.bullets) {
    let remaining = Array.from(bullet)
    if (!remaining.length) chunks.push('')
    while (remaining.length) {
      let low = 1, high = Math.min(3800, remaining.length), length = 1
      while (low <= high) {
        const middle = Math.floor((low + high) / 2)
        if (height(remaining.slice(0, middle).join('')) <= budget) { length = middle; low = middle + 1 }
        else high = middle - 1
      }
      chunks.push(remaining.slice(0, length).join(''))
      remaining = remaining.slice(length)
    }
  }
  const groups: string[][] = [[]]
  let used = 0
  for (const chunk of chunks) {
    const size = height(chunk)
    const current = groups[groups.length - 1]!
    if (current.length && (used + gap + size > budget || current.length >= 20)) { groups.push([]); used = 0 }
    const target = groups[groups.length - 1]!
    used += (target.length ? gap : 0) + size
    target.push(chunk)
  }
  const bodyPages = groups.map((bullets, index) => ({ ...slide, bullets, bodyRole, titleChartLayout: chartLayout,
    title: slide.title + (index ? '（续 ' + (index + 1) + '）' : '') }))
  if (!slide.chartCaption) return bodyPages
  const captionWidth = stacked ? 1020 : 460
  const prefix = slide.captionPrefix ?? ''
  const captionBodyY = titleLayout(prefix + '图注（续 999）', false, chartLayout).bodyY
  const continuationBudget = Math.min(stacked ? 300 : 200,
    contentBottom - Math.max(stacked ? captionBodyY : 220, captionBodyY) - (stacked ? 102 : 92))
  let remaining = Array.from(slide.chartCaption.slice(prefix.length))
  const captionChunks: string[] = []
  do {
    const budget = Math.max(captionMinimum, captionChunks.length || separateChart ? continuationBudget : firstCaptionBudget)
    let low = 1, high = Math.min(3800, remaining.length), count = 0
    while (low <= high) {
      const middle = Math.floor((low + high) / 2)
      if (roleHeight(prefix + remaining.slice(0, middle).join(''), captionWidth,
        { ...prefs.typography.caption, size: 6 }) <= budget) { count = middle; low = middle + 1 }
      else high = middle - 1
    }
    count = Math.max(1, count)
    captionChunks.push(prefix + remaining.slice(0, count).join(''))
    remaining = remaining.slice(count)
  } while (remaining.length)
  return [
    ...bodyPages.map((page, index) => ({ ...page,
      ...(separateChart ? { chartPath: undefined, chartCaption: undefined } :
        { chartCaption: captionChunks[0], captionBudget: firstCaptionBudget }),
      ...(captionChunks.length > 1 ? { shortenedChartTitle: true,
        title: prefix + '图表分析' + (index ? '（续 ' + (index + 1) + '）' : '') } : {}),
    })),
    ...captionChunks.slice(separateChart ? 0 : 1).map((chartCaption, index) => ({ ...slide, bullets: [], chartCaption,
      captionBudget: Math.max(captionMinimum, continuationBudget), captionContinuation: true,
      title: prefix + '图注（续 ' + (index + (separateChart ? 1 : 2)) + '）' })),
  ]
}
let chartNumber = 0
const sourceSlides: CaptionedSlide[] = input.slides.map(slide => {
  if (!prefs || !slide.chartPath) return slide
  const captionPrefix = prefs.charts.captionNumbering ? `图 ${++chartNumber} ` : ''
  return { ...slide, captionPrefix, chartCaption: captionPrefix + slide.title }
})
let tableNumber = 0
function tablePages(slide: CaptionedSlide): CaptionedSlide[] {
  const result: CaptionedSlide[] = []
  for (const table of slide.tables ?? []) {
    const number = ++tableNumber
    const tablePageStart = result.length
    const caption = table.caption || slide.title
    const title = (prefs?.tables.captionNumbering === false ? '' : `表 ${number} `) + caption
    const role = prefs ? { ...prefs.typography.table } : {
      size: 17, lineHeight: 1.3, bold: false, color: '#183247', font: 'sans', spaceBefore: 0, spaceAfter: 0,
    }
    // 宽表只按列分组，首列上下文重复；每个原始单元格仍逐字保留。
    for (let column = 1; column < Math.max(2, table.headers.length); column += 5) {
      const indices = [0, ...Array.from({ length: Math.min(5, table.headers.length - column) }, (_, i) => column + i)]
      const header = indices.map(i => table.headers[i]!)
      const rows = table.rows.map(row => indices.map(i => row[i]!))
      const columnWidth = 1020 / indices.length
      const y = prefs ? Math.max(titleLayout(title).bodyY, titleLayout(title + '（续 999）').bodyY) : 174
      const budget = contentBottom - y
      const measured = (row: string[], style: any) => Math.max(32, ...row.map(value => chartBulletHeight(
        value, finalWidth(columnWidth) - 20, style.size, 0, style.lineHeight, style.bold,
        style.spaceBefore, style.spaceAfter, prefs?.fontNames[style.font], style.indent, true))) + 12
      while (role.size > 6 && measured(header, role) > budget / 2) role.size = Math.max(6, role.size - 0.5)
      const headerHeight = Math.min(measured(header, role), budget / 2)
      if (measured(header, role) > headerHeight) preferenceWarnings.push({ page: 0,
        code: 'pptx_table_header_unfit', message: `表 ${number} 表头在最小6磅仍过长，完整内容保留但可能裁切；排版未通过。` })
      let cursor = 0
      do {
        const hasHeader = cursor === 0 || prefs?.tables.repeatHeader !== false
        const grid = hasHeader ? [header] : []
        const heights = hasHeader ? [headerHeight] : []
        let used = heights.reduce((sum, height) => sum + height, 0)
        const pageRole = { ...role }
        while (cursor < rows.length && grid.length < 74) {
          let height = measured(rows[cursor]!, pageRole)
          if (used + height > budget && grid.length > (hasHeader ? 1 : 0)) break
          // PPTX 不拆散业务行；极端单行仅缩字并明确返回仍无法容纳的告警。
          while (used + height > budget && pageRole.size > 6) {
            pageRole.size = Math.max(6, pageRole.size - 0.5)
            height = measured(rows[cursor]!, pageRole)
          }
          if (used + height > budget) {
            preferenceWarnings.push({ page: result.length + 2, code: 'pptx_table_row_unfit',
              message: `表 ${number} 第 ${cursor + 1} 行在最小6磅仍超过页内区域，完整单元格保留，可能裁切；排版未通过。` })
            height = Math.max(1, budget - used)
          }
          grid.push(rows[cursor]!); heights.push(height); used += height; cursor++
          if (pageRole.size < role.size) break
        }
        if (pageRole.size < role.size) preferenceWarnings.push({ page: result.length + 2,
          code: 'pptx_table_font_adjusted', message: `表 ${number} 长行由 ${role.size} 磅调整为 ${pageRole.size} 磅，完整单元格保留。` })
        const pageInTable = result.length - tablePageStart
        result.push({ title: title + (pageInTable ? `（续 ${pageInTable + 1}）` : ''), bullets: [],
          evidenceIds: slide.evidenceIds, tablePage: { grid, heights, role: pageRole, hasHeader, y,
            startRow: cursor - grid.length + (hasHeader ? 1 : 0) } })
      } while (cursor < rows.length)
    }
  }
  return result
}
const slides = sourceSlides.flatMap(slide => [
  ...(prefs ? paginateSlide(slide) : [slide]), ...tablePages(slide),
])
const colors = { ...palettes[input.theme], ...(prefs ? { accent: prefs.common.accentColor } : {}) }
// 沿用工作簿自动对比色：浅主题表头用黑字，深主题用白字，不新增无效维护项。
const tableHeaderRgb = colors.accent.slice(1).match(/../g)!.map((value: string) => parseInt(value, 16) / 255)
const tableHeaderLuminance = tableHeaderRgb.map((value: number) => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
  .reduce((sum: number, value: number, index: number) => sum + value * [.2126, .7152, .0722][index]!, 0)
const tableHeaderColor = tableHeaderLuminance > .179 ? '#000000' : '#FFFFFF'

const chartUrls = slides.map((slide) => slide.chartPath ? pathToFileURL(slide.chartPath).href : undefined)
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
const captionRoles = new Map<object, any>()
const bodyRoles = new Map<object, any>()
const titleRoles = new Map<object, any>()
const coverTitleHeight = prefs ? titleLayout(input.title, true).height : 130
let coverBodyRole = prefs?.typography.body
if (prefs) {
  const slot = (contentBottom - 40 - coverTitleHeight - 40) / 2
  const value = roleHeight(input.period, 1020, coverBodyRole) > roleHeight('管理分析报告', 1020, coverBodyRole)
    ? input.period : '管理分析报告'
  coverBodyRole = fitRole(value, 1020, coverBodyRole, slot)
  if (coverBodyRole.size < prefs.typography.body.size) preferenceWarnings.push({ page: 1,
    code: 'pptx_body_font_adjusted', message: `封面正文为适应可用空间，由 ${prefs.typography.body.size} 磅调整为 ${coverBodyRole.size} 磅，完整文字和段落间距保留。` })
}
const coverPeriodHeight = prefs ? roleHeight(input.period, 1020, coverBodyRole) : 60
const coverLabelHeight = prefs ? Math.max(38, roleHeight('管理分析报告', 1020, coverBodyRole)) : 38
const coverTitleY = prefs ? Math.min(220, contentBottom - coverTitleHeight - coverPeriodHeight - coverLabelHeight - 40) : 220
const coverTitle = text(96, coverTitleY, 1080, coverTitleHeight, input.title, 34, colors.ink, true)
const coverPeriod = text(100, coverTitleY + coverTitleHeight + 20, 1020, coverPeriodHeight, input.period, 18, colors.muted)
const coverLabel = text(100, prefs ? Math.min(620, contentBottom - coverLabelHeight) : 620,
  1020, coverLabelHeight, '管理分析报告', 12, colors.accent, true)
if (prefs) { bodyRoles.set(coverPeriod, coverBodyRole); bodyRoles.set(coverLabel, coverBodyRole) }
const pages: DeckSpec['pages'] = [
  {
    background: colors.background,
    elements: [
      { type: 'shape', shape: 'rect', x: 0, y: 0, w: 18, h: SPEC_CANVAS_H, fill: colors.accent },
      coverTitle, coverPeriod, coverLabel,
    ],
  },
  ...slides.map((slide, index) => {
    const bullets = prefs ? slide.bullets : slide.chartPath ? slide.bullets : slide.bullets.slice(0, 5)
    const compact = prefs?.density === 'compact'
    const stacked = Boolean(prefs && slide.chartPath && prefs.layout === 'text')
    const imageLeft = Boolean(prefs && slide.chartPath && prefs.layout === 'image_left')
    const textX = imageLeft ? 680 : 140
    const textWidth = slide.chartPath && !stacked ? 520 : 1020
    const bodyRole = slide.bodyRole ?? prefs?.typography.body
    const bodySize = bodyRole?.size ?? 17
    const title = prefs ? titleLayout(slide.title, false,
      slide.titleChartLayout ?? (slide.chartPath ? stacked ? 'text' : 'side' : undefined)) : null
    const heights = bullets.map((bullet) => prefs ? roleHeight(bullet, textWidth, bodyRole, compact ? 40 : 54)
      : slide.chartPath ? chartBulletHeight(bullet) : 54)
    const gap = prefs ? compact ? 10 : 18 : slide.chartPath && bullets.length > 1
      ? Math.max(8, Math.min(18, (466 - heights.reduce((sum, height) => sum + height, 0)) / (bullets.length - 1))) : 18
    let bulletY = title?.bodyY ?? 174
    const elements: DeckSpec['pages'][number]['elements'] = [
      { type: 'shape' as const, shape: 'rect', x: 72, y: 76, w: 8, h: 50, fill: colors.accent },
      text(100, 76, 1080, title?.height ?? 52, slide.title, 25, colors.ink, true),
      { type: 'shape' as const, shape: 'line', x: 100, y: title?.dividerY ?? 148, w: 1080, h: 1, stroke: { color: '#D5DEDF', widthPt: 1 } },
      ...bullets.flatMap((bullet, bulletIndex) => {
        const y = bulletY
        const height = heights[bulletIndex]!
        bulletY += height + gap
        const body = text(textX, y, textWidth, height, bullet, bodySize, colors.ink)
        if (prefs) bodyRoles.set(body, bodyRole)
        return [
          { type: 'shape' as const, shape: 'ellipse', x: textX - 28, y: y + 16, w: 10, h: 10, fill: colors.accent },
          body,
        ]
      }),
      ...(!prefs ? [text(1090, 660, 100, 24, `${index + 2}`, 10, colors.muted)] : []),
    ]
    if (title) titleRoles.set(elements[1]!, title.role)
    if (prefs && bodySize < prefs.typography.body.size) preferenceWarnings.push({ page: index + 2,
      code: 'pptx_body_font_adjusted', message: `正文为适应可用空间，由 ${prefs.typography.body.size} 磅调整为 ${bodySize} 磅，完整文字保留。` })
    if (slide.shortenedChartTitle) preferenceWarnings.push({ page: index + 2, code: 'pptx_chart_title_shortened',
      message: '超长源标题在图注片段中完整保留，正文页顶栏使用简短的图表分析标题，避免挤占正文。' })
    const url = chartUrls[index]
    if (url) {
      const aspect = charts.get(url)?.aspect ?? 460 / 320
      const box = stacked ? { x: 140, y: bulletY + 10, w: 1020, h: Math.max(60, contentBottom - bulletY - 10) }
        : { x: imageLeft ? 140 : 700, y: Math.max(220, title?.bodyY ?? 174), w: 460,
          h: prefs ? Math.min(320, contentBottom - Math.max(220, title!.bodyY)) : 320 }
      let imageHeight = box.h
      if (prefs && slide.chartCaption) {
        const role = { ...prefs.typography.caption }
        const requestedSize = role.size
        while (role.size > 6 && roleHeight(slide.chartCaption, box.w, role) > (slide.captionBudget ?? 96)) {
          role.size = Math.max(6, role.size - 0.5)
        }
        const captionHeight = roleHeight(slide.chartCaption, box.w, role)
        imageHeight -= captionHeight + 12
        const caption = text(box.x, box.y + imageHeight + 12, box.w, captionHeight,
          slide.chartCaption, role.size, role.color, role.bold)
        elements.push(caption)
        captionRoles.set(caption, role)
        if (slide.captionContinuation) preferenceWarnings.push({ page: index + 2, code: 'pptx_caption_continued',
          message: '长图注使用续页，保持原图号和完整文字，图片与图注同页。' })
        if (role.size < requestedSize) preferenceWarnings.push({ page: index + 2, code: 'pptx_caption_font_adjusted',
          message: `图注为适应可用空间，由 ${requestedSize} 磅调整为 ${role.size} 磅，完整文字保留。` })
      }
      const w = Math.min(box.w, imageHeight * aspect)
      const h = w / aspect
      elements.push({ type: 'image' as const, url, x: box.x + (box.w - w) / 2, y: box.y + (imageHeight - h) / 2, w, h })
    }
    return { background: colors.background, elements }
  }),
]

const signatureElements = new Set<object>()
if (prefs) {
  const signature = prefs.signature
  const paragraphs = (values: string[], size: number, identity = false) => values.map((value, index) => ({
        align: signature.align, lineSpacingPct: signature.lineHeight * 100,
        spaceBeforePt: identity && index === 1 ? signature.dateGap : 0, spaceAfterPt: signature.spaceAfter,
        indentPt: signature.indent,
        runs: [{ text: value, sizePt: size, color: signature.color,
          bold: signature.bold, font: prefs.fontNames[signature.font] }],
      }))
  const measured = (values: string[], size: number, identity = false) => {
    const layout = layoutText({ body: { paragraphs: paragraphs(values, size, identity).map(paragraph => ({
      runs: paragraph.runs.map(run => ({ text: run.text, fontSize: run.sizePt })),
      lineHeight: paragraph.lineSpacingPct, spaceBefore: paragraph.spaceBeforePt, spaceAfter: paragraph.spaceAfterPt,
      indent: Math.round(paragraph.indentPt * 12700),
    })), wrap: true, anchor: 'top', insets: { l: 0, t: 0, r: 0, b: 0 } },
      boxWidthPx: prefs.aspectRatio === '4:3' ? 810 : 1080, boxHeightPx: 466, metrics: new HeuristicMetrics(),
      vp: { widthPx: 1280, heightPx: SPEC_CANVAS_H, scale: 1 } })
    return Math.ceil(Math.max(layout.contentHeight, layout.inkBottom ?? 0)) + 8
  }
  const identity = prefs.signatureLines.slice(0, 2) as string[]
  const signatureHeading = (value: string) => {
    const layout = titleLayout(value)
    const heading = text(100, 76, 1080, layout.height, value, prefs.typography.h1.size, colors.ink, true)
    titleRoles.set(heading, layout.role)
    return heading
  }
  const firstHeading = signatureHeading('报告落款')
  const continuationHeading = signatureHeading('报告落款（附加说明续页）')
  // 前间距是标题文本框底部到首个落款文本框顶部的物理距离，不靠首段段前模拟。
  const startBelow = (heading: typeof firstHeading) => heading.y + heading.h + signature.spaceBefore * 96 / 72
  let signatureStart = startBelow(firstHeading)
  let signatureBudget = contentBottom - signatureStart
  let identitySize = signature.size
  while (identitySize > 6 && measured(identity, identitySize, true) > signatureBudget) identitySize = Math.max(6, identitySize - 0.5)
  const identityHeight = measured(identity, identitySize, true)
  let y = signatureStart
  let signaturePage = { background: colors.background, elements: [firstHeading] } as DeckSpec['pages'][number]
  pages.push(signaturePage)
  if (identitySize !== signature.size) preferenceWarnings.push({ page: pages.length,
    code: 'pptx_signature_identity_font_adjusted', message: '长署名与日期保持同页，落款身份字号由 ' + signature.size + ' 磅调整为 ' + identitySize + ' 磅，完整署名与日期保留。' })
  if (identityHeight > signatureBudget) preferenceWarnings.push({ page: pages.length,
    code: 'pptx_signature_identity_spacing_unfit',
    message: '落款身份已调整至最小字号，但冻结的标题前间距、日期间距和段后间距仍超过页脚以上可用区域，可能与页脚重叠；保留原文和间距，产物继续生成，排版未通过。' })
  const addSignature = (values: string[], size: number, height: number, isIdentity = false) => {
    const element = { type: 'text' as const, x: 100, y, w: 1080, h: height,
      paragraphs: paragraphs(values, size, isIdentity) }
    signaturePage.elements.push(element); signatureElements.add(element); y += height
  }
  addSignature(identity, identitySize, identityHeight, true)
  const nextSignaturePage = () => {
    const heading = signatureHeading('报告落款（附加说明续页）')
    signaturePage = { background: colors.background, elements: [heading] }
    signatureStart = startBelow(heading)
    signatureBudget = contentBottom - signatureStart
    pages.push(signaturePage); y = signatureStart
  }
  let descriptionSize = signature.size
  while (descriptionSize > 6 && measured(['国😀W'], descriptionSize) > Math.min(signatureBudget, contentBottom - startBelow(continuationHeading))) {
    descriptionSize = Math.max(6, descriptionSize - 0.5)
  }
  if (prefs.signatureLines.length > 2 && descriptionSize < signature.size) preferenceWarnings.push({ page: pages.length,
    code: 'pptx_signature_description_font_adjusted',
    message: `落款说明单行超过页脚以上可用区域，由 ${signature.size} 磅调整为 ${descriptionSize} 磅，完整原文和段落间距保留。` })
  for (const description of prefs.signatureLines.slice(2) as string[]) {
    let remaining = Array.from(description)
    if (!remaining.length) remaining = ['']
    while (remaining.length) {
      // 页标题与页脚也占元素预算，保留余量避免引擎截断说明。
      if (signaturePage.elements.length >= 44) nextSignaturePage()
      const all = remaining.join('')
      if (measured([all], descriptionSize) <= signatureBudget && y + measured([all], descriptionSize) > contentBottom) nextSignaturePage()
      let low = 1, high = Math.min(3800, remaining.length), count = 0
      while (low <= high) {
        const middle = Math.floor((low + high) / 2)
        if (measured([remaining.slice(0, middle).join('')], descriptionSize) <= contentBottom - y) { count = middle; low = middle + 1 }
        else high = middle - 1
      }
      if (!count) {
        if (y > signatureStart) { nextSignaturePage(); continue }
        // 空页仍放不下时一次保留全部余文并告警，不能继续创建空续页。
        addSignature([all], descriptionSize, Math.max(1, signatureBudget))
        preferenceWarnings.push({ page: pages.length, code: 'pptx_signature_description_content_unfit',
          message: '落款说明在空续页仍无法容纳，完整余文保留在受限文本框中，可能缩小或裁切；排版未通过，产物继续生成。' })
        remaining = []
        continue
      }
      const chunk = remaining.slice(0, count).join('')
      addSignature([chunk], descriptionSize, measured([chunk], descriptionSize))
      remaining = remaining.slice(count)
    }
  }
  for (const [index, page] of pages.entries()) {
    for (const element of page.elements) {
      if (element.type !== 'text' || signatureElements.has(element)) continue
      const isTitle = element.y === 76 || element === coverTitle
      const role = { ...(isTitle ? prefs.typography.h1 : captionRoles.get(element) ?? bodyRoles.get(element) ?? prefs.typography.body) }
      if (isTitle) {
        const value = element.paragraphs.map(paragraph => paragraph.runs.map(run => run.text).join('')).join('\n')
        const requestedSize = role.size
        role.size = (titleRoles.get(element) ?? titleLayout(value, index === 0).role).size
        if (role.size < requestedSize) preferenceWarnings.push({ page: index + 1, code: 'pptx_title_font_adjusted',
          message: `标题为适应可用空间，由 ${requestedSize} 磅调整为 ${role.size} 磅，完整文字保留。` })
      }
      for (const paragraph of element.paragraphs) {
        paragraph.lineSpacingPct = role.lineHeight * 100
        paragraph.spaceBeforePt = role.spaceBefore
        paragraph.spaceAfterPt = role.spaceAfter
        paragraph.indentPt = role.indent
        for (const run of paragraph.runs) {
          run.font = prefs.fontNames[role.font]
          run.sizePt = role.size
          run.color = role.color
          run.bold = role.bold
        }
      }
      element.h = Math.max(element.h, roleHeight(
        element.paragraphs.map(paragraph => paragraph.runs.map(run => run.text).join('')).join('\n'),
        element.w, role))
    }
  }
}

const deck = await buildDeckPptx({ pages }, {
  fetchImage: async (url) => charts.get(url) ?? null,
})
const opened = await openPptx(deck.bytes)
setSlideNotes(opened, 0, `报告期间：${input.period}`)
for (const [index, slide] of slides.entries()) {
  setSlideNotes(opened, index + 1, `分析证据：${(slide.evidenceIds ?? []).join(', ') || '未登记'}`)
}
if (prefs) {
  for (const [index, slide] of opened.deck.slides.entries()) {
    if (index === 0 && prefs.hideTitleSlideFooter) continue
    for (const [side, parts] of Object.entries(prefs.resolvedFooter) as [string, any[]][]) {
      if (!parts.length) continue
      const style = footerRole
      addElement(slide, { kind: 'textbox',
        offset: { x: (side === 'left' ? 100 : side === 'center' ? 460 : 820) * 9525,
          y: footerY * 9525, cx: 360 * 9525, cy: footerHeight * 9525 },
        paragraphs: [{ align: side as 'left' | 'center' | 'right', lineHeight: style.lineHeight * 100,
          indent: Math.round(style.indent * 12700),
          spaceBefore: style.spaceBefore, spaceAfter: style.spaceAfter, runs: parts.map(part => ({
          text: part.field === 'slidecount' ? String(pages.length) : part.field ? String(index + 1) : part.text,
          ...(part.field === 'slidenum' ? { field: part.field } : {}),
          fontFamily: prefs.fontNames[style.font], fontSize: style.size, color: style.color, bold: style.bold,
        })) }], bodyPr: { autoFit: 'shrink', insetsEmu: { l: 0, t: 0, r: 0, b: 0 } },
      })
    }
    if (footerRole.size < prefs.footerStyle.size) preferenceWarnings.push({ page: index + 1,
      code: 'pptx_footer_font_adjusted', message: `页脚为适应可用空间，由 ${prefs.footerStyle.size} 磅调整为 ${footerRole.size} 磅，完整文字和段落间距保留。` })
    if (footerContentUnfit) preferenceWarnings.push({ page: index + 1, code: 'pptx_footer_content_unfit',
      message: '页脚在最小6磅仍超过200像素可用高度，完整原文和段落间距保留在受限文本框中，可能缩小或裁切，不能保证完整可见；排版未通过，产物继续生成。' })
  }
  if (prefs.aspectRatio === '4:3') {
    // 同步等比缩小图片，避免图表横向压扁。
    for (const slide of opened.deck.slides) for (const element of slide.elements) {
      if (element.type !== 'picture') continue
      const box = element.transform.offset
      box.y += Math.round(box.cy / 8)
      box.cy = Math.round(box.cy * 0.75)
      element.dirtyTransform = true
    }
    setSlideSize(opened, Math.round(opened.deck.size.cy * 4 / 3), opened.deck.size.cy)
  }
}
// 原生表格在最终页面尺寸确定后插入，保持列网格与外框宽度一致。
for (const [index, page] of slides.entries()) {
  if (!page.tablePage) continue
  const table = page.tablePage
  const y = table.y
  const height = table.heights.reduce((sum, value) => sum + value, 0)
  const added = addTable(opened, index + 1, { rows: table.grid.length, cols: table.grid[0]!.length,
    offset: { x: finalWidth(140) * 9525, y: y * 9525, cx: finalWidth(1020) * 9525, cy: height * 9525 },
    rowHeightsEmu: table.heights.map(value => Math.round(value * 9525)) })
  if (!added) throw new Error('pptx_native_table_insert_failed')
  editTableStyle(added.slide, added.elementId, { firstRow: table.hasHeader, bandRow: false,
    borderPreset: prefs?.tables.borders === 'none' ? 'none' : 'all',
    borderColor: '#D5DEDF', borderWidthEmu: prefs?.tables.borders === 'all' ? 9525 : 3175 })
  for (const [row, cells] of table.grid.entries()) {
    for (const [col, value] of cells.entries()) {
      const header = table.hasHeader && row === 0
      const striped = prefs?.tables.striped !== false && (table.startRow + row - (table.hasHeader ? 1 : 0)) % 2 === 1
      editTableStyle(added.slide, added.elementId, { shadingColor: header ? colors.accent : striped ? '#EAF0F3' : '#FFFFFF',
        cells: [{ row, col }] })
      const lines = value.split('\n')
      editTableCellText(added.slide, added.elementId, row, col, lines.map((line, index) => ({
        lineHeight: table.role.lineHeight * 100,
        indent: Math.round((table.role.indent ?? 0) * 12700),
        spaceBefore: index === 0 ? table.role.spaceBefore : 0,
        spaceAfter: index === lines.length - 1 ? table.role.spaceAfter : 0,
        runs: [{ text: line, fontFamily: prefs?.fontNames[table.role.font], fontSize: table.role.size,
          color: header ? tableHeaderColor : table.role.color, bold: header || table.role.bold }],
      })))
    }
  }
}
const bytes = await savePptx(opened)
await writeFile(input.output, bytes)
let issues: { page: number; message: string; code?: string }[]
try {
  const audited = await auditDeck(bytes)
  issues = audited.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message })))
} catch (error) {
  issues = [{ page: 0, message: `PPTX layout audit failed: ${error instanceof Error ? error.message : String(error)}` }]
}
issues.push(...preferenceWarnings)
const chartImages = chartUrls.flatMap((url, index) => {
  const image = url ? charts.get(url) : null
  return image ? [{ slide: index + 2, sourceSha256: createHash('sha256').update(image.bytes).digest('hex') }] : []
})
process.stdout.write(JSON.stringify({ slideCount: pages.length, issues, chartImages }))
