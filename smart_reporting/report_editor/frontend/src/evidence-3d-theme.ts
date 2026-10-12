import type { EvidenceObjectKind } from './evidence-state'

/**
 * 3D 关系图视觉主题：深色空间底 + 雾化纵深 + 节点信息卡（不用后期辉光：
 * 软件渲染与部分显卡不支持其浮点纹理，会整屏空白）。画布底色保持纯色，
 * 便于检查节点与名称未越出画布边缘（smoke 以该底色判定空白）。
 */
export const EVIDENCE_3D_THEME = {
  background: '#071321',
  backgroundRgb: [7, 19, 33] as const,
  transparentBackground: 'rgba(7, 19, 33, 0)',
  /** 指数雾密度：越远的节点与连线越暗，形成纵深。 */
  fogDensity: 0.0009,
  /** 深色底上的类型主色（比 2D 类型色更亮），用于卡片色条、图标与图例。 */
  kinds: {
    fact: '#4f9dff', computation: '#a78bfa', dataset: '#2dd4bf', chart: '#fbbf24', subject: '#94a3b8',
  } as Record<EvidenceObjectKind, string>,
  dimmedNode: '#1c3247',
  /** 关系流线：管体半径与三种状态的不透明度。 */
  flow: { radius: 0.55, normal: 0.55, highlight: 1, dimmed: 0.08 },
  /** 视差最大偏转角（弧度）：水平约 6°、竖直约 4°。 */
  parallax: { yaw: 0.1, pitch: 0.07 },
  /** 当前页与预览卡片向镜头凸出的距离（出屏感）。 */
  popOut: { current: 34, selected: 14 },
  /** 阶段标题与泳道。 */
  stage: { title: '#e2f4ff', outline: '#071321' },
}

export type EvidenceCardState = 'normal' | 'current' | 'selected' | 'dimmed'
export const CARD_PIXELS = { width: 560, height: 150, padding: 12 }
export const CARD_RESOLUTION = 2
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
  // 贴图按两倍分辨率绘制，缩小显示时文字更清晰。
  canvas.width = width * CARD_RESOLUTION
  canvas.height = height * CARD_RESOLUTION
  const context = canvas.getContext('2d')
  if (!context) return
  context.setTransform(CARD_RESOLUTION, 0, 0, CARD_RESOLUTION, 0, 0)
  const accent = EVIDENCE_3D_THEME.kinds[card.kind]
  const x = padding
  const y = padding
  const w = width - padding * 2
  const h = height - padding * 2
  context.clearRect(0, 0, width, height)
  context.globalAlpha = card.state === 'dimmed' ? 0.34 : 1
  const radius = 18
  const highlighted = card.state === 'current' || card.state === 'selected'
  // 柔和投影；当前页用类型色发光。
  context.save()
  context.shadowColor = card.state === 'current' ? `${accent}cc` : 'rgba(0, 0, 0, 0.6)'
  context.shadowBlur = card.state === 'current' ? 18 : 12
  context.shadowOffsetY = card.state === 'current' ? 0 : 5
  roundedRect(context, x, y, w, h, radius)
  context.fillStyle = '#0d2236'
  context.fill()
  context.restore()
  // 玻璃质感：自上而下的冷色渐变，叠一层类型色的斜向晕染。
  context.save()
  roundedRect(context, x, y, w, h, radius)
  context.clip()
  const glass = context.createLinearGradient(0, y, 0, y + h)
  glass.addColorStop(0, highlighted ? '#1d4466' : '#183552')
  glass.addColorStop(1, '#0c1e31')
  context.fillStyle = glass
  context.fillRect(x, y, w, h)
  const tint = context.createLinearGradient(x, y, x + w * 0.6, y + h)
  tint.addColorStop(0, `${accent}33`)
  tint.addColorStop(1, `${accent}00`)
  context.fillStyle = tint
  context.fillRect(x, y, w, h)
  // 顶部高光
  const shine = context.createLinearGradient(0, y, 0, y + h * 0.45)
  shine.addColorStop(0, 'rgba(255, 255, 255, 0.10)')
  shine.addColorStop(1, 'rgba(255, 255, 255, 0)')
  context.fillStyle = shine
  context.fillRect(x, y, w, h * 0.45)
  // 左侧类型色条（带辉光）
  context.shadowColor = accent
  context.shadowBlur = 10
  context.fillStyle = accent
  context.fillRect(x, y, 7, h)
  context.restore()
  // 描边：当前页为类型色、预览为浅色，其余为极细的冷色描边。
  roundedRect(context, x + 0.75, y + 0.75, w - 1.5, h - 1.5, radius)
  context.lineWidth = card.state === 'current' ? 3.5 : card.state === 'selected' ? 3 : 1.5
  context.strokeStyle = card.state === 'current' ? accent : card.state === 'selected' ? '#e2f1fb' : 'rgba(150, 200, 232, 0.28)'
  context.stroke()
  // 图标底座
  const iconSize = 46
  const iconX = x + 28
  const iconY = y + (h - iconSize) / 2
  context.beginPath()
  context.arc(iconX + iconSize / 2, iconY + iconSize / 2, iconSize / 2 + 9, 0, Math.PI * 2)
  context.fillStyle = `${accent}22`
  context.fill()
  context.lineWidth = 1.5
  context.strokeStyle = `${accent}66`
  context.stroke()
  if (card.icon) context.drawImage(card.icon, iconX, iconY, iconSize, iconSize)
  // 文字：名称为主，类型与状态以类型色小字标注。
  const textX = iconX + iconSize + 24
  const textWidth = x + w - textX - 16
  context.textBaseline = 'alphabetic'
  context.fillStyle = '#f2f8ff'
  context.font = '600 44px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif'
  context.fillText(fitText(context, card.name, textWidth), textX, y + h / 2 + 2)
  context.fillStyle = card.state === 'current' ? accent : '#8fb4cd'
  context.font = '500 26px "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif'
  context.fillText(fitText(context, card.detail, textWidth), textX, y + h / 2 + 38)
}

/** 阶段泳道贴图：竖向柔光带，四周渐隐到透明，避免硬边玻璃板的生硬感。 */
export function laneCanvas(width = 256, height = 512): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return canvas
  const horizontal = context.createLinearGradient(0, 0, width, 0)
  horizontal.addColorStop(0, 'rgba(56, 140, 200, 0)')
  horizontal.addColorStop(0.5, 'rgba(56, 140, 200, 0.22)')
  horizontal.addColorStop(1, 'rgba(56, 140, 200, 0)')
  context.fillStyle = horizontal
  context.fillRect(0, 0, width, height)
  context.globalCompositeOperation = 'destination-in'
  const vertical = context.createLinearGradient(0, 0, 0, height)
  vertical.addColorStop(0, 'rgba(0, 0, 0, 0)')
  vertical.addColorStop(0.18, 'rgba(0, 0, 0, 1)')
  vertical.addColorStop(0.82, 'rgba(0, 0, 0, 1)')
  vertical.addColorStop(1, 'rgba(0, 0, 0, 0)')
  context.fillStyle = vertical
  context.fillRect(0, 0, width, height)
  return canvas
}
