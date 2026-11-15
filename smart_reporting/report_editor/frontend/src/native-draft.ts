/** 原生草稿始终属于一个不可变文件快照；服务端仍负责操作和文件身份校验。 */
export interface NativeDraftIdentity {
  documentId: string
  revision: number
  sourceSha256: string
  scope: { database: string; companyId: string; userId: string; threadId: string }
}
export type NativeOperation = { kind: string; [key: string]: unknown }
export interface NativeSaveRequest {
  requestId: string
  expectedSha256: string
  operations: NativeOperation[]
  note?: string
  confirmedPreviewDigest?: string
}
export type NativeStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
interface PendingSave { action: 'save' | 'export'; request: NativeSaveRequest }

function identityValue(identity: NativeDraftIdentity) {
  return [identity.scope.database, identity.scope.companyId, identity.scope.userId, identity.scope.threadId,
    identity.documentId, identity.revision, identity.sourceSha256]
}
export function nativeDraftKey(identity: NativeDraftIdentity): string {
  return `native-editor-draft:v1:${JSON.stringify(identityValue(identity))}`
}
function copyOperations(operations: NativeOperation[]): NativeOperation[] {
  if (!Array.isArray(operations) || operations.length > 500) throw new Error('原生编辑操作超限')
  const encoded = JSON.stringify(operations, (_key, value) => {
    if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('原生编辑操作包含无效数字')
    if (value === undefined || typeof value === 'function' || typeof value === 'symbol' || typeof value === 'bigint') throw new Error('原生编辑操作不是有效 JSON')
    return value
  })
  if (new TextEncoder().encode(encoded).length > 12 * 1024 * 1024) throw new Error('原生编辑操作超限')
  const copied = JSON.parse(encoded) as NativeOperation[]
  if (copied.some(value => !value || typeof value !== 'object' || Array.isArray(value) || typeof value.kind !== 'string' || !value.kind)) throw new Error('原生编辑操作无效')
  return copied
}

export class NativeDraft {
  private readonly boundIdentity: NativeDraftIdentity
  private current: NativeOperation[] = []
  private past: NativeOperation[][] = []
  private future: NativeOperation[][] = []
  private pending?: PendingSave
  private inFlight = false
  private ended = false
  persistenceError: string | null = null

  constructor(identity: NativeDraftIdentity, private readonly storage: NativeStorage,
    private readonly requestId: () => string = () => crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('')) {
    this.boundIdentity = structuredClone(identity)
    this.restore()
  }

  get identity() { return structuredClone(this.boundIdentity) }
  get operations() { return structuredClone(this.current) }
  get canUndo() { return !this.inFlight && !this.ended && this.past.length > 0 }
  get canRedo() { return !this.inFlight && !this.ended && this.future.length > 0 }
  get saving() { return this.inFlight }
  get closed() { return this.ended }
  get dirty() { return !this.ended && this.current.length > 0 }

  private editable() {
    if (this.inFlight) throw new Error('正在保存，请等待保存完成')
    if (this.ended) throw new Error('当前修订已保存，请打开新修订继续编辑')
  }
  setOperations(operations: NativeOperation[]) {
    this.editable()
    const next = copyOperations(operations)
    if (JSON.stringify(next) === JSON.stringify(this.current)) return
    this.past.push(this.current)
    this.current = next
    this.future = []
    this.pending = undefined
    this.persist()
  }
  undo() {
    this.editable()
    const previous = this.past.pop()
    if (!previous) return
    this.future.push(this.current)
    this.current = previous
    this.pending = undefined
    this.persist()
  }
  redo() {
    this.editable()
    const next = this.future.pop()
    if (!next) return
    this.past.push(this.current)
    this.current = next
    this.pending = undefined
    this.persist()
  }
  beginSave(options: { note?: string; action?: 'save' | 'export'; confirmedPreviewDigest?: string } = {}): NativeSaveRequest {
    this.editable()
    if (options.note !== undefined && options.note.length > 200) throw new Error('修订备注超限')
    if (options.confirmedPreviewDigest !== undefined && !/^[a-f0-9]{64}$/.test(options.confirmedPreviewDigest)) throw new Error('文字预览确认无效')
    const action = options.action ?? 'save'
    const payload = { expectedSha256: this.identity.sourceSha256, operations: this.operations,
      ...(options.note === undefined ? {} : { note: options.note }),
      ...(options.confirmedPreviewDigest === undefined ? {} : { confirmedPreviewDigest: options.confirmedPreviewDigest }) }
    const previous = this.pending
    if (!previous || previous.action !== action || JSON.stringify({ ...previous.request, requestId: undefined }) !== JSON.stringify(payload)) {
      this.pending = { action, request: { ...payload, requestId: this.requestId() } }
    }
    this.inFlight = true
    this.persist()
    return structuredClone(this.pending!.request)
  }
  saveFailed() {
    this.inFlight = false
    this.persist()
  }
  saveCompleted(result: { revision: number; revisionRegistered: boolean }) {
    this.inFlight = false
    if (!result.revisionRegistered) { this.persist(); return }
    this.ended = true
    try { this.storage.removeItem(nativeDraftKey(this.identity)); this.persistenceError = null }
    catch { this.persistenceError = '无法清理本地草稿' }
  }
  private persist() {
    try {
      if(this.current.some(operation=>operation.kind==='setDocumentProtection')){this.storage.removeItem(nativeDraftKey(this.identity));this.persistenceError=null;return}
      this.storage.setItem(nativeDraftKey(this.identity), JSON.stringify({ version: 1, identity: this.identity, operations: this.current, pending: this.pending }))
      this.persistenceError = null
    } catch { this.persistenceError = '无法保存本地草稿；当前修改仍保留在页面中' }
  }
  private restore() {
    try {
      const raw = this.storage.getItem(nativeDraftKey(this.identity))
      if (!raw) return
      const value = JSON.parse(raw)
      if (value.version !== 1 || JSON.stringify(identityValue(value.identity)) !== JSON.stringify(identityValue(this.identity))) return
      const restored=copyOperations(value.operations)
      if(restored.some(operation=>operation.kind==='setDocumentProtection')){this.storage.removeItem(nativeDraftKey(this.identity));return}
      this.current = restored
      const pending = value.pending as PendingSave | undefined
      if (pending && ['save', 'export'].includes(pending.action) && typeof pending.request.requestId === 'string'
        && pending.request.requestId && pending.request.expectedSha256 === this.identity.sourceSha256
        && (pending.request.note === undefined || typeof pending.request.note === 'string' && pending.request.note.length <= 200)
        && (pending.request.confirmedPreviewDigest === undefined || typeof pending.request.confirmedPreviewDigest === 'string' && /^[a-f0-9]{64}$/.test(pending.request.confirmedPreviewDigest))
        && JSON.stringify(copyOperations(pending.request.operations)) === JSON.stringify(this.current)) {
        this.pending = structuredClone(pending)
      }
    } catch { /* 损坏、过期或不属于本文件的草稿不恢复。 */ }
  }
}
