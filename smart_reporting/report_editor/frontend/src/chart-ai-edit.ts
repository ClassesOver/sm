import type { EditorView } from '@milkdown/kit/prose/view'
import type { Node as ProseMirrorNode } from '@milkdown/kit/prose/model'
import { closeHistory } from '@milkdown/kit/prose/history'
import { buttonClasses } from './button'
import { askAIPanel, type AskAISession } from './ask-ai-panel'
import { createAITemplateCard } from './ai-template-card'
import { findProtocolMarkers, protocolMarkersUnchanged } from './protocol'
import { ReportEditorApiError, type ChartAIEditPage, type ChartAIEditSuccess, type ChartStandardEditRequest, type ReportEditorClient, type TraceChartInfo } from './api'

/** 设计稿：docs/superpowers/specs/2026-10-25-report-editor-ai-chart-edit-design.md §3/§10。 */

const UNAVAILABLE_REASONS: Record<string, string> = {
  read_only: '当前会话为只读分享会话，不能使用 AI 改图。',
  unconfigured: 'AI 改图服务未配置完成。',
  vision_missing: '未配置视觉审查模型，AI 改图不可用。',
  snapshot_expired: '该版本的数据来源已结束保留期，AI 改图不可用。',
  plot_data_missing: '这张图没有登记作图数据（或来自旧报告），暂不支持改图。',
  unknown_chart: '图表不在当前版本的登记中。',
  unavailable: 'AI 改图当前不可用。',
}

const STAGE_LABELS: Record<string, string> = {
  queued: '排队中…',
  check: '正在核验底图身份…',
  plan: '正在理解改图要求…',
  materialize: '正在准备作图数据…',
  compile: '正在编译标准图参数…',
  draw: '正在绘图与执行检查…',
  inspect: '正在检查图表…',
  register: '正在登记改图结果…',
}

const QUICK_COMMANDS = [
  '改成横向条形图并按数值降序排列',
  '在图上显示数值标签',
  '只保留金额最大的前 5 组，其余合并为“其他”并标注为子集',
  '把标题改得更简洁',
  '调整配色，提高对比度',
  '图例移到图表下方',
]

// P3：快捷指令按图形推荐——已知当前形态时优先给出“从该形态出发”的常用调整，
// 形态未知（未改图的原始图）回落到默认指令集。
const QUICK_COMMANDS_BY_FORM: [RegExp, string[]][] = [
  [/条形|柱状/, ['在图上显示数值标签', '按数值降序重新排列', '改成横向条形图', '只保留金额最大的前 5 组，其余合并为“其他”并标注为子集']],
  [/折线|趋势/, ['标注最高和最低的月份', '平滑折线并加粗', '改成柱状图对比各期', '在图上显示数值标签']],
  [/饼|构成|占比/, ['按占比从大到小排序', '只保留占比最大的前 5 项，其余合并为“其他”并标注为子集', '改成排序条形图', '在扇区外侧显示百分比']],
]

export function quickCommandsForForm(visualForm?: string | null): string[] {
  if (!visualForm) return QUICK_COMMANDS
  for (const [pattern, commands] of QUICK_COMMANDS_BY_FORM) {
    if (pattern.test(visualForm)) return [...new Set([...commands, ...QUICK_COMMANDS])].slice(0, QUICK_COMMANDS.length)
  }
  return QUICK_COMMANDS
}

const MAX_INSTRUCTION_CHARS = 2000

export const STANDARD_CHART_PRESETS = [
  { id: 'pie', name: '饼图', description: '需要可加的非负构成数据；不足整体的区域保持留白。', standard: { standardForm: 'pie' }, instruction: '按已登记数据改成饼图，保持真实分母与覆盖范围。' },
  { id: 'donut', name: '环形图', description: '沿用真实构成分母，不把展示子集重新归一。', standard: { standardForm: 'donut' }, instruction: '按已登记数据改成环形图，保持真实分母与覆盖范围。' },
  { id: 'radar', name: '雷达图', description: '需要3–8个同量纲轴，或前轮已登记的冻结尺度。', standard: { standardForm: 'radar' }, instruction: '使用已登记字段与尺度改成雷达图，不从观测值猜测业务满分。' },
  { id: 'funnel', name: '漏斗图', description: '保持冻结阶段顺序；非单调按原值呈现并告警。', standard: { standardForm: 'funnel' }, instruction: '改成按登记阶段顺序的漏斗图，不暗中声称转化率。' },
  { id: 'sankey', name: '桑基图', description: '需要前轮已登记的source/target/value字段绑定。', standard: { standardForm: 'sankey' }, instruction: '按已登记流向字段改成静态桑基图，不补造平衡流。' },
  { id: 'dual', name: '双坐标轴', description: '适合金额与完成率等单位不同的系列。', instruction: '根据已登记系列改成双坐标轴，金额与完成率等不同单位分别使用左右轴，清楚标明单位；不新增或修改数值。' },
  { id: 'dual-stack', name: '堆叠柱与右轴折线', description: '适合分项金额与独立比例同时展示。', instruction: '把已登记的可加分项画成左轴堆叠柱，正负分开累计；完成率等独立指标画右轴折线，分别标明单位，总额只包含左侧分项，不重复堆叠。' },
  { id: 'vertical-break', name: '纵向断轴', description: '适合少数极大值挤压其余柱或折线。', instruction: '保留全部数据和原值，用上下两个线性区间展示纵向图，清楚画出断轴斜线并说明省略区间；不得静默隐藏数据点或将值压到边界。' },
  { id: 'horizontal-break', name: '横向条形断轴', description: '适合类别较多且数值差距很大的横条。', instruction: '改成横向分组条形图，使用左右两个线性区间和清晰断轴标记；两段保持同一类别顺序、颜色、真实有符号柱长和零起点，说明省略区间。' },
  { id: 'scatter', name: '数值散点', description: '需要两个已登记数值字段。', instruction: '使用两个合适的已登记数值字段绘制散点图，横纵坐标均使用真实数值及登记单位；若有分类字段按分类区分，不用类别序号代替数值。' },
  { id: 'bubble', name: '比例气泡', description: '还需要一个非负数值字段表示面积。', instruction: '使用已登记的两个数值字段作为真实横纵坐标、一个非负数值字段表示气泡面积，面积严格正比于原值，零值不制造虚假气泡，并说明各字段及单位。' },
  { id: 'heatmap', name: '分类热力图', description: '需要两个分类字段和一个数值字段。', instruction: '用两个已登记分类字段和一个数值字段绘制热力矩阵，保留真实行列含义，缺失单元与零值区分；不暗中聚合重复单元。' },
  { id: 'waterfall', name: '增减瀑布图', description: '需要明确的起点、增减项和已登记小计或终点。', instruction: '将已登记的可加金额绘制为增减瀑布图，明确绝对值起点、小计或终点与有符号增减项；累计对账，不编造终点或改变贡献顺序。' },
  { id: 'boxplot', name: '分布箱线图', description: '需要原始样本，或同口径的已登记分位数和须。', instruction: '绘制分组箱线图：有原始组内样本时按样本计算；只有已登记分位数和上下须时直接读取统计量，不把汇总均值当原始样本。真实样本量和异常点未知时明确说明。' },
  { id: 'bands', name: '折线与范围带', description: '需要已登记的中心值、上下界和一致期间。', instruction: '将中心值画为折线，并使用同口径、同期间的已登记上下界绘制范围带，明确单位；缺失保持断带，不能自行估算置信区间。' },
  { id: 'canvas', name: '画布与配色', description: '改善字号、留白、图例与重点标注的阅读效果。', instruction: '优化画布比例、字体、留白与配色，提高对比度；同一系列颜色保持一致，合理安排图例和重点标注，避免文字遮挡或超出画布，保留全部真实数值。' },
  { id: 'pagination', name: '全部类别分页', description: '适合类别较多的柱图；完整页数须在图表预算内。', instruction: '将全部已登记类别按原顺序分页为清晰的柱图或横向条形图，所有页使用相同系列颜色、单位和值域，标明页号；不截取TopN、不丢末页，若预算不足请明确说明。' },
] as const

