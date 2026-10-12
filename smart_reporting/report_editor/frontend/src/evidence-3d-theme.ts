import type { EvidenceObjectKind } from './evidence-state'

/**
 * 3D 关系图视觉主题：深色空间底 + 雾化纵深 + 节点信息卡（不用后期辉光：
 * 软件渲染与部分显卡不支持其浮点纹理，会整屏空白）。画布底色保持纯色，
 * 便于检查节点与名称未越出画布边缘（smoke 以该底色判定空白）。
 */
export const EVIDENCE_3D_THEME = {
  background: '#071321',
  backgroundRgb: [7, 19, 33] as const,
  /** 指数雾密度：越远的节点与连线越暗，形成纵深。 */
  fogDensity: 0.0009,
  /** 深色底上的类型主色（比 2D 类型色更亮），用于卡片色条、图标与图例。 */
  kinds: {
    fact: '#4f9dff', computation: '#a78bfa', dataset: '#2dd4bf', chart: '#fbbf24', subject: '#94a3b8',
  } as Record<EvidenceObjectKind, string>,
  dimmedNode: '#1c3247',
  link: '#3f8fbf',
  linkHighlight: '#67e8f9',
  linkDimmed: '#16293b',
  /** 阶段标题。 */
  stage: { edge: '#2c8fb8', title: '#e2f4ff', titleBackground: 'rgba(12, 44, 66, 0.92)' },
  grid: { line: '#1b7fa3', ring: '#22d3ee', opacity: 0.55 },
}

/**
 * 全息地面贴图：网格线 + 同心雷达环，整体按径向渐隐到透明。边缘完全透明，
 * 地面铺得再大也不会在画布边缘留下网格。
 */
export function floorCanvas(size = 1024): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) return canvas
  const { line, ring } = EVIDENCE_3D_THEME.grid
  const center = size / 2
  context.strokeStyle = line
  context.globalAlpha = 0.55
  context.lineWidth = 1.5
  const cells = 24
  for (let index = 0; index <= cells; index++) {
    const offset = index * size / cells
    context.beginPath(); context.moveTo(offset, 0); context.lineTo(offset, size); context.stroke()
    context.beginPath(); context.moveTo(0, offset); context.lineTo(size, offset); context.stroke()
  }
  context.strokeStyle = ring
  context.globalAlpha = 0.7
  context.lineWidth = 2.5
  for (const radius of [0.14, 0.28, 0.42]) {
    context.beginPath(); context.arc(center, center, radius * size, 0, Math.PI * 2); context.stroke()
  }
  // 径向遮罩：中心不透明，向外渐隐到完全透明。
  context.globalAlpha = 1
  context.globalCompositeOperation = 'destination-in'
  const mask = context.createRadialGradient(center, center, 0, center, center, center)
  mask.addColorStop(0, 'rgba(0,0,0,1)')
  mask.addColorStop(0.5, 'rgba(0,0,0,0.8)')
  mask.addColorStop(0.85, 'rgba(0,0,0,0)')
  context.fillStyle = mask
  context.fillRect(0, 0, size, size)
  return canvas
}

export type EvidenceCardState = 'normal' | 'current' | 'selected' | 'dimmed'
export const CARD_PIXELS = { width: 560, height: 150, padding: 12 }
/** 卡片在世界坐标中的尺寸（与贴图宽高比一致）。 */
export const CARD_WORLD = { width: 150, height: 150 * CARD_PIXELS.height / CARD_PIXELS.width }

function roundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  context.beginPath()
  context.moveTo(x + radius, y)
  context.arcTo(x + width, y, x + width, y + height, radius)
  context.arcTo(x + width, y + height, x, y + height, radius)
  context.arcTo(x, y + height, x, y, radius)
  context.arcTo(x, y, x + width, y, radius)
  context.closePath()
}

/** 截断到画布宽度内，末尾加省略号。 */
function fitText(context: CanvasRenderingContext2D, text: string, width: number): string {
  if (context.measureText(text).width <= width) return text
  let end = text.length
  while (end > 1 && context.measureText(`${text.slice(0, end)}…`).width > width) end--
  return `${text.slice(0, end)}…`
}

/**
 * 节点信息卡：类型色条 + 类型图标 + 业务名称 + 类型与状态。卡片本身带柔和投影，
 * 当前页亮青描边发光，预览项白色描边，无关项整体变暗。
 */
export function drawEvidenceCard(canvas: HTMLCanvasElement, card: { kind: EvidenceObjectKind; name: string; detail: string; state: EvidenceCardState; icon?: CanvasImageSource | null }): void {
  const { width, height, padding } = CARD_PIXELS
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return
  const accent = EVIDENCE_3D_THEME.kinds[card.kind]
  const x = padding
  const y = padding
  const w = width - padding * 2
  const h = height - padding * 2
  context.clearRect(0, 0, width, height)
  context.globalAlpha = card.state === 'dimmed' ? 0.38 : 1
  // 投影与发光
  context.save()
  context.shadowColor = card.state === 'current' ? 'rgba(34, 211, 238, 0.75)' : 'rgba(0, 0, 0, 0.55)'
  context.shadowBlur = card.state === 'current' ? 14 : 10
  context.shadowOffsetY = card.state === 'current' ? 0 : 4
  roundedRect(context, x, y, w, h, 14)
  const fill = context.createLinearGradient(0, y, 0, y + h)
  fill.addColorStop(0, '#16324c')
  fill.addColorStop(1, '#0d2136')
  context.fillStyle = fill
  context.fill()
  context.restore()
  // 描边
  roundedRect(context, x, y, w, h, 14)
  context.lineWidth = card.state === 'current' ? 4 : card.state === 'selected' ? 3.5 : 2
  context.strokeStyle = card.state === 'current' ? '#22d3ee' : card.state === 'selected' ? '#f1f5f9' : 'rgba(120, 170, 205, 0.45)'
  context.stroke()
  // 类型色条
  context.save()
  roundedRect(context, x, y, w, h, 14)
  context.clip()
  context.fillStyle = accent
  context.fillRect(x, y, 10, h)
  context.restore()
  // 图标
  const iconSize = 50
  const iconX = x + 26
  const iconY = y + (h - iconSize) / 2
  roundedRect(context, iconX - 6, iconY - 6, iconSize + 12, iconSize + 12, 12)
  context.fillStyle = `${accent}26`
  context.fill()
  if (card.icon) context.drawImage(card.icon, iconX, iconY, iconSize, iconSize)
  // 文字
  const textX = iconX + iconSize + 20
  const textWidth = x + w - textX - 14
  context.textBaseline = 'alphabetic'
  context.fillStyle = '#eef7ff'
  context.font = '600 46px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif'
  context.fillText(fitText(context, card.name, textWidth), textX, y + h / 2 + 4)
  context.fillStyle = card.state === 'current' ? '#7ee8fa' : '#93b6cf'
  context.font = '500 27px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif'
  context.fillText(fitText(context, card.detail, textWidth), textX, y + h / 2 + 40)
}
