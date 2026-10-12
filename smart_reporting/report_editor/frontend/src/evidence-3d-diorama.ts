import { CARD_WORLD } from './evidence-3d-theme'

type Three = typeof import('./evidence-3d-primitives')
type Point = { x: number; y: number; z: number }

/**
 * 裸眼 3D 展台：把整张关系图装进一个半透明线框盒子（背墙与地板带渐隐细网格），
 * 每张卡片在背墙上投下柔和阴影。盒子的透视收束与卡片—阴影的错位共同给出纵深，
 * 旋转或视差时空间关系一目了然。只读坐标，不参与拾取。
 */
export const DIORAMA = {
  margin: { x: CARD_WORLD.width / 2 + 46, top: 70, bottom: 46, back: 96, front: 64 },
  edge: '#38bdf8', edgeOpacity: 0.32, gridLine: '#2a7fb0', wallOpacity: 0.55, floorOpacity: 0.5,
  shadowOffset: { x: 8, y: -10 }, shadowOpacity: 0.5,
}

function gridCanvas(columns: number, rows: number, size = 512): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) return canvas
  context.strokeStyle = DIORAMA.gridLine
  context.lineWidth = 1.2
  context.globalAlpha = 0.6
  for (let index = 0; index <= columns; index++) {
    const x = index * size / columns
    context.beginPath(); context.moveTo(x, 0); context.lineTo(x, size); context.stroke()
  }
  for (let index = 0; index <= rows; index++) {
    const y = index * size / rows
    context.beginPath(); context.moveTo(0, y); context.lineTo(size, y); context.stroke()
  }
  // 四周渐隐，网格不出现硬边。
  context.globalAlpha = 1
  context.globalCompositeOperation = 'destination-in'
  const fade = context.createRadialGradient(size / 2, size / 2, size * 0.15, size / 2, size / 2, size * 0.72)
  fade.addColorStop(0, 'rgba(0,0,0,1)')
  fade.addColorStop(1, 'rgba(0,0,0,0)')
  context.fillStyle = fade
  context.fillRect(0, 0, size, size)
  return canvas
}

function shadowCanvas(width = 256, height = 96): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return canvas
  context.filter = 'blur(10px)'
  context.fillStyle = 'rgba(0, 0, 0, 0.9)'
  context.fillRect(22, 20, width - 44, height - 40)
  return canvas
}

export function buildDiorama(three: Three, positions: Iterable<[string, Point]>) {
  const points = [...positions].map(([, point]) => point)
  const group = new three.Group()
  group.name = 'evidence-diorama'
  const disposables: Array<{ dispose(): void }> = []
  if (!points.length) return { group, corners: [] as Point[], dispose: () => {} }
  const span = (axis: keyof Point) => [Math.min(...points.map(point => point[axis])), Math.max(...points.map(point => point[axis]))]
  const [x, y, z] = [span('x'), span('y'), span('z')]
  const { margin } = DIORAMA
  const box = {
    left: x[0] - margin.x, right: x[1] + margin.x,
    bottom: y[0] - margin.bottom, top: y[1] + margin.top,
    back: z[0] - margin.back, front: z[1] + margin.front,
  }
  const width = box.right - box.left
  const height = box.top - box.bottom
  const depth = box.front - box.back
  const center = { x: (box.left + box.right) / 2, y: (box.bottom + box.top) / 2, z: (box.back + box.front) / 2 }
  const material = <T extends { dispose(): void }>(value: T) => { disposables.push(value); return value }
  // 线框
  const boxGeometry = material(new three.BoxGeometry(width, height, depth))
  const edges = material(new three.EdgesGeometry(boxGeometry))
  const frame = new three.LineSegments(edges, material(new three.LineBasicMaterial({
    color: DIORAMA.edge, transparent: true, opacity: DIORAMA.edgeOpacity, depthWrite: false })))
  frame.position.set(center.x, center.y, center.z)
  frame.raycast = () => {}
  // 背墙与地板网格
  const surface = (columns: number, rows: number, opacity: number) => {
    const texture = material(new three.CanvasTexture(gridCanvas(columns, rows)))
    texture.colorSpace = three.SRGBColorSpace
    return material(new three.MeshBasicMaterial({ map: texture, transparent: true, opacity, depthWrite: false, side: three.DoubleSide, toneMapped: false }))
  }
  const wall = new three.Mesh(material(new three.PlaneGeometry(width, height)),
    surface(Math.max(4, Math.round(width / 40)), Math.max(4, Math.round(height / 40)), DIORAMA.wallOpacity))
  wall.position.set(center.x, center.y, box.back)
  wall.renderOrder = 0
  wall.raycast = () => {}
  const floor = new three.Mesh(material(new three.PlaneGeometry(width, depth)),
    surface(Math.max(4, Math.round(width / 40)), Math.max(2, Math.round(depth / 40)), DIORAMA.floorOpacity))
  floor.rotation.x = -Math.PI / 2
  floor.position.set(center.x, box.bottom, center.z)
  floor.renderOrder = 0
  floor.raycast = () => {}
  group.add(wall, floor, frame)
  // 卡片投在背墙上的阴影：与卡片之间隔着纵深，转动视角时错位明显。
  const shadowTexture = material(new three.CanvasTexture(shadowCanvas()))
  const shadowMaterial = material(new three.MeshBasicMaterial({ map: shadowTexture, transparent: true, opacity: DIORAMA.shadowOpacity, depthWrite: false, toneMapped: false }))
  const shadowGeometry = material(new three.PlaneGeometry(CARD_WORLD.width * 1.15, CARD_WORLD.height * 1.6))
  for (const point of points) {
    const shadow = new three.Mesh(shadowGeometry, shadowMaterial)
    shadow.position.set(point.x + DIORAMA.shadowOffset.x, point.y + DIORAMA.shadowOffset.y, box.back + 0.5)
    shadow.renderOrder = 0
    shadow.raycast = () => {}
    group.add(shadow)
  }
  const corners: Point[] = []
  for (const cx of [box.left, box.right]) for (const cy of [box.bottom, box.top]) for (const cz of [box.back, box.front]) corners.push({ x: cx, y: cy, z: cz })
  return { group, corners, dispose: () => { for (const item of disposables) item.dispose() } }
}
