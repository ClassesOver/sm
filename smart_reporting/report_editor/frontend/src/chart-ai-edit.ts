import type { EditorView } from '@milkdown/kit/prose/view'
import type { Node as ProseMirrorNode } from '@milkdown/kit/prose/model'
import { closeHistory } from '@milkdown/kit/prose/history'
import { createElement, CircleAlert } from 'lucide'
import { buttonClasses } from './button'
import { askAIPanel, type AskAISession } from './ask-ai-panel'
import { createAITemplateCard } from './ai-template-card'
import { createModal } from './modal'
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

/** 阶段时间线：服务端 8 个细阶段收成 4 个粗阶段展示，细节仍由进度标题给出。 */
const STAGE_GROUPS: { label: string; stages: string[] }[] = [
  { label: '核验底图', stages: ['queued', 'check'] },
  { label: '理解与规划', stages: ['plan', 'materialize'] },
  { label: '绘图与检查', stages: ['compile', 'draw', 'inspect'] },
  { label: '登记结果', stages: ['register'] },
]

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

/** 已用时统一 mm:ss 显示（改图/改表进度共用同一读法）。 */
export function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

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

/** 标准（确定性）预设不可用时的常显说明：点名受影响的预设，并指出 AI 路径仍可用。 */
export function standardUnavailableText(reason?: string): string {
  const detail = reason === 'unconfigured' ? '服务未配置完成'
    : reason === 'read_only' ? '当前会话为只读分享会话'
      : reason === 'snapshot_expired' ? '该版本的数据来源已结束保留期'
        : '服务暂不可用'
  return `标准预设${detail}，饼图、环形图、雷达图、漏斗图、桑基图暂不可用；其余预设与自由要求可继续用 AI 生成。`
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
  standardAvailable?: boolean
  standardReason?: string
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
  let actionModal: ReturnType<typeof createModal> | null = null
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
      content: '<div class="chart-ai-body" data-role="body"></div>',
    })
    return modal
  }

  const ensureActionModal = () => {
    if (actionModal) return actionModal
    actionModal = createModal({
      root: document.body,
      overlayClass: 'chart-ai-actions-modal',
      cardClass: 'chart-ai-actions-card',
      closeLabel: '关闭模板与快捷操作',
      label: '模板与快捷操作',
      content: '<div class="chart-ai-actions-dialog"><h2>模板与快捷操作</h2><div class="chart-ai-action-dialog-body"></div></div>',
    })
    return actionModal
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
        visualForm: record?.visualForm ?? matched?.visualForm ?? null,
        expectedSha256: record?.pages?.find(page => imageMatchesPage(src, page, basePath))?.sha256 ?? availability.expectedSha256,
        aiAvailable: availability.available,
        aiReason: availability.reason,
        standardAvailable: availability.standardAvailable,
        standardReason: availability.standardReason,
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
    actionModal?.close()
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
        <div class="chart-ai-standard-controls">
          <select id="${fieldId('chart-ai-standard-preset')}" aria-describedby="${fieldId('chart-ai-standard-help')}"><option value="">选择一种图形或调整方式</option></select>
          <button type="button" class="${buttonClasses('secondary')}" data-action="apply-standard" disabled>应用所选预设</button>
        </div>
        <p id="${fieldId('chart-ai-standard-help')}" class="chart-ai-hint" aria-live="polite">预设直接执行；自由要求请用 AI 生成。</p>
        <label class="chart-ai-hint" for="${fieldId('chart-ai-standard-reset')}">
          <input id="${fieldId('chart-ai-standard-reset')}" type="checkbox" aria-describedby="${fieldId('chart-ai-standard-reset-help')}">
          套用预设时重置旧图形设置
        </label>
        <p id="${fieldId('chart-ai-standard-reset-help')}" class="chart-ai-hint">仅对直接应用的预设生效；作图数据不变。</p>
      </details>
      <div class="ask-ai-input-form">
      <div class="chart-ai-input-heading">
        <label class="chart-ai-label" for="${fieldId('chart-ai-instruction')}">${retainReview ? '继续调整新图' : '改图要求'}</label>
        <button type="button" class="${buttonClasses('secondary')} chart-ai-actions-trigger" data-action="show-chart-actions" aria-haspopup="dialog">模板与快捷操作</button>
      </div>
      <textarea id="${fieldId('chart-ai-instruction')}" rows="3" maxlength="2000"
        placeholder="例如：改成横向柱状图并按金额降序，显示数值标签"></textarea>
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
    if (note) {
      const noteElement = body.querySelector<HTMLElement>('.chart-ai-note')!
      noteElement.textContent = note
      if (failed) {
        noteElement.dataset.tone = 'warn'
        if (instructionDraft.trim()) {
          const retry = document.createElement('button')
          retry.type = 'button'
          retry.className = buttonClasses('secondary')
          retry.textContent = '重新生成'
          retry.addEventListener('click', () => {
            const submitButton = ensureModal().composer.querySelector<HTMLButtonElement>('[data-action="submit"]')
            if (submitButton && !submitButton.disabled) submitButton.click()
          })
          noteElement.after(retry)
        }
      }
    }
    const textarea = body.querySelector<HTMLTextAreaElement>(`#${fieldId('chart-ai-instruction')}`)!
    textarea.value = instructionDraft
    const presets = body.querySelector<HTMLSelectElement>(`#${fieldId('chart-ai-standard-preset')}`)!
    const presetHelp = body.querySelector<HTMLElement>(`#${fieldId('chart-ai-standard-help')}`)!
    const applyPreset = body.querySelector<HTMLButtonElement>('[data-action="apply-standard"]')!
    const originalStandard = body.querySelector<HTMLDetailsElement>('.chart-ai-standard')!
    const standardDetails = document.createElement('section')
    standardDetails.className = 'chart-ai-standard chart-ai-actions-section'
    const standardTitle = document.createElement('h3'); standardTitle.textContent = '标准图形与排版'
    standardDetails.append(standardTitle)
    originalStandard.querySelector('summary')?.remove()
    standardDetails.append(...Array.from(originalStandard.childNodes))
    originalStandard.replaceWith(standardDetails)
    const resetStandard = body.querySelector<HTMLInputElement>(`#${fieldId('chart-ai-standard-reset')}`)!
    const templateSection = document.createElement('section')
    templateSection.className = 'chart-ai-actions-section chart-ai-actions-templates'
    const templateTitle = document.createElement('h3'); templateTitle.textContent = '预制图模板'
    const templates = document.createElement('div')
    templates.className = 'chart-ai-templates'
    templates.setAttribute('role', 'group')
    templates.setAttribute('aria-label', '预制图模板')
    templateSection.append(templateTitle, templates)
    templateSection.hidden = true
    for (const preset of STANDARD_CHART_PRESETS.filter(item => !('standard' in item)
      || !current.standardForms || current.standardForms.includes(item.standard.standardForm))) {
      const option = document.createElement('option')
      option.value = preset.id
      option.textContent = preset.name
      // 标准执行通道不可用时，确定性预设直接置灰，避免选完点应用才报错。
      if ('standard' in preset && current.standardAvailable === false) option.disabled = true
      presets.append(option)
    }
    if (current.standardAvailable === false) presetHelp.textContent = standardUnavailableText(current.standardReason)
    presets.addEventListener('change', () => {
      const preset = STANDARD_CHART_PRESETS.find(item => item.id === presets.value)
      applyPreset.disabled = !preset
      presetHelp.textContent = preset ? `${preset.description} 数据不满足时会说明原因，不补造数据。` : '选择后可补充字段、单位、颜色等要求；会先检查已登记数据是否满足条件。'
    })
    let appliedPreset = ''
    applyPreset.addEventListener('click', () => {
      const preset = STANDARD_CHART_PRESETS.find(item => item.id === presets.value)
      if (!preset) return
      if ('standard' in preset && current.standardAvailable === false) {
        presetHelp.textContent = standardUnavailableText(current.standardReason)
        return
      }
      if ('standard' in preset && !textarea.value.trim()) {
        if (!current.expectedSha256) {
          presetHelp.textContent = '底图身份不可读取，请刷新后重试；未启动改图。'
          return
        }
        actionModal?.close()
        void runEdit(current, `应用预设：${preset.name}`, { standard: preset.standard,
          ...(resetStandard.checked ? { inheritPreviousStandard: false } : {}),
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
      actionModal?.close()
      textarea.focus()
    })
    const quick = document.createElement('div')
    quick.className = 'chart-ai-quick'
    quick.setAttribute('role', 'group')
    quick.setAttribute('aria-label', '快捷指令')
    const quickSection = document.createElement('section')
    quickSection.className = 'chart-ai-actions-section chart-ai-actions-quick'
    const quickTitle = document.createElement('h3'); quickTitle.textContent = '快捷指令'
    quickSection.append(quickTitle, quick)
    for (const command of quickCommandsForForm(current.visualForm)) {
      const chip = document.createElement('button')
      chip.type = 'button'
      chip.className = 'chart-ai-chip'
      chip.textContent = command
      chip.addEventListener('click', () => {
        const merged = textarea.value.trim() ? `${textarea.value.trim()}；${command}` : command
        textarea.value = merged.slice(0, MAX_INSTRUCTION_CHARS)
        textarea.dispatchEvent(new Event('input'))
        actionModal?.close()
        textarea.focus()
      })
      quick.append(chip)
    }
    if (quick.scrollWidth > quick.clientWidth) quick.dataset.overflow = 'true'
    const submit = body.querySelector<HTMLButtonElement>('[data-action="submit"]')!
    const inputCount = body.querySelector<HTMLElement>('[data-role="input-count"]')!
    const syncInput = () => {
      instructionDraft = textarea.value
      // 输入框随内容自动增高（上限与面板样式一致），不用一直滚动小框。
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
      submit.disabled = current.aiAvailable === false || !textarea.value.trim()
      inputCount.textContent = `${textarea.value.length} / ${MAX_INSTRUCTION_CHARS}`
      inputCount.dataset.level = textarea.value.length >= MAX_INSTRUCTION_CHARS ? 'limit'
        : textarea.value.length >= MAX_INSTRUCTION_CHARS * 0.9 ? 'warn' : ''
    }
    textarea.addEventListener('input', syncInput)
    textarea.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
        event.preventDefault(); if (!submit.disabled) submit.click()
      }
    })
    syncInput()
    if (current.aiAvailable === false) {
      submit.title = chartAiUnavailableReason(current.aiReason)
      // AI 不可用但标准预设仍可用时，原因不能只藏在悬停提示里：常显一行说明，并指出还能走的路。
      const note = document.createElement('p')
      note.className = 'chart-ai-hint'
      note.dataset.role = 'ai-unavailable-note'
      note.setAttribute('role', 'status')
      note.textContent = `${chartAiUnavailableReason(current.aiReason)}可直接应用标准预设。`
      submit.closest('.chart-ai-actions')?.after(note)
    }
    const chartTemplates = (client as ReportEditorClient & {
      chartTemplates?: (chartId: string) => Promise<{ templates: { templateId: string; name: string; available: boolean; reason?: string; recommended?: boolean; recommendationReason?: string }[] }>
    }).chartTemplates
    if (typeof chartTemplates === 'function') {
      templateSection.hidden = false
      const owner = generation
      const skeleton = document.createElement('div')
      skeleton.className = 'ai-template-skeleton'
      skeleton.setAttribute('aria-hidden', 'true')
      skeleton.append(document.createElement('span'), document.createElement('span'))
      templateSection.append(skeleton)
      void chartTemplates.call(client, current.chartId).then((catalog) => {
        skeleton.remove()
        if (owner !== generation || !textarea.isConnected || dismissed) return
        templates.hidden = catalog.templates.length === 0
        const ordered = [...catalog.templates].sort((a, b) => Number(b.recommended ?? false) - Number(a.recommended ?? false) || Number(b.available) - Number(a.available))
        for (const item of ordered) {
          const control = createAITemplateCard(item, 'chart', () => {
            if (textarea.value.trim()) {
              textarea.value = `${textarea.value.trim()}；参考模板：${item.name}`.slice(0, MAX_INSTRUCTION_CHARS)
              textarea.dispatchEvent(new Event('input'))
              presetHelp.textContent = '包含自由要求，请点击“使用 AI 生成改图”。'
              actionModal?.close()
              textarea.focus()
              return
            }
            actionModal?.close()
            void runTemplate(current, item.templateId, '')
          })
          templates.append(control)
        }
      }).catch(() => {
        skeleton.remove()
        if (owner !== generation || dismissed) return
        const loadNote = document.createElement('p')
        loadNote.className = 'chart-ai-hint'
        loadNote.textContent = '模板加载失败，可直接输入要求生成。'
        templateSection.append(loadNote)
      })
    }
    const actionDialog = ensureActionModal()
    actionDialog.card.querySelector<HTMLElement>('.chart-ai-action-dialog-body')!.replaceChildren(standardDetails, templateSection, quickSection)
    body.querySelector<HTMLButtonElement>('[data-action="show-chart-actions"]')!.addEventListener('click', () => actionDialog.open(presets))
    submit.addEventListener('click', () => {
      const instruction = textarea.value.trim()
      if (!instruction) {
        textarea.focus()
        return
      }
      void runEdit(current, instruction)
    })
    const form = body.querySelector<HTMLElement>('.ask-ai-input-form')!
    if (!retainReview) output.replaceChildren(...body.childNodes)
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
        <div class="ai-progress-track" aria-hidden="true"><span class="ai-progress-fill"></span></div>
        <ol class="ai-stage-timeline" data-role="timeline" aria-label="生成阶段">${STAGE_GROUPS.map((group, index) => `<li data-step-state="${index === 0 ? 'current' : 'pending'}"><span class="ai-stage-dot" aria-hidden="true"></span>${group.label}</li>`).join('')}</ol>
        <p class="ask-ai-elapsed" data-role="elapsed" aria-hidden="true">已用时 00:00</p>
        <p class="chart-ai-hint">可收起侧栏，任务继续运行。</p>
        <div class="chart-ai-actions">
          <button type="button" class="${buttonClasses('secondary')}" data-action="cancel">取消改图</button>
        </div>
      </div>
    `
    const stage = body.querySelector<HTMLElement>('[data-role="stage"]')!
    const timeline = body.querySelector<HTMLElement>('[data-role="timeline"]')!
    const setStage = (key: string) => {
      stage.textContent = STAGE_LABELS[key] ?? '正在处理改图…'
      const currentIndex = STAGE_GROUPS.findIndex(group => group.stages.includes(key))
      timeline.querySelectorAll<HTMLElement>('li').forEach((item, index) => {
        const state = currentIndex < 0 ? 'pending' : index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'pending'
        item.dataset.stepState = state
        item.querySelector('.ai-stage-dot')!.textContent = state === 'done' ? '✓' : ''
      })
    }
    const elapsed = body.querySelector<HTMLElement>('[data-role="elapsed"]')!
    const cancel = body.querySelector<HTMLButtonElement>('[data-action="cancel"]')!
    cancel.addEventListener('click', () => {
      if (owner !== generation) return
      cancelled = true
      cancel.disabled = true
      cancel.textContent = '正在取消…'
      stage.textContent = '正在取消…'
      invalidateCurrent()
      renderInputPhase(current, '已取消本次改图，原图保持不变。')
    })
    const started = performance.now()
    const clock = progressClock = window.setInterval(() => {
      if (!cancelled) elapsed.textContent = `已用时 ${formatElapsed(performance.now() - started)}`
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
        setStage(String(state.stage ?? ''))
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
    ensureModal().addMessage('assistant', '新图已生成。')
    const changes: string[] = []
    if (result.changes.title) changes.push(`标题改为「${result.changes.title}」`)
    if (result.changes.altText) changes.push(`图注改为「${result.changes.altText}」`)
    if (result.changes.visualForm) changes.push(`图形改为「${result.changes.visualForm}」`)
    if (result.planningRoute === 'direct') changes.push('确定性模板预览；未调用 AI 参数规划或自由绘图。')
    if (!result.visualInspection.reviewed) changes.push('仅完成确定性图片检查，尚未进行独立模型视觉审查。')
    if (pages.length > 1) changes.push(`完整生成 ${pages.length} 页，接受时将一次替换整组图表。`)
    let dataChange: string | null = null
    if (result.changes.plotDataUnchanged) {
      changes.push('作图数据未变（数值与原图一致）')
    } else {
      const added = result.changes.dataBindingsAdded ?? []
      dataChange = added.length
        ? `作图数据换绑：${added.map(item => `${item.dataPath}（${item.fields.join('、')}）`).join('；')}`
        : '作图数据有变化'
    }
    body.innerHTML = `
      <div class="chart-ai-view-switch" role="group" aria-label="选择预览图">
        <button type="button" class="${buttonClasses('quiet')}" data-action="view-new" aria-pressed="true">新图</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="view-original" aria-pressed="false">原图</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="view-both" aria-pressed="false">对比</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="view-blink" aria-pressed="false">闪烁</button>
      </div>
      <div class="chart-ai-compare" role="group" aria-label="改图前后对比">
        <figure class="chart-ai-compare-item" data-compare-view="original" hidden>
          <figcaption>原图</figcaption>
          <img alt="改图前的原图" src="${assetUrl(basePath, current.imagePath)}">
        </figure>
        <div class="chart-ai-pages" aria-label="全部改图结果"></div>
      </div>
      <div class="chart-ai-blink" data-compare-view="blink" hidden>
        <div class="chart-ai-blink-frame" data-frame="new" role="button" tabindex="0" title="点击暂停或继续闪烁" aria-label="闪烁对比画布，点击暂停或继续">
          <img class="chart-ai-blink-img" alt="改图前的原图" src="${assetUrl(basePath, current.imagePath)}">
          <img class="chart-ai-blink-img chart-ai-blink-top" alt="AI 改图生成的新图" src="${assetUrl(basePath, pages[0]!.imagePath)}">
          <span class="chart-ai-blink-tag" data-role="blink-tag">新图</span>
        </div>
        <div class="chart-ai-page-nav" data-role="blink-nav" role="group" aria-label="闪烁对比分页" hidden></div>
        <p class="chart-ai-hint">每秒交替，点击画面暂停。${pages.length > 1 ? '多页可用页码切换。' : ''}</p>
      </div>
      <div class="ai-review-summary" data-role="review-summary" aria-label="审阅摘要"></div>
      <ul class="chart-ai-changes" aria-label="变更清单"></ul>
      ${result.warnings.length ? '<ul class="chart-ai-warnings" role="alert" aria-label="软告警"></ul>' : ''}
      ${result.skipped.length ? '<ul class="chart-ai-skipped" aria-label="未执行的要求"></ul>' : ''}
      <div class="chart-ai-actions">
        <p class="ask-ai-adopt-note">尚未修改正文</p>
        <button type="button" class="${buttonClasses('primary')}" data-action="accept">采用到正文</button>
        <button type="button" class="${buttonClasses('secondary')}" data-action="continue">继续调整</button>
        <button type="button" class="${buttonClasses('quiet')}" data-action="discard">放弃</button>
      </div>
      <p class="chart-ai-hint">快捷键：<kbd>A</kbd> 采用 · <kbd>X</kbd> 放弃 · <kbd>C</kbd> 继续调整 · <kbd>1</kbd>–<kbd>4</kbd> 切换视图（输入时不触发）</p>
    `
    const pageList = body.querySelector<HTMLElement>('.chart-ai-pages')!
    const original = body.querySelector<HTMLElement>('[data-compare-view="original"]')!
    const blink = body.querySelector<HTMLElement>('[data-compare-view="blink"]')!
    const blinkFrame = blink.querySelector<HTMLElement>('.chart-ai-blink-frame')!
    const blinkTag = blink.querySelector<HTMLElement>('[data-role="blink-tag"]')!
    const blinkTop = blink.querySelector<HTMLImageElement>('.chart-ai-blink-top')!
    const blinkNav = blink.querySelector<HTMLElement>('[data-role="blink-nav"]')!
    let pageNav: HTMLElement | undefined
    let blinkTimer: number | undefined
    let blinkPaused = false
    let blinkShowNew = true
    const renderBlinkFrame = () => {
      blinkFrame.dataset.frame = blinkShowNew ? 'new' : 'original'
      blinkTag.textContent = blinkPaused ? '已暂停' : blinkShowNew ? '新图' : '原图'
    }
    const stopBlink = () => { if (blinkTimer !== undefined) { window.clearInterval(blinkTimer); blinkTimer = undefined } blinkPaused = false }
    const startBlink = () => {
      stopBlink()
      blinkShowNew = true
      // 减动效偏好下不自动闪烁：停在新图并标注已暂停，用户点击可手动切换。
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { blinkPaused = true; renderBlinkFrame(); return }
      renderBlinkFrame()
      blinkTimer = window.setInterval(() => { blinkShowNew = !blinkShowNew; renderBlinkFrame() }, 900)
    }
    const toggleBlinkPause = (event: Event) => {
      // 闪烁画布的点击/按键只用于暂停，不冒泡触发面板的图片放大。
      event.stopPropagation()
      if (blink.hidden) return
      if (blinkPaused) { blinkPaused = false; blinkTimer = window.setInterval(() => { blinkShowNew = !blinkShowNew; renderBlinkFrame() }, 900) }
      else { stopBlink(); blinkPaused = true }
      renderBlinkFrame()
    }
    blinkFrame.addEventListener('click', toggleBlinkPause)
    blinkFrame.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      event.preventDefault()
      toggleBlinkPause(event)
    })
    if (pages.length > 1) {
      pages.forEach((page, index) => {
        const jump = document.createElement('button')
        jump.type = 'button'
        jump.className = 'chart-ai-chip'
        jump.textContent = `第 ${page.pageNumber} 页`
        jump.setAttribute('aria-pressed', String(index === 0))
        jump.addEventListener('click', () => {
          blinkTop.src = assetUrl(basePath, page.imagePath)
          blinkNav.querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === jump)))
        })
        blinkNav.append(jump)
      })
    }
    for (const view of ['original', 'new', 'both', 'blink']) {
      body.querySelector<HTMLButtonElement>(`[data-action="view-${view}"]`)!.addEventListener('click', () => {
        original.hidden = view === 'new' || view === 'blink'
        pageList.hidden = view === 'original' || view === 'blink'
        if (pageNav) pageNav.hidden = pageList.hidden
        blink.hidden = view !== 'blink'
        blinkNav.hidden = view !== 'blink' || pages.length <= 1
        if (view === 'blink') startBlink(); else stopBlink()
        for (const name of ['original', 'new', 'both', 'blink']) {
          body.querySelector(`[data-action="view-${name}"]`)!.setAttribute('aria-pressed', String(view === name))
        }
      })
    }
    const figures: HTMLElement[] = []
    for (const page of pages) {
      const figure = document.createElement('figure')
      figure.className = 'chart-ai-compare-item'
      const caption = document.createElement('figcaption')
      caption.textContent = pages.length > 1 ? `新图 · 第 ${page.pageNumber}/${page.pageCount} 页` : '新图（AI 改图结果）'
      const image = document.createElement('img')
      image.alt = page.altText || `AI 改图生成的新图${pages.length > 1 ? `第${page.pageNumber}页` : ''}`
      image.src = assetUrl(basePath, page.imagePath)
      figure.append(caption, image)
      figures.push(figure)
      pageList.append(figure)
    }
    if (pages.length > 1) {
      const nav = document.createElement('div')
      nav.className = 'chart-ai-page-nav'
      nav.setAttribute('role', 'group')
      nav.setAttribute('aria-label', '结果分页导航')
      pages.forEach((page, index) => {
        const jump = document.createElement('button')
        jump.type = 'button'
        jump.className = 'chart-ai-chip'
        jump.textContent = `第 ${page.pageNumber} 页`
        jump.addEventListener('click', () => figures[index]?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
        nav.append(jump)
      })
      pageNav = nav
      pageList.before(nav)
    }
    const changeList = body.querySelector<HTMLElement>('.chart-ai-changes')!
    for (const change of changes) {
      const item = document.createElement('li')
      item.textContent = change
      changeList.append(item)
    }
    if (dataChange) {
      const item = document.createElement('li')
      item.className = 'chart-ai-change--data'
      item.textContent = dataChange
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
    const summary = body.querySelector<HTMLElement>('[data-role="review-summary"]')!
    const summaryParts: [string, string, string][] = []
    if (dataChange) summaryParts.push(['is-data', '含作图数据变更', '.chart-ai-change--data'])
    else if (result.changes.plotDataUnchanged) summaryParts.push(['is-safe', '作图数据未变', '.chart-ai-changes'])
    summaryParts.push(['', `变更 ${changes.length + (dataChange ? 1 : 0)} 项`, '.chart-ai-changes'])
    if (result.warnings.length) summaryParts.push(['is-warn', `告警 ${result.warnings.length} 条`, '.chart-ai-warnings'])
    if (result.skipped.length) summaryParts.push(['is-skipped', `未执行 ${result.skipped.length} 项`, '.chart-ai-skipped'])
    if (pages.length > 1) summaryParts.push(['', `${pages.length} 页结果`, '.chart-ai-pages'])
    for (const [tone, label, selector] of summaryParts) {
      const item = document.createElement('button')
      item.type = 'button'
      item.className = tone ? `ai-review-summary-item ${tone}` : 'ai-review-summary-item'
      item.textContent = label
      item.title = '定位到对应内容'
      item.addEventListener('click', () => {
        const target = body.querySelector<HTMLElement>(selector)
        if (!target) return
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        target.classList.remove('ai-flash')
        void target.offsetWidth
        target.classList.add('ai-flash')
        window.setTimeout(() => target.classList.remove('ai-flash'), 2000)
      })
      summary.append(item)
    }
    // 变更清单过长时折叠多余项，避免审阅区被清单淹没。
    const changeItems = [...changeList.children] as HTMLElement[]
    if (changeItems.length > 6) {
      changeItems.slice(6).forEach(item => { item.hidden = true })
      const toggle = document.createElement('button')
      toggle.type = 'button'
      toggle.className = 'chart-ai-chip'
      toggle.textContent = `展开全部 ${changeItems.length} 项变更`
      toggle.addEventListener('click', () => {
        const expanding = changeItems[6]!.hidden
        changeItems.slice(6).forEach(item => { item.hidden = !expanding })
        toggle.textContent = expanding ? '收起变更清单' : `展开全部 ${changeItems.length} 项变更`
      })
      changeList.after(toggle)
    }
    // 审阅按钮角标提示快捷键：用 data-key + 伪元素呈现，不改按钮文本（按钮会被整体移入底部 dock，角标随行）。
    for (const [action, key] of [['accept', 'A'], ['continue', 'C'], ['discard', 'X']] as const) {
      const actionButton = body.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
      if (actionButton) actionButton.dataset.key = key
    }
    // 审阅快捷键：监听挂 document，离开审阅阶段后自清理；输入框内不触发。
    const onReviewKey = (event: KeyboardEvent) => {
      if (!body.isConnected || !body.querySelector('[data-action="accept"]')) { document.removeEventListener('keydown', onReviewKey); return }
      if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return
      if ((event.target as HTMLElement | null)?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (body.closest('[hidden]')) return
      const key = event.key.toLowerCase()
      const action = key === 'a' ? 'accept' : key === 'x' ? 'discard' : key === 'c' ? 'continue'
        : ['1', '2', '3', '4'].includes(key) ? `view-${['new', 'original', 'both', 'blink'][Number(key) - 1]}` : undefined
      if (!action) return
      event.preventDefault()
      body.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)?.click()
    }
    document.addEventListener('keydown', onReviewKey)
    body.querySelector<HTMLButtonElement>('[data-action="accept"]')!.addEventListener('click', () => {
      stopBlink()
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
      stopBlink()
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
          <p class="ai-loading-line">正在读取图表信息…</p>
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
          const unavailableIcon = document.createElement('span')
          unavailableIcon.className = 'chart-ai-unavailable-icon'
          unavailableIcon.append(createElement(CircleAlert, { width: 22, height: 22, 'aria-hidden': 'true' }))
          body.querySelector('.chart-ai-unavailable')!.prepend(unavailableIcon)
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
      actionModal?.remove()
      actionModal = null
      modal?.remove()
      modal = null
    },
  }
  return controller
}
