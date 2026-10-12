import type { EvidenceObjectKind } from './evidence-state'

/**
 * 3D 关系图视觉主题：深色空间底 + 雾化景深 + 叠加光晕的发光节点（不用后期辉光：
 * 软件渲染与部分显卡不支持其浮点纹理，会整屏空白）。画布底色保持纯色，
 * 便于检查节点与名称未越出画布边缘（smoke 以该底色判定空白）。
 */
export const EVIDENCE_3D_THEME = {
  background: '#071321',
  backgroundRgb: [7, 19, 33] as const,
  /** 指数雾密度：越远的节点与连线越暗，形成纵深。 */
  fogDensity: 0.0016,
  /** 深色底上的节点主色（比 2D 类型色更亮，配合辉光）。 */
  kinds: {
    fact: '#4f9dff', computation: '#a78bfa', dataset: '#2dd4bf', chart: '#fbbf24', subject: '#94a3b8',
  } as Record<EvidenceObjectKind, string>,
  dimmedNode: '#1c3247',
  link: '#3f8fbf',
  linkHighlight: '#67e8f9',
  linkDimmed: '#16293b',
  label: { text: '#bfe0f2', background: 'rgba(9, 27, 43, 0.86)', current: 'rgba(14, 58, 82, 0.92)', border: '#24506b', selected: '#22d3ee' },
  guide: '#2f5d78',
  /** 节点到地面的落地线与投影点：标出节点悬浮高度，增强空间感。 */
  drop: { line: '#1f6f8f', opacity: 0.55, marker: '#22d3ee' },
  grid: { line: '#1b7fa3', ring: '#22d3ee', opacity: 0.9 },
}

/** 节点光晕贴图：径向渐变，叠加混合时中心最亮、边缘透明。 */
export function haloCanvas(color: string, size = 128): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) return canvas
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, `${color}cc`)
  gradient.addColorStop(0.25, `${color}55`)
  gradient.addColorStop(0.6, `${color}14`)
  gradient.addColorStop(1, `${color}00`)
  context.fillStyle = gradient
  context.fillRect(0, 0, size, size)
  return canvas
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
