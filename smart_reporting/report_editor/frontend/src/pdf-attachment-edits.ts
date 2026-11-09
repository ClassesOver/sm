import type { NativeOperation } from './native-draft'
export interface SavedPdfAttachment { key: string; name: string; description: string; size: number; contentSha256: string; attachmentId: string; expectedAttachmentSha256: string }
export interface PdfAttachmentModel { attachments?: SavedPdfAttachment[]; attachmentsEditable?: boolean; attachmentsReason?: string | null; sourceSha256: string }
export const ATTACHMENT_FILE_MAX = 2 * 1024 * 1024
const sha = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
export const isAttachmentEdit = (op: NativeOperation) => ['addAttachment', 'removeAttachment'].includes(op.kind)
export function validAttachmentName(name: string) { return name.length > 0 && name.length <= 256 && !!name.trim() && !/[\x00-\x1f\x7f/\\]/.test(name) && new TextDecoder().decode(new TextEncoder().encode(name)) === name }
export function validateAttachmentEdits(operations: NativeOperation[]) {
  let total = 0
  const names = new Set<string>(), removed = new Set<string>()
  const edits = operations.filter(isAttachmentEdit)
  if (edits.length && operations.some(op => op.kind === 'replaceText')) throw Error('附件修改与原位改字请分别保存重开')
  for (const op of edits) {
    const allowed = op.kind === 'addAttachment' ? ['kind', 'sourceSha256', 'name', 'bytesBase64', 'description'] : ['kind', 'sourceSha256', 'attachmentId', 'expectedAttachmentSha256']
    if (Object.keys(op).some(key => !allowed.includes(key)) || (op.sourceSha256 !== undefined && !sha(op.sourceSha256))) throw Error('附件操作格式无效，原草稿已保留')
    if (op.kind === 'addAttachment') {
      if (typeof op.name !== 'string' || !validAttachmentName(op.name) || names.has(op.name) || (op.description !== undefined && (typeof op.description !== 'string' || op.description.length > 4000))) throw Error('附件名称无效或重复')
      const value = op.bytesBase64
      if (typeof value !== 'string' || value.length > 4 * Math.ceil(ATTACHMENT_FILE_MAX / 3) || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) throw Error('附件编码无效或单文件超过 2 MiB')
      const decoded = atob(value)
      if (decoded.length > ATTACHMENT_FILE_MAX || btoa(decoded) !== value) throw Error('附件编码无效或单文件超过 2 MiB')
      total += decoded.length; names.add(op.name)
    } else {
      if (!sha(op.attachmentId) || !sha(op.expectedAttachmentSha256) || removed.has(String(op.attachmentId))) throw Error('附件删除身份无效或重复')
      removed.add(String(op.attachmentId))
    }
  }
  if (total > 6 * 1024 * 1024) throw Error('本次新增附件总量超过 6 MiB')
}
export function attachmentEditState(model: PdfAttachmentModel, operations: NativeOperation[]) {
  validateAttachmentEdits(operations)
  const edits = operations.filter(isAttachmentEdit), removed = new Set<string>()
  if (edits.length && model.attachmentsEditable !== true) throw Error(model.attachmentsReason || '当前来源附件仅可查看和下载')
  for (const op of edits) {
    if (op.sourceSha256 !== undefined && op.sourceSha256 !== model.sourceSha256) throw Error('附件来源已变化，原草稿已保留')
    if (op.kind !== 'removeAttachment') continue
    const row = model.attachments?.find(item => item.attachmentId === op.attachmentId)
    if (!row || row.expectedAttachmentSha256 !== op.expectedAttachmentSha256) throw Error('附件身份已变化，原草稿已保留')
    removed.add(row.key)
  }
  const added = edits.filter(op => op.kind === 'addAttachment')
  if (added.some(op => model.attachments?.some(row => row.key === op.name && !removed.has(row.key)))) throw Error('附件名称已存在；请先移除原附件或重命名文件')
  if ((model.attachments?.length ?? 0) - removed.size + added.length > 200) throw Error('附件数量超过 200 个，请先保存或移除部分附件')
  return { removed, added }
}
export async function attachmentFileOperation(file: File): Promise<NativeOperation> {
  if (file.size > ATTACHMENT_FILE_MAX || !validAttachmentName(file.name)) throw Error('附件名称无效或单文件超过 2 MiB')
  const bytes = new Uint8Array(await file.arrayBuffer())
  let raw = ''
  for (let i = 0; i < bytes.length; i += 8192) raw += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return {kind:'addAttachment',name:file.name,bytesBase64:btoa(raw)}
}
