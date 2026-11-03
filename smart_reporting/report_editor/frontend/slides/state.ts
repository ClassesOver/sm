export interface SlideElement {
  id: string
  kind: 'text' | 'image' | 'shape'
  x: number
  y: number
  width: number
  height: number
  rotation: number
  text?: string
  fontSize?: number
  fontFamily?: string
  color?: string
  bold?: boolean
  fill?: string
  imageDataUrl?: string
  shape?: string
  lineSpacing?: number
  editable?: boolean
}
export interface Slide {
  index: number
  title: string
  background: string
  elements: SlideElement[]
}
export interface Validation {
  ok: boolean
  issues: unknown[]
}
export interface PublicationGate {
  formalReleaseAllowed: boolean
  issues: unknown[]
}
export interface SlidesDocument {
  reportId: string
  revision: number
  sha256: string
  csrfToken: string
  width: number
  height: number
  fontScale?: number
  slides: Slide[]
  validation?: Validation
  publicationGate?: PublicationGate
}
export type ElementChanges = Partial<Omit<SlideElement, 'id' | 'kind' | 'editable' | 'imageDataUrl' | 'shape'>>
export type NewText = Pick<SlideElement, 'text' | 'x' | 'y' | 'width' | 'height'> & ElementChanges
export type Operation =
  | ({ op: 'update'; slide: number; id: string } & ElementChanges)
  | ({ op: 'addText'; slide: number } & NewText)
  | { op: 'delete'; slide: number; id: string }
  | { op: 'background'; slide: number; color: string }
export interface DraftBody {
  expectedSha256: string
  operations: Operation[]
}

export class SlidesState {
  document: SlidesDocument
  operations: Operation[] = []
  busy = false
  private additions = new Map<string, Operation & { op: 'addText' }>()
  private nextId = 0

  constructor(document: SlidesDocument) {
    this.document = structuredClone(document)
  }

  get dirty(): boolean { return this.operations.length > 0 }

  element(slide: number, id: string): SlideElement | undefined {
    return this.document.slides.find((item) => item.index === slide)?.elements.find((item) => item.id === id)
  }

  update(slide: number, id: string, changes: ElementChanges): void {
    const element = this.element(slide, id)
    if (this.busy || !element || element.editable === false) return
    Object.assign(element, changes)
    const addition = this.additions.get(id)
    if (addition) {
      Object.assign(addition, changes)
      return
    }
    const existing = this.operations.find((item) => item.op === 'update' && item.slide === slide && item.id === id)
    if (existing) Object.assign(existing, changes)
    else this.operations.push({ op: 'update', slide, id, ...changes })
  }

  addText(slide: number, text: NewText): string {
    const page = this.document.slides.find((item) => item.index === slide)
    if (this.busy || !page) return ''
    const id = `local-text-${++this.nextId}`
    const operation: Operation & { op: 'addText' } = { op: 'addText', slide, ...text }
    this.operations.push(operation)
    this.additions.set(id, operation)
    page.elements.push({ id, kind: 'text', rotation: 0, ...text })
    return id
  }

  delete(slide: number, id: string): void {
    const element = this.element(slide, id)
    if (this.busy || !element || element.editable === false) return
    const page = this.document.slides.find((item) => item.index === slide)!
    page.elements = page.elements.filter((item) => item.id !== id)
    const addition = this.additions.get(id)
    this.operations = this.operations.filter((item) => item !== addition && !('id' in item && item.id === id && item.slide === slide))
    if (addition) this.additions.delete(id)
    else this.operations.push({ op: 'delete', slide, id })
  }

  background(slide: number, color: string): void {
    const page = this.document.slides.find((item) => item.index === slide)
    if (this.busy || !page) return
    page.background = color
    const existing = this.operations.find((item) => item.op === 'background' && item.slide === slide)
    if (existing && existing.op === 'background') existing.color = color
    else this.operations.push({ op: 'background', slide, color })
  }

  async save(send: (body: DraftBody) => Promise<SlidesDocument>): Promise<void> {
    if (this.busy || !this.dirty) return
    this.busy = true
    try {
      const saved = await send({ expectedSha256: this.document.sha256, operations: structuredClone(this.operations) })
      this.document = structuredClone(saved)
      this.operations = []
      this.additions.clear()
    } finally {
      this.busy = false
    }
  }
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code = '') { super(message) }
}

export async function requestJson<T>(url: string, options: RequestInit = {}, send: typeof fetch = fetch): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await send(url, { ...options, headers, credentials: 'same-origin' })
  const data = await response.json().catch(() => undefined)
  if (!response.ok) {
    const detail = data?.detail
    throw new ApiError(typeof detail?.message === 'string' ? detail.message : `请求失败（HTTP ${response.status}）`, response.status, typeof detail?.code === 'string' ? detail.code : '')
  }
  if (!data) throw new ApiError('服务端未返回有效数据，请重试。', response.status)
  return data as T
}

export function safeImageSource(value?: string): string | undefined {
  return value && /^data:image\/(?:png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$/i.test(value) ? value : undefined
}
