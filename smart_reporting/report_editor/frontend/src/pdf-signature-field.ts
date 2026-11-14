/**
 * 固定源 Sign ▸ 放入签名字段：renderer/signature-field.ts `signatureDrawingForField` 的移植。
 * 逻辑逐行保持（8% 内边距、等比缩放、居中；手写笔迹 y 轴向下翻到 PDF 坐标），
 * 只把固定源的 DrawingInput 换成原生 addDrawing 操作，并以字段身份（fieldId + 摘要）代替 formFieldName，
 * 由桥接核对后写入固定引擎的 formFieldName 关联。可视签名，不是证书数字签名。
 */
import type { NativeOperation } from './native-draft'

export interface PdfSignatureField {
  fieldId: string; expectedFieldSha256: string; name: string
  signed: boolean; visuallySigned: boolean
  widgets: { pageIndex: number; rect: [number, number, number, number] }[]
  bindable: boolean; reason: string | null
}
export type SignatureData =
  | { kind: 'ink'; width: number; height: number; paths: number[][] }
  | { kind: 'image'; width: number; height: number; image: string }

export function signatureDrawingForField(sig: SignatureData, target: PdfSignatureField, pageId: string, color: [number, number, number]): NativeOperation {
  const widget = target.widgets[0]
  if (!target.bindable || !widget) throw new Error(target.reason || '此签名字段不能放入签名')
  const [x1, y1, x2, y2] = widget.rect
  const fieldW = Math.abs(x2 - x1)
  const fieldH = Math.abs(y2 - y1)
  const inset = Math.min(fieldW, fieldH) * 0.08
  const availW = Math.max(1, fieldW - inset * 2)
  const availH = Math.max(1, fieldH - inset * 2)
  const k = Math.min(availW / Math.max(sig.width, 1), availH / Math.max(sig.height, 1))
  const width = sig.width * k
  const height = sig.height * k
  const left = Math.min(x1, x2) + (fieldW - width) / 2
  const bottom = Math.min(y1, y2) + (fieldH - height) / 2
  const signatureField = { fieldId: target.fieldId, expectedFieldSha256: target.expectedFieldSha256 }
  const round = (value: number) => Math.round(value * 100) / 100
  if (sig.kind === 'image') {
    return { kind: 'addDrawing', pageId, shape: 'image', image: sig.image, rect: [left, bottom, left + width, bottom + height].map(round), color: [...color], width: 2, signatureField }
  }
  const top = bottom + height
  return {
    kind: 'addDrawing', pageId, shape: 'ink', color: [...color], width: 1.6, signatureField,
    paths: sig.paths.map(path => {
      const out: number[] = []
      // walk whole pairs only: a trailing odd or non-finite value would emit NaN
      for (let index = 0; index + 1 < path.length; index += 2) {
        const x = path[index]!
        const y = path[index + 1]!
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue
        out.push(round(left + x * k), round(top - y * k))
      }
      return out
    }),
  }
}

/** PNG 宽高（IHDR），用于键入签名按图片原始比例放入字段。 */
export function pngSize(base64: string): { width: number; height: number } {
  const bytes = Uint8Array.from(atob(base64.slice(0, 44)), char => char.charCodeAt(0))
  const view = new DataView(bytes.buffer)
  if (bytes.length < 24 || view.getUint32(12) !== 0x49484452) throw new Error('签名图像不是有效的 PNG')
  return { width: view.getUint32(16), height: view.getUint32(20) }
}

/** 草稿校验：签名字段身份格式；同一字段在整份草稿中至多放入一次。 */
export function validatePdfSignatureFieldBindings(operations: NativeOperation[]) {
  const seen = new Set<string>()
  for (const operation of operations) {
    if (operation.kind !== 'addDrawing' || operation.signatureField === undefined) continue
    const field = operation.signatureField as Record<string, unknown>
    if (!['ink', 'image'].includes(String(operation.shape)) || !field || typeof field !== 'object' || Object.keys(field).sort().join() !== 'expectedFieldSha256,fieldId'
      || typeof field.fieldId !== 'string' || !/^[a-f0-9]{64}$/.test(field.fieldId) || typeof field.expectedFieldSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(field.expectedFieldSha256)) throw new Error('签名字段参数无效')
    if (seen.has(field.fieldId)) throw new Error('同一签名字段只能放入一次签名')
    seen.add(field.fieldId)
  }
}

/** 上游签名对话框的 strokes/image 数据转为字段放入所需的签名数据。 */
export function signatureDataFromDialog(data: { kind: 'strokes'; paths: number[][]; width: number; height: number } | { kind: 'image'; image: string; width: number; height: number }): SignatureData {
  return data.kind === 'strokes' ? { kind: 'ink', width: data.width, height: data.height, paths: data.paths.map(path => [...path]) } : { kind: 'image', width: data.width, height: data.height, image: data.image }
}

/**
 * 上游签名对话框确认后、进入拖放前的放入位置选择（固定源 openSignatureDialog(target) 的目标选择）。
 * 返回所选 fieldId；'' 表示在页面上拖出位置；undefined 表示取消。没有可放入字段时不弹出，直接走拖放。
 */
export function choosePdfSignatureFieldTarget(owner: Document, fields: { fieldId: string; label: string }[]): Promise<string | undefined> {
  if (fields.length === 0) return Promise.resolve('')
  const dialog = owner.createElement('dialog'); dialog.className = 'pdf-sign-target-dialog'; dialog.setAttribute('aria-label', '签名放入位置')
  const title = owner.createElement('h2'); title.textContent = '放入位置'
  const select = owner.createElement('select'); select.setAttribute('aria-label', '签名放入位置')
  select.append(...fields.map(field => new Option(field.label, field.fieldId)), new Option('在页面上拖出位置', ''))
  const actions = owner.createElement('div'); actions.className = 'pdf-sign-target-actions'
  const ok = owner.createElement('button'); ok.type = 'button'; ok.textContent = '确定'
  const cancel = owner.createElement('button'); cancel.type = 'button'; cancel.textContent = '取消'
  actions.append(cancel, ok); dialog.append(title, select, actions); owner.body.append(dialog)
  return new Promise(resolve => {
    const finish = (value: string | undefined) => { if (dialog.open) dialog.close(); dialog.remove(); resolve(value) }
    ok.addEventListener('click', () => finish(select.value))
    cancel.addEventListener('click', () => finish(undefined))
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish(undefined) })
    dialog.showModal(); select.focus()
  })
}