export function chartAiUnavailableReason(reason?: string): string {
  if (!reason) return UNAVAILABLE_REASONS.unavailable
  return UNAVAILABLE_REASONS[reason] ?? UNAVAILABLE_REASONS.unavailable
}

export function assetUrl(basePath: string, imagePath: string): string {
  const encoded = imagePath.split('/').map(encodeURIComponent).join('/')
  return `${basePath}/asset/${encoded}`
}

/** 从编辑器图片 src 提取登记的工作区相对路径（asset URL 形态时解码还原）。 */
export function workspacePathFromSrc(src: string, basePath: string): string | null {
  const marker = `${basePath.replace(/\/$/, '')}/asset/`
  const index = src.indexOf(marker)
  if (index < 0) return null
  const raw = src.slice(index + marker.length).split(/[?#]/)[0] ?? ''
  try {
    return raw.split('/').map(decodeURIComponent).join('/')
  } catch {
    return null
  }
}

/** 正文图片 → 登记图表：与后端 _manifest_image 同一“后缀唯一匹配”规则。 */
export function matchChartForImage(
  charts: TraceChartInfo[],
  src: string,
  basePath = '',
): TraceChartInfo | null {
  const candidates = [src.replace(/\\/g, '/'), workspacePathFromSrc(src, basePath) ?? '']
  const matches = charts.filter(chart => {
    const path = chart.imagePath.replace(/\\/g, '/')
    return candidates.some(value =>
      value &&
      !value.startsWith('/') &&
      !value.split('/').includes('..') &&
      (path === value || path.endsWith(`/${value}`)),
    )
  })
  return matches.length === 1 ? matches[0] : null
}

/** 正文图片已是 AI 改图结果（chart-edits/<editId>/chart.png）时返回 editId。 */
export function chartEditIdFromSrc(src: string, basePath = ''): string | null {
  const candidates = [src.replace(/\\/g, '/'), workspacePathFromSrc(src, basePath) ?? '']
  for (const value of candidates) {
    const matched = /(?:^|\/)chart-edits\/(cedit-[0-9a-z]{8,32})\/[^/]+$/.exec(value)
    if (matched) return matched[1]
  }
  return null
}

interface CaptionTarget {
  from: number
  to: number
  prefix: string
}

/** 图片块后紧跟的“图表：/图注：”段落；替换图注时一并写回，与图片同一次事务。 */
export function findChartCaptionParagraph(doc: ProseMirrorNode, posAfter: number): CaptionTarget | null {
  const node: ProseMirrorNode | undefined | null = doc.nodeAt(posAfter)
  if (!node || !node.isTextblock) return null
  const text = node.textContent ?? ''
  const matched = /^(图表|图注)\s*[:：]/.exec(text.trim())
  if (!matched) return null
  return { from: posAfter, to: posAfter + node.nodeSize, prefix: matched[0] }
}

const isImageNode = (node: ProseMirrorNode | null | undefined): node is ProseMirrorNode =>
  !!node && (node.type.name === 'image' || node.type.name === 'image-block')

/** 图片节点位置；行内图片（与引用标记同段）的图注段落在所在段落之后。 */
function locateImage(view: EditorView, img: HTMLImageElement) {
  try {
  const doc = view.state.doc
  const pos = view.posAtDOM(img, 0)
  const direct = doc.nodeAt(pos)
  if (isImageNode(direct)) {
    const blockEnd = direct.isInline ? doc.resolve(pos).after() : pos + direct.nodeSize
    return { from: pos, node: direct, blockEnd }
  }
  const resolved = doc.resolve(pos)
  if (!resolved.depth) return null
  const from = resolved.before()
  const node = doc.nodeAt(from)
  return isImageNode(node) ? { from, node, blockEnd: from + node.nodeSize } : null
  } catch {
    return null
  }
}

export interface ChartReplacementText {
  title: string | null
  altText: string | null
}

/**
 * 接受替换：一次事务修改图片节点（src 与替代文本）与随后的“图表：/图注：”段落，保证撤销一步恢复原图。
 * “图表：”段落写标题，“图注：”段落写图注；返回是否已提交事务，找不到对应图片节点时返回 false。
 */
export function applyChartReplacement(
  view: EditorView,
  img: HTMLImageElement,
  imageSrc: string,
  text: ChartReplacementText,
): boolean {
  const located = locateImage(view, img)
  if (!located) return false
  const { from, node, blockEnd } = located
  const { title, altText } = text
  const captions: { target: CaptionTarget; references: ProseMirrorNode[]; replacement: string }[] = []
  const seen = new Set<string>()
  let cursor = blockEnd
  for (let count = 0; count < 2; count++) {
    const target = findChartCaptionParagraph(view.state.doc, cursor)
    if (!target) break
    const kind = target.prefix.startsWith('图表') ? '图表' : '图注'
    if (seen.has(kind)) return false
    seen.add(kind)
    const value = kind === '图表' ? title : altText
    if (value !== null) {
      const references = captionReferenceNodes(view.state.doc.nodeAt(target.from)!)
      if (references === null) return false
      captions.push({ target, references, replacement: `${target.prefix}${value}` })
    }
    cursor = target.to
  }
  const tr = view.state.tr
  if (node.type.name === 'image-block') {
    tr.setNodeMarkup(from, undefined, { ...node.attrs, src: imageSrc, caption: altText ?? node.attrs.caption })
  } else {
    tr.setNodeMarkup(from, undefined, { ...node.attrs, src: imageSrc, alt: altText ?? node.attrs.alt })
  }
  // 从后向前编辑，保留段落类型/属性及引用节点；首段变长不偏移第二段。
  for (const { target, references, replacement } of captions.reverse()) {
    if (references.length) {
      tr.replaceWith(target.from + 1, target.to - 1, [view.state.schema.text(replacement), ...references])
    } else tr.insertText(replacement, target.from + 1, target.to - 1)
  }
  if (!protocolMarkersUnchanged(view.state.doc.textContent, tr.doc.textContent)) return false
  view.dispatch(closeHistory(tr))
  return true
}

/** 页列表必须完整，不能把损坏的多页响应降格为只接受首页。 */
export function chartResultPages(result: ChartAIEditSuccess): ChartAIEditPage[] | null {
  if (result.pages === undefined) return [{ pageNumber: 1, pageCount: 1, imagePath: result.imagePath,
    imageSrc: result.imageSrc, title: result.changes.title ?? null, altText: result.changes.altText ?? null }]
  const pages = result.pages
  if (!Array.isArray(pages) || !pages.length || pages.length > 20 || pages.some((page, i) => page.pageNumber !== i + 1
    || page.pageCount !== pages.length || !page.imagePath || !page.imageSrc
    || page.imagePath.split('/').includes('..') || page.imageSrc.split('/').includes('..'))
    || new Set(pages.map(page => page.imagePath)).size !== pages.length
    || new Set(pages.map(page => page.imageSrc)).size !== pages.length
    || pages[0]!.imagePath !== result.imagePath || pages[0]!.imageSrc !== result.imageSrc) return null
  return pages
}

function imageMatchesPage(src: string, page: ChartAIEditPage, basePath: string): boolean {
  const value = workspacePathFromSrc(src, basePath) ?? src
  return value === page.imagePath || value === page.imageSrc
}

/** 只移动已有引用节点；完整协议文本之外的正文和未知 atom 不能被当作图组内容。 */
function citationOnlyContent(nodes: ProseMirrorNode[]): { nodes: ProseMirrorNode[]; hasCitation: boolean } | null {
  let pendingText = ''
  let hasCitation = false
  const flush = () => {
    const markers = findProtocolMarkers(pendingText)
    if (markers.some(marker => marker.kind !== 'citation')) return false
    let remaining = pendingText
    for (const marker of markers.reverse()) remaining = remaining.slice(0, marker.start) + remaining.slice(marker.end)
    if (remaining.trim()) return false
    hasCitation ||= markers.length > 0
    pendingText = ''
    return true
  }
  for (const node of nodes) {
    if (node.isText) {
      pendingText += node.text ?? ''
      continue
    }
    if (!flush()) return null
    const id = node.attrs.citationId ?? node.attrs.subjectId ?? node.attrs.id
    if (!node.isInline || !node.isAtom || !node.isLeaf || !['citation', 'citation_marker', 'citation-marker'].includes(node.type.name)
      || typeof id !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/.test(id)) return null
    hasCitation = true
  }
  return flush() ? { nodes, hasCitation } : null
}

/** 图题/图注文字可以替换，已有引用的文字片段、marks 和已知 atom 原样保留。 */
function captionReferenceNodes(caption: ProseMirrorNode): ProseMirrorNode[] | null {
  const references: ProseMirrorNode[] = []
  let pendingText = ''
  let pendingStart = 0
  let valid = true
  const append = (nodes: ProseMirrorNode[]) => {
    references.push(caption.type.schema.text(' '), ...nodes)
  }
  const flush = () => {
    const markers = findProtocolMarkers(pendingText)
    if (markers.some(marker => marker.kind !== 'citation')) return false
    let remaining = pendingText
    for (const marker of [...markers].reverse()) remaining = remaining.slice(0, marker.start) + remaining.slice(marker.end)
    if (remaining.includes('[[') || remaining.includes(']]')) return false
    for (const marker of markers) {
      const nodes: ProseMirrorNode[] = []
      caption.content.cut(pendingStart + marker.start, pendingStart + marker.end).forEach(node => nodes.push(node))
      append(nodes)
    }
    pendingText = ''
    return true
  }
  caption.forEach((node, offset) => {
    if (!valid) return
    if (node.isText) {
      if (!pendingText) pendingStart = offset
      pendingText += node.text ?? ''
    } else {
      const citation = citationOnlyContent([node])
      if (!flush() || !citation?.hasCitation) valid = false
      else append([node])
    }
  })
  return valid && flush() ? references : null
}

/** 根级完整图组一次替换；拒绝缺页、重复、分散或夹杂其他正文的图组。 */
export function applyChartPagesReplacement(
  view: EditorView, img: HTMLImageElement, pages: ChartAIEditPage[],
  options: { basePath: string; previousEditId?: string; previousPages?: ChartAIEditPage[]; expectedImageSrc?: string },
): boolean {
  const located = locateImage(view, img)
  if (!located || options.expectedImageSrc !== undefined && located.node.attrs.src !== options.expectedImageSrc) return false
  if (options.previousEditId && (options.previousPages?.length ?? 1) <= 1) {
    let found = 0
    view.state.doc.descendants?.((node) => {
      if (isImageNode(node) && chartEditIdFromSrc(String(node.attrs.src), options.basePath) === options.previousEditId) found++
    })
    if (found > 1) return false
  }
  if (pages.length === 1 && (options.previousPages?.length ?? 1) === 1) {
    return applyChartReplacement(view, img, pages[0]!.imageSrc, pages[0]!)
  }
  if (!pages.length) return false
  const doc = view.state.doc
  const blocks: { node: ProseMirrorNode; from: number; to: number; image?: ProseMirrorNode; imagePos?: number; citations: ProseMirrorNode[] }[] = []
  doc.forEach((node, from) => {
    let image: ProseMirrorNode | undefined
    let imagePos: number | undefined
    let citations: ProseMirrorNode[] = []
    if (node.type.name === 'image' || node.type.name === 'image-block') {
      image = node
      imagePos = from
    } else if (node.type.name === 'paragraph') {
      const references: ProseMirrorNode[] = []
      const referenceSegments: ProseMirrorNode[][] = [[]]
      let imageCount = 0
      node.forEach((child, offset) => {
        if (isImageNode(child)) {
          imageCount++
          image = child
          imagePos = from + 1 + offset
          referenceSegments.push([])
        } else {
          references.push(child)
          referenceSegments.at(-1)!.push(child)
        }
      })
      if (imageCount !== 1 || referenceSegments.some(segment => !citationOnlyContent(segment))) {
        image = undefined
        imagePos = undefined
      } else citations = references
    }
    blocks.push({ node, from, to: from + node.nodeSize, image, imagePos, citations })
  })
  let first = blocks.findIndex(block => block.imagePos === located.from)
  if (first < 0) return false
  const oldPages = options.previousPages
  if (oldPages && oldPages.length > 1) {
    if (!options.previousEditId) return false
    const images: { node: ProseMirrorNode; from: number }[] = []
    doc.descendants((node, from) => {
      if (isImageNode(node) && chartEditIdFromSrc(String(node.attrs.src), options.basePath) === options.previousEditId) images.push({ node, from })
    })
    if (images.length !== oldPages.length || images.some((item, i) => !imageMatchesPage(String(item.node.attrs.src), oldPages[i]!, options.basePath))) return false
    first = blocks.findIndex(block => block.imagePos === images[0]!.from)
    if (first < 0) return false
  }
  const template = blocks[first]!.image
  if (!template) return false
  let cursor = first
  const expected = oldPages && oldPages.length > 1 ? oldPages : [null]
  const citations: ProseMirrorNode[] = []
  for (const page of expected) {
    const block = blocks[cursor]
    if (!block?.image || page && !imageMatchesPage(String(block.image.attrs.src), page, options.basePath)) return false
    citations.push(...block.citations)
    cursor++
    const seenCaptions = new Set<string>()
    for (let n = 0; n < 2; n++) {
      const caption = blocks[cursor]?.node
      if (!caption?.isTextblock) break
      const matched = /^(图表|图注)\s*[:：]\s*(.*)$/.exec(caption.textContent.trim())
      if (!matched) break
      if (seenCaptions.has(matched[1]!)) return false
      seenCaptions.add(matched[1]!)
      if (page && matched[2] !== (matched[1] === '图表' ? page.title : page.altText)) return false
      const references = captionReferenceNodes(caption)
      if (references === null) return false
      citations.push(...references)
      cursor++
    }
  }
  const paragraph = view.state.schema.nodes.paragraph
  if (!paragraph) return false
  const nodes: ProseMirrorNode[] = []
  for (const [index, page] of pages.entries()) {
    const attrs = { ...template.attrs, src: page.imageSrc,
      ...(template.type.name === 'image-block' ? { caption: page.altText ?? '' } : { alt: page.altText ?? '' }) }
    const image = template.type.create(attrs)
    nodes.push(image.isInline ? paragraph.create(null, [image, ...(index === 0 ? citations : [])]) : image)
    if (page.title) nodes.push(paragraph.create(null, view.state.schema.text(`图表：${page.title}`)))
    if (page.altText && image.isInline) nodes.push(paragraph.create(null, view.state.schema.text(`图注：${page.altText}`)))
  }
  if (!template.isInline && citations.length) nodes.push(paragraph.create(null, citations))
  const tr = view.state.tr.replaceWith(blocks[first]!.from, blocks[cursor - 1]!.to, nodes)
  if (!protocolMarkersUnchanged(doc.textContent, tr.doc.textContent)) return false
  view.dispatch(closeHistory(tr))
  return true
}

export interface ChartAIEditHooks {
  /** 接受替换并写回正文后触发（自动保存由通用文档变更链路接管）。 */
  onReplaced?: (editId: string) => void
  onError?: (code: string) => void
}

export interface ChartAIEditController {
  open(img: HTMLImageElement): void
  dispose(): void
}

interface EditTarget {
  img: HTMLImageElement
  chartId: string
  imagePath: string
  title: string
  altText: string
  visualForm?: string | null
  expectedSha256?: string
  aiAvailable?: boolean
  aiReason?: string
  standardForms?: string[]
  previousEditId?: string
  /** 正文中的原图组；继续预览未接受的结果时保持不变。 */
  bodyEditId?: string
  bodyPages?: ChartAIEditPage[]
  bodyImageSrc?: string
}

export function createChartAIEdit(options: {
  view: EditorView
  client: ReportEditorClient
  basePath: string
  /** 可显式使用定时轮询；默认由服务端短时等待任务完成。 */
  pollIntervalMs?: number
  hooks?: ChartAIEditHooks
}): ChartAIEditController {
  const { view, client, basePath, hooks } = options
  const pollIntervalMs = options.pollIntervalMs ?? 1500
  let modal: AskAISession | null = null
  let target: EditTarget | null = null
  let openedImage: HTMLImageElement | null = null
  let instructionDraft = ''
  let progressClock: number | undefined
  let runningEditId: string | null = null
  let cancelled = false
  // 仅销毁时停止回调；收起侧栏不取消任务，也不抢回焦点。
  let dismissed = false
  // 关闭或切换目标后，旧异步请求不得再操作当前窗口与任务身份。
  let generation = 0
  const invalidateCurrent = () => {
    window.clearInterval(progressClock)
    generation++
    cancelled = true
    if (runningEditId && target) {
      void client.cancelChartAiEdit(target.chartId, runningEditId).catch(() => undefined)
    }
    runningEditId = null
  }

  const ensureModal = () => {
    if (modal) return modal
    modal = askAIPanel().createSession({
      kind: 'chart', label: '图表',
      content: `
        <div class="panel-header">
          <h2>AI 改图</h2>
          <p class="chart-ai-subtitle" data-role="subtitle">用自然语言调整这张图，改后先对比再替换</p>
        </div>
        <div class="chart-ai-body" data-role="body"></div>
      `,
    })
    return modal
  }

  const bodyOf = () => {
    const body = ensureModal().card.querySelector<HTMLElement>('[data-role="body"]')
    if (!body) throw new Error('chart ai panel body missing')
    return body
  }

  function baseTitleOf(img: HTMLImageElement): string {
    const block = img.closest('.milkdown-image-block')
    const caption = block?.nextElementSibling
    if (caption?.matches('p')) {
      const text = caption.textContent?.trim() ?? ''
      if (/^图表\s*[:：]/.test(text)) return text.replace(/^图表\s*[:：]\s*/, '')
    }
    return img.getAttribute('title') ?? img.alt ?? ''
  }

  async function resolveTarget(img: HTMLImageElement): Promise<EditTarget | { error: string }> {
    const src = img.getAttribute('src') ?? ''
    const altText = img.alt || baseTitleOf(img)
    try {
      // 已接受过的改图：按登记找回所属图表，以该改图为底图继续调整。
      const editId = chartEditIdFromSrc(src, basePath)
      let record: Awaited<ReturnType<typeof client.chartEditRecord>> | null = null
      if (editId) {
        try { record = await client.chartEditRecord(editId) } catch (error) {
          if (!(error instanceof ReportEditorApiError && error.status === 404)) throw error
        }
      }
      const charts = record ? [] : (await client.charts()).charts ?? []
      const matched = record ? null : matchChartForImage(charts, src, basePath)
      const chart = record
        ? { chartId: record.chartId, imagePath: record.imagePath }
        : matched
          ? { chartId: matched.chartId, imagePath: matched.imagePath }
          : null
      if (!chart) return { error: '这张图不在当前版本的登记图表中，无法改图。' }
      const availability = await client.chartAiAvailability(chart.chartId)
      if (!availability.available && !availability.standardAvailable) {
        return { error: chartAiUnavailableReason(availability.reason) }
      }
      return {
        img,
        chartId: chart.chartId,
        imagePath: record?.pages?.find(page => imageMatchesPage(src, page, basePath))?.imagePath ?? chart.imagePath,
        title: baseTitleOf(img),
        altText,
        visualForm: matched?.visualForm ?? null,
        expectedSha256: record?.pages?.find(page => imageMatchesPage(src, page, basePath))?.sha256 ?? availability.expectedSha256,
        aiAvailable: availability.available,
        aiReason: availability.reason,
        standardForms: availability.standardChartCapabilities?.forms,
        bodyImageSrc: locateImage(view, img)?.node.attrs.src as string | undefined,
        ...(record ? { previousEditId: record.editId, bodyEditId: record.editId, bodyPages: record.pages } : {}),
      }
    } catch {
      return { error: '无法获取图表登记信息，请稍后重试。' }
    }
  }

  function renderInputPhase(current: EditTarget, note?: string, failed = false, retainReview = false) {
    if (dismissed) return
    target = current
    ensureModal().setLabel(current.title || current.altText || '图表')
    if (!retainReview) ensureModal().setState(failed ? 'error' : 'idle')
    ensureModal().setThumbnail(assetUrl(basePath, current.imagePath))
    const output = bodyOf()
    const focusInput = modal?.visible && (output.contains(document.activeElement) || modal.composer.contains(document.activeElement) || document.activeElement === modal.closeButton)
    const body = document.createElement('div')
    const fieldId = (name: string) => `${name}${ensureModal().idSuffix}`
    body.innerHTML = `
      <div class="chart-ai-current">
        <img alt="当前图表" src="${assetUrl(basePath, current.imagePath)}">
        <div class="chart-ai-current-meta">
          <p class="chart-ai-chart-title"></p>
          <p class="chart-ai-chart-alt"></p>
        </div>
      </div>
      ${note ? `<p class="chart-ai-note" role="status"></p>` : ''}
      <details class="chart-ai-standard">
        <summary>模板与快捷调整 <span>选择后预览</span></summary>
        <label class="chart-ai-label" for="${fieldId('chart-ai-standard-preset')}">标准图形与排版</label>
        <div class="chart-ai-standard-controls">
          <select id="${fieldId('chart-ai-standard-preset')}" aria-describedby="${fieldId('chart-ai-standard-help')}"><option value="">选择一种图形或调整方式</option></select>
          <button type="button" class="${buttonClasses('secondary')}" data-action="apply-standard" disabled>应用所选预设</button>
        </div>
        <p id="${fieldId('chart-ai-standard-help')}" class="chart-ai-hint" aria-live="polite">结构化预设直接执行；有自由要求时，请明确使用 AI 生成。</p>
      </details>
      <div class="ask-ai-input-form">
      <label class="chart-ai-label" for="${fieldId('chart-ai-instruction')}">${retainReview ? '继续调整新图' : '改图要求'}</label>
      <textarea id="${fieldId('chart-ai-instruction')}" rows="3" maxlength="2000"
        placeholder="例如：改成横向柱状图并按金额降序，显示数值标签"></textarea>
      <div class="chart-ai-quick" role="group" aria-label="快捷指令"></div>
      <div class="chart-ai-actions">
        <button type="button" class="${buttonClasses('primary')}" data-action="submit">使用 AI 生成改图</button>
        <span class="chart-ai-hint" data-role="input-count"></span>
      </div>
      <p class="chart-ai-hint">Ctrl / ⌘ + Enter 发送 · 超出已登记数据的要求会说明原因。</p>
      </div>
    `
    body.querySelector<HTMLElement>('.chart-ai-chart-title')!.textContent = `标题：${current.title || '（无）'}`
    body.querySelector<HTMLElement>('.chart-ai-chart-alt')!.textContent = `图注：${current.altText || '（无）'}`
    body.querySelector<HTMLElement>('.chart-ai-chart-title')!.title = current.title || ''
    body.querySelector<HTMLElement>('.chart-ai-chart-alt')!.title = current.altText || ''
    if (note) body.querySelector<HTMLElement>('.chart-ai-note')!.textContent = note
    const textarea = body.querySelector<HTMLTextAreaElement>(`#${fieldId('chart-ai-instruction')}`)!
    textarea.value = instructionDraft
    const presets = body.querySelector<HTMLSelectElement>(`#${fieldId('chart-ai-standard-preset')}`)!
    const presetHelp = body.querySelector<HTMLElement>(`#${fieldId('chart-ai-standard-help')}`)!
    const applyPreset = body.querySelector<HTMLButtonElement>('[data-action="apply-standard"]')!
    const standardDetails = body.querySelector<HTMLElement>('.chart-ai-standard')!
    for (const preset of STANDARD_CHART_PRESETS.filter(item => !('standard' in item)
      || !current.standardForms || current.standardForms.includes(item.standard.standardForm))) {
      const option = document.createElement('option')
      option.value = preset.id
      option.textContent = preset.name
      presets.append(option)
    }
    presets.addEventListener('change', () => {
      const preset = STANDARD_CHART_PRESETS.find(item => item.id === presets.value)
      applyPreset.disabled = !preset
      presetHelp.textContent = preset ? `${preset.description} 数据不满足时会说明原因，不补造数据。` : '选择后可补充字段、单位、颜色等要求；会先检查已登记数据是否满足条件。'
    })
    let appliedPreset = ''
    applyPreset.addEventListener('click', () => {
      const preset = STANDARD_CHART_PRESETS.find(item => item.id === presets.value)
      if (!preset) return
      if ('standard' in preset && !textarea.value.trim()) {
        if (!current.expectedSha256) {
          presetHelp.textContent = '底图身份不可读取，请刷新后重试；未启动改图。'
          return
        }
        void runEdit(current, `应用预设：${preset.name}`, { standard: preset.standard,
          baseImagePath: current.imagePath, expectedSha256: current.expectedSha256,
          ...(current.previousEditId ? { previousEditId: current.previousEditId } : {}),
          ...(current.title ? { baseTitle: current.title } : {}),
          ...(current.altText ? { baseAltText: current.altText } : {}),
        })
        return
      }
      const custom = appliedPreset ? textarea.value.replace(appliedPreset, '').replace(/^；|；$/g, '').trim() : textarea.value.trim()
      const instruction = custom ? `${custom}；${preset.instruction}` : preset.instruction
      if (instruction.length > MAX_INSTRUCTION_CHARS) {
        presetHelp.textContent = '改图要求合计不能超过2000字，请缩短补充要求后再填入。'
        textarea.focus()
        return
      }
      textarea.value = instruction
      textarea.dispatchEvent(new Event('input'))
      appliedPreset = preset.instruction
      presetHelp.textContent = '此要求包含自由描述，需要点击“使用 AI 生成改图”；不会作为无模型模板执行。'
      textarea.focus()
    })
    const quick = body.querySelector<HTMLElement>('.chart-ai-quick')!
    for (const command of quickCommandsForForm(current.visualForm)) {
      const chip = document.createElement('button')
      chip.type = 'button'
      chip.className = 'chart-ai-chip'
      chip.textContent = command
      chip.addEventListener('click', () => {
        const merged = textarea.value.trim() ? `${textarea.value.trim()}；${command}` : command
        textarea.value = merged.slice(0, MAX_INSTRUCTION_CHARS)
        textarea.dispatchEvent(new Event('input'))
        textarea.focus()
      })
      quick.append(chip)
    }
    const submit = body.querySelector<HTMLButtonElement>('[data-action="submit"]')!
    const inputCount = body.querySelector<HTMLElement>('[data-role="input-count"]')!
    const syncInput = () => {
      instructionDraft = textarea.value
      submit.disabled = current.aiAvailable === false || !textarea.value.trim()
      inputCount.textContent = `${textarea.value.length} / ${MAX_INSTRUCTION_CHARS}`
    }
    textarea.addEventListener('input', syncInput)
    textarea.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
        event.preventDefault(); if (!submit.disabled) submit.click()
      }
    })
    syncInput()
    if (current.aiAvailable === false) submit.title = chartAiUnavailableReason(current.aiReason)
    const chartTemplates = (client as ReportEditorClient & {
      chartTemplates?: (chartId: string) => Promise<{ templates: { templateId: string; name: string; available: boolean; reason?: string }[] }>
    }).chartTemplates
    if (typeof chartTemplates === 'function') {
      const owner = generation
      void chartTemplates.call(client, current.chartId).then((catalog) => {
        if (owner !== generation || !textarea.isConnected || dismissed) return
        const templates = document.createElement('div')
        templates.className = 'chart-ai-templates'
        templates.setAttribute('role', 'group')
        templates.setAttribute('aria-label', '预制图模板')
        for (const item of catalog.templates) {
          const control = createAITemplateCard(item, 'chart', () => {
            if (textarea.value.trim()) {
              textarea.value = `${textarea.value.trim()}；参考模板：${item.name}`.slice(0, MAX_INSTRUCTION_CHARS)
              textarea.dispatchEvent(new Event('input'))
              presetHelp.textContent = '包含自由要求，请点击“使用 AI 生成改图”。'
              return
            }
            void runTemplate(current, item.templateId, '')
          })
          templates.append(control)
        }
        standardDetails.append(templates)
      }).catch(() => undefined)
    }
    submit.addEventListener('click', () => {
      const instruction = textarea.value.trim()
      if (!instruction) {
        textarea.focus()
        return
      }
      void runEdit(current, instruction)
    })
    const form = body.querySelector<HTMLElement>('.ask-ai-input-form')!
    if (retainReview) output.append(standardDetails)
    else output.replaceChildren(...body.childNodes)
    ensureModal().mountComposer(form)
    if (focusInput) textarea.focus()
  }

  async function runTemplate(current: EditTarget, templateId: string, _instruction: string) {
    await runEdit(current, `套用模板：${templateId}`, undefined, templateId)
  }

  async function runEdit(current: EditTarget, instruction: string, standard?: ChartStandardEditRequest, templateId?: string) {
    const owner = generation
    const body = bodyOf()
    cancelled = false
    instructionDraft = standard || templateId ? instructionDraft : instruction
    ensureModal().addMessage('user', instruction)
    ensureModal().setState('running')
    body.innerHTML = `
      <div class="chart-ai-progress" role="status" aria-live="polite">
        <div class="chart-ai-current"><img alt="当前图表" src="${assetUrl(basePath, current.imagePath)}"></div>
        <p class="chart-ai-stage" data-role="stage">${STAGE_LABELS.queued}</p>
        <p class="ask-ai-elapsed" data-role="elapsed">已用 0 秒</p>
        <p class="chart-ai-hint">可收起侧栏继续阅读，完成后从 Ask AI 恢复预览。</p>
        <div class="chart-ai-actions">
          <button type="button" class="${buttonClasses('danger')}" data-action="cancel">取消改图</button>
        </div>
      </div>
    `
    const stage = body.querySelector<HTMLElement>('[data-role="stage"]')!
    const elapsed = body.querySelector<HTMLElement>('[data-role="elapsed"]')!
    const cancel = body.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
    cancel.addEventListener('click', () => {
      if (owner !== generation) return
      cancelled = true
      cancel.disabled = true
      stage.textContent = '正在取消…'
      invalidateCurrent()
      renderInputPhase(current, '已取消本次改图，原图保持不变。')
    })
    const started = performance.now()
    let stageLabel = STAGE_LABELS.queued
    const clock = progressClock = window.setInterval(() => {
      if (!cancelled) elapsed.textContent = `已用 ${Math.floor((performance.now() - started) / 1000)} 秒`
    }, 1000)
    try {
      const payload = {
        ...(current.imagePath ? { baseImagePath: current.imagePath } : {}),
        ...(current.title ? { baseTitle: current.title } : {}),
        ...(current.altText ? { baseAltText: current.altText } : {}),
        ...(current.previousEditId ? { previousEditId: current.previousEditId } : {}),
      }
      const startedResponse = templateId ? await client.startChartTemplateEdit(current.chartId, { ...payload, templateId })
        : standard ? await client.startChartStandardEdit(current.chartId, standard) : await client.startChartAiEdit(current.chartId, { ...payload, instruction })
      if (owner !== generation || dismissed) {
        void client.cancelChartAiEdit(current.chartId, startedResponse.editId).catch(() => undefined)
        return
      }
      runningEditId = startedResponse.editId
      if (cancelled) {
        // 服务端返回编号前已取消：补发取消请求，避免后台任务继续占用该图与额度。
        void client.cancelChartAiEdit(current.chartId, runningEditId).catch(() => undefined)
      }
      let transientFailures = 0
      let firstStatus = true
      for (;;) {
        const waitMs = !firstStatus && transientFailures === 0 && options.pollIntervalMs === undefined ? 1500 : 0
        if (!firstStatus) await new Promise((resolve) => setTimeout(resolve,
          transientFailures ? pollIntervalMs : options.pollIntervalMs ?? 0))
        firstStatus = false
        if (owner !== generation) return
        if (cancelled) break
        let state: Awaited<ReturnType<typeof client.chartAiEditStatus>>
        try {
          state = waitMs ? await client.chartAiEditStatus(current.chartId, runningEditId, waitMs)
            : await client.chartAiEditStatus(current.chartId, runningEditId)
          transientFailures = 0
        } catch (error) {
          if (error instanceof TypeError && ++transientFailures < 5) continue
          throw error
        }
        if (owner !== generation) return
        if (cancelled) break
        stageLabel = STAGE_LABELS[String(state.stage ?? '')] ?? '正在处理改图…'
        stage.textContent = stageLabel
        if (dismissed) return
        if (state.status === 'succeeded') {
          renderReviewPhase(current, state as unknown as ChartAIEditSuccess)
          return
        }
        if (state.status === 'failed' || state.status === 'cancelled') {
          const error = (state as { error?: { code?: string; message?: string; skipped?: { request: string; reason: string }[] } }).error
          hooks?.onError?.(error?.code ?? 'report_editor_chart_ai_failed')
          const skippedNote = (error?.skipped ?? []).map(item => item.reason).join('；')
          renderInputPhase(
            current,
            error?.message
              ? `${error.message}${skippedNote ? `（${skippedNote}）` : ''}`
              : '改图未完成，原图保持不变，可调整要求后重试。',
            state.status === 'failed',
          )
          return
        }
      }
      if (cancelled && !dismissed) {
        renderInputPhase(current, '已取消本次改图，原图保持不变。')
      }
    } catch (error) {
      if (owner !== generation || dismissed) return
      hooks?.onError?.(error instanceof Error ? error.message : 'report_editor_chart_ai_failed')
      if (!dismissed) renderInputPhase(current, '改图请求失败，请稍后重试；原图保持不变。', true)
    } finally {
      window.clearInterval(clock)
      if (owner === generation) runningEditId = null
    }
  }

  function renderReviewPhase(current: EditTarget, result: ChartAIEditSuccess) {
    const pages = chartResultPages(result)
    if (!pages) {
      renderInputPhase(current, '分页结果不完整，未替换正文。请重新生成或联系管理员。', true)
      return
    }
    const body = bodyOf()
    ensureModal().setState('ready')
    ensureModal().addMessage('assistant', '新图已生成。请查看变更和告警，确认后替换到正文。')
    const changes: string[] = []
    if (result.changes.title) changes.push(`标题改为「${result.changes.title}」`)
    if (result.changes.altText) changes.push(`图注改为「${result.changes.altText}」`)
    if (result.changes.visualForm) changes.push(`图形改为「${result.changes.visualForm}」`)
    if (result.planningRoute === 'direct') changes.push('确定性模板预览；未调用 AI 参数规划或自由绘图。')
    if (!result.visualInspection.reviewed) changes.push('仅完成确定性图片检查，尚未进行独立模型视觉审查。')
    if (pages.length > 1) changes.push(`完整生成 ${pages.length} 页，接受时将一次替换整组图表。`)
    if (result.changes.plotDataUnchanged) {
      changes.push('作图数据未变（数值与原图一致）')
    } else {
      const added = result.changes.dataBindingsAdded ?? []
      changes.push(
        added.length
          ? `作图数据换绑：${added.map(item => `${item.dataPath}（${item.fields.join('、')}）`).join('；')}`
          : '作图数据有变化',
      )
    }
    body.innerHTML = `
      <div class="chart-ai-view-switch" role="group" aria-label="选择预览图">
        <button type="button" class="${buttonClasses('secondary')}" data-action="view-new" aria-pressed="true">新图</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="view-original" aria-pressed="false">原图</button>
      </div>
      <div class="chart-ai-compare" role="group" aria-label="改图前后对比">
        <figure class="chart-ai-compare-item" data-compare-view="original" hidden>
          <figcaption>原图</figcaption>
          <img alt="改图前的原图" src="${assetUrl(basePath, current.imagePath)}">
        </figure>
        <div class="chart-ai-pages" aria-label="全部改图结果"></div>
      </div>
      <ul class="chart-ai-changes" aria-label="变更清单"></ul>
      ${result.warnings.length ? '<ul class="chart-ai-warnings" role="alert" aria-label="软告警"></ul>' : ''}
      ${result.skipped.length ? '<ul class="chart-ai-skipped" aria-label="未执行的要求"></ul>' : ''}
      <div class="chart-ai-actions">
        <p class="ask-ai-adopt-note">尚未修改正文</p>
        <button type="button" class="${buttonClasses('primary')}" data-action="accept">采用到正文</button>
        <button type="button" class="${buttonClasses('secondary')}" data-action="continue">继续调整</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="discard">放弃</button>
      </div>
      <p class="chart-ai-hint">接受后正文图片与图注一并替换，可用撤销（⌘/Ctrl+Z）恢复原图；导出新版本后改图与原图一样可追溯。</p>
    `
    const pageList = body.querySelector<HTMLElement>('.chart-ai-pages')!
    const original = body.querySelector<HTMLElement>('[data-compare-view="original"]')!
    for (const view of ['original', 'new']) {
      body.querySelector<HTMLButtonElement>(`[data-action="view-${view}"]`)!.addEventListener('click', () => {
        original.hidden = view !== 'original'
        pageList.hidden = view !== 'new'
        body.querySelector('[data-action="view-original"]')!.setAttribute('aria-pressed', String(view === 'original'))
        body.querySelector('[data-action="view-new"]')!.setAttribute('aria-pressed', String(view === 'new'))
      })
    }
    for (const page of pages) {
      const figure = document.createElement('figure')
      figure.className = 'chart-ai-compare-item'
      const caption = document.createElement('figcaption')
      caption.textContent = pages.length > 1 ? `新图 · 第 ${page.pageNumber}/${page.pageCount} 页` : '新图（AI 改图结果）'
      const image = document.createElement('img')
      image.alt = page.altText || `AI 改图生成的新图${pages.length > 1 ? `第${page.pageNumber}页` : ''}`
      image.src = assetUrl(basePath, page.imagePath)
      figure.append(caption, image)
      pageList.append(figure)
    }
    const changeList = body.querySelector<HTMLElement>('.chart-ai-changes')!
    for (const change of changes) {
      const item = document.createElement('li')
      item.textContent = change
      changeList.append(item)
    }
    const warnings = body.querySelector<HTMLElement>('.chart-ai-warnings')
    if (warnings) for (const warning of result.warnings) {
      const item = document.createElement('li')
      item.textContent = warning
      warnings.append(item)
    }
    const skipped = body.querySelector<HTMLElement>('.chart-ai-skipped')
    if (skipped) for (const item of result.skipped) {
      const entry = document.createElement('li')
      entry.textContent = `「${item.request}」未执行：${item.reason}`
      skipped.append(entry)
    }
    body.querySelector<HTMLButtonElement>('[data-action="accept"]')!.addEventListener('click', () => {
      let bodyImage = openedImage ?? current.img
      // 后台完成时正文可能因装饰重绘而更换 DOM；只恢复唯一同源图片，歧义仍拒绝。
      if (!bodyImage.isConnected) {
        const source = bodyImage.getAttribute('src')
        const matches = source ? [...view.dom.querySelectorAll<HTMLImageElement>('img')]
          .filter(image => image.getAttribute('src') === source) : []
        if (matches.length === 1) bodyImage = openedImage = matches[0]!
      }
      const replaced = applyChartPagesReplacement(view, bodyImage, pages, {
        basePath, previousEditId: current.bodyEditId, previousPages: current.bodyPages, expectedImageSrc: current.bodyImageSrc,
      })
      if (!replaced) {
        hooks?.onError?.('report_editor_chart_ai_target_missing')
        renderInputPhase(current, '未能完整定位正文图表组（可能缺页、分散或包含其他正文），尚未替换。请刷新并从完整图组重新打开。', true)
        return
      }
      hooks?.onReplaced?.(result.editId)
      openedImage = null
      const adopted = view.state.doc
      const positions = (doc: ProseMirrorNode) => {
        const found: { node: ProseMirrorNode; pos: number }[] = []
        doc.descendants((node, pos) => {
          if (isImageNode(node) && chartEditIdFromSrc(String(node.attrs.src), basePath) === result.editId) found.push({ node, pos })
        })
        return found
      }
      const originalGroup = positions(adopted)
      let adoptedImage: HTMLImageElement | null = null
      ensureModal().notifyReplaced({
        locate: () => {
          const currentGroup = positions(view.state.doc)
          if (currentGroup.length !== pages.length || originalGroup.length !== pages.length
            || currentGroup.some((item, index) => !imageMatchesPage(String(item.node.attrs.src), pages[index]!, basePath) || !item.node.eq(originalGroup[index]!.node))) return false
          const span = (items: typeof currentGroup, doc: ProseMirrorNode) => doc.slice(items[0]!.pos, items.at(-1)!.pos + items.at(-1)!.node.nodeSize).content
          if (!span(currentGroup, view.state.doc).eq(span(originalGroup, adopted))) return false
          const matches = [...view.dom.querySelectorAll<HTMLImageElement>('img')].filter(image => imageMatchesPage(image.getAttribute('src') ?? '', pages[0]!, basePath))
          if (matches.length !== 1 || locateImage(view, matches[0]!)?.from !== currentGroup[0]!.pos) return false
          adoptedImage = matches[0]!
          adoptedImage.scrollIntoView?.({ block: 'center', behavior: 'auto' })
          return true
        },
        continueEditing: () => { if (adoptedImage) controller.open(adoptedImage) },
      })
    })
    body.querySelector<HTMLButtonElement>('[data-action="discard"]')!.addEventListener('click', () => {
      openedImage = null
      ensureModal().mountComposer(null)
      ensureModal().setState('idle')
      body.innerHTML = '<p class="chart-ai-note" role="status">已放弃本轮结果。继续编辑时，请在正文选择图表。</p>'
      modal?.close()
    })
    body.querySelector<HTMLButtonElement>('[data-action="continue"]')!.addEventListener('click', () => {
      modal?.focusComposer()
    })
    ensureModal().mountReviewActions(body.querySelector<HTMLElement>('.chart-ai-actions')!)
    instructionDraft = ''
    renderInputPhase(
      {
        ...current,
        imagePath: result.imagePath,
        previousEditId: result.editId,
        title: result.changes.title ?? current.title,
        altText: result.changes.altText ?? current.altText,
        visualForm: result.changes.visualForm ?? current.visualForm,
        expectedSha256: pages[0]?.sha256,
      },
      undefined, false, true,
    )
  }

  const controller: ChartAIEditController = {
    open(img: HTMLImageElement) {
      if (openedImage?.getAttribute('src') === img.getAttribute('src') && modal) {
        openedImage = img
        if (target) target.img = img
        modal.open(); return
      }
      invalidateCurrent()
      openedImage = img
      instructionDraft = ''
      modal?.card.querySelector('.ask-ai-messages')?.replaceChildren()
      const owner = generation
      dismissed = false
      const body = bodyOf()
      ensureModal().mountComposer(null)
      body.innerHTML = `
        <div class="chart-ai-progress" role="status" aria-live="polite">
          <p>正在读取图表信息…</p>
        </div>
      `
      ensureModal().open()
      void resolveTarget(img).then((resolved) => {
        if (owner !== generation || dismissed) return
        if ('error' in resolved) {
          openedImage = null
          ensureModal().setState('error')
          body.innerHTML = `
            <div class="chart-ai-unavailable" role="alert">
              <p></p>
              <div class="chart-ai-actions">
                <button type="button" class="${buttonClasses('quiet')}" data-action="close">关闭</button>
              </div>
            </div>
          `
          body.querySelector('p')!.textContent = resolved.error
          body.querySelector('[data-action="close"]')!.addEventListener('click', () => modal?.close())
          hooks?.onError?.('report_editor_chart_ai_unavailable')
          return
        }
        // 登记请求期间正文可能重绘；恢复到同资源的新 DOM 后，以当前节点接受结果。
        if (openedImage) {
          resolved.img = openedImage
          resolved.bodyImageSrc = locateImage(view, openedImage)?.node.attrs.src as string | undefined
        }
        renderInputPhase(resolved)
      })
    },
    dispose() {
      invalidateCurrent()
      dismissed = true
      modal?.remove()
      modal = null
    },
  }
  return controller
}
