/**
 * 固定源 Design ▸ Watermark（ribbon-design-tab.tsx 预设菜单 + WatermarkDialog 文字页 + “删除水印”）：
 * 原生草稿为一条文档级 setWatermark，按全部页眉部件摘要绑定来源；与来源相同即撤回该修改。
 * 图片水印本轮不接入（对话框只提供“无水印 / 文字”）。
 */
import type { NativeOperation } from './native-draft'

export interface DocxWatermarkModel { text: string | null; style: Omit<DocxWatermarkSpec, 'text' | 'sizePt' | 'boxPt'> | null; picture: boolean; mixed: boolean; editable: boolean; readOnlyReason: string | null; expectedHeadersSha256: string }
export interface DocxWatermarkSpec { text: string; fontFamily?: string; colorHex?: string; opacity?: number; diagonal?: boolean; bold?: boolean; italic?: boolean; sizePt?: number; boxPt?: { widthPt: number; heightPt: number } }

/** 固定源 WATERMARK_KEYS（中文：机密/严禁复制/草稿/样本）+ 非英文界面追加的 CONFIDENTIAL / DRAFT。 */
export const DOCX_WATERMARK_PRESETS = ['机密', '严禁复制', '草稿', '样本', 'CONFIDENTIAL', 'DRAFT']
/** 固定源 WatermarkDialog 的字号档位；“自动”不写 sizePt/boxPt。 */
export const DOCX_WATERMARK_SIZES = [36, 40, 44, 48, 54, 60, 66, 72, 80, 90, 96, 105, 120, 144]
export const DOCX_WATERMARK_DEFAULT_COLOR = 'C0C0C0'
export const DOCX_WATERMARK_DEFAULT_FONT = 'Calibri'
/** 原生对话框的字体候选（固定源读取系统字体列表；网页编辑器无此能力，提供常用中西文字体）。 */
export const DOCX_WATERMARK_FONTS = ['Calibri', '等线', '宋体', '黑体', '楷体', '微软雅黑', 'Arial', 'Times New Roman']

const HEX = /^[0-9A-F]{6}$/
const SHA = /^[a-f0-9]{64}$/
const KEYS = ['bold', 'boxPt', 'colorHex', 'diagonal', 'fontFamily', 'italic', 'opacity', 'sizePt', 'text']

export function docxWatermarkModel(value: unknown): DocxWatermarkModel | null {
  if (!value || typeof value !== 'object') return null
  const model = value as Record<string, unknown>
  if (typeof model.editable !== 'boolean' || typeof model.picture !== 'boolean' || typeof model.mixed !== 'boolean' || typeof model.expectedHeadersSha256 !== 'string' || !SHA.test(model.expectedHeadersSha256)
    || (model.text !== null && typeof model.text !== 'string')) return null
  const style = model.style && typeof model.style === 'object' && model.text && validDocxWatermarkSpec({ ...model.style, text: model.text }) && !('sizePt' in model.style) ? model.style as DocxWatermarkModel['style'] : null
  return { text: model.text as string | null, style, picture: model.picture, mixed: model.mixed, editable: model.editable, readOnlyReason: typeof model.readOnlyReason === 'string' ? model.readOnlyReason : null, expectedHeadersSha256: model.expectedHeadersSha256 }
}

/** 与桥接一致的文字水印取值范围（固定源对话框可产生的值）。 */
export function validDocxWatermarkSpec(value: unknown): value is DocxWatermarkSpec {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const spec = value as Record<string, unknown>
  const box = spec.boxPt as Record<string, unknown> | undefined
  return !Object.keys(spec).some(key => !KEYS.includes(key))
    && typeof spec.text === 'string' && !!spec.text.trim() && spec.text === spec.text.trim() && spec.text.length <= 255 && !/[\u0000-\u001f\u007f]/.test(spec.text)
    && (spec.fontFamily === undefined || (typeof spec.fontFamily === 'string' && !!spec.fontFamily.trim() && spec.fontFamily.length <= 100 && !/[\u0000-\u001f"<>&]/.test(spec.fontFamily)))
    && (spec.colorHex === undefined || (typeof spec.colorHex === 'string' && HEX.test(spec.colorHex)))
    && (spec.opacity === undefined || (typeof spec.opacity === 'number' && spec.opacity >= 0 && spec.opacity <= 1 && Math.abs(Math.round(spec.opacity * 100) - spec.opacity * 100) <= 1e-9))
    && [spec.diagonal, spec.bold, spec.italic].every(item => item === undefined || typeof item === 'boolean')
    && (spec.sizePt === undefined) === (spec.boxPt === undefined)
    && (spec.sizePt === undefined || DOCX_WATERMARK_SIZES.includes(spec.sizePt as number))
    && (box === undefined || (!!box && typeof box === 'object' && Object.keys(box).sort().join() === 'heightPt,widthPt'
      && [box.widthPt, box.heightPt].every(item => typeof item === 'number' && Number.isFinite(item) && item > 0 && item <= 2000)))
}

/** 草稿中的水印修改（恢复与提交前都按来源校验；不一致即抛错，原草稿保留）。 */
export function docxWatermarkOperations(operations: NativeOperation[], model: DocxWatermarkModel | null): NativeOperation[] {
  const found = operations.filter(operation => operation.kind === 'setWatermark')
  if (!found.length) return []
  if (found.length > 1 || !model) throw new Error('水印草稿无效或来源未提供水印能力；原草稿已保留')
  const operation = found[0]!
  if (Object.keys(operation).sort().join() !== 'expectedHeadersSha256,kind,watermark' || operation.expectedHeadersSha256 !== model.expectedHeadersSha256
    || (operation.watermark !== null && !validDocxWatermarkSpec(operation.watermark)) || (operation.watermark === null && model.text === null && !model.picture)) throw new Error('水印草稿与当前来源不一致；原草稿已保留')
  if (!model.editable) throw new Error(model.readOnlyReason ?? '此文档的水印不能修改')
  return [JSON.parse(JSON.stringify(operation))]
}

/** 生效中的水印：草稿优先（null = 草稿删除），否则来源文字水印；undefined 表示来源为图片水印。 */
export function effectiveDocxWatermark(operations: NativeOperation[], model: DocxWatermarkModel | null): DocxWatermarkSpec | null {
  const pending = operations.find(operation => operation.kind === 'setWatermark')
  if (pending) return pending.watermark as DocxWatermarkSpec | null
  return sourceDocxWatermark(model)
}

/** 来源文字水印（文字 + 回读样式，固定源 textFromDocImage）。 */
export function sourceDocxWatermark(model: DocxWatermarkModel | null): DocxWatermarkSpec | null {
  return model?.text ? { text: model.text, ...(model.style ?? {}) } : null
}
const canonical = (spec: DocxWatermarkSpec | null) => spec === null ? null : JSON.stringify(Object.fromEntries(Object.entries({ diagonal: true, opacity: 0.5, ...spec }).sort(([a], [b]) => a.localeCompare(b))))

/** 新水印后的完整非正文草稿：替换已有的 setWatermark；删除且来源本无水印、或预设与来源相同则只撤回。 */
export function withDocxWatermark(operations: NativeOperation[], model: DocxWatermarkModel | null, spec: DocxWatermarkSpec | null): NativeOperation[] {
  if (!model) throw new Error('当前来源未提供水印能力')
  if (!model.editable) throw new Error(model.readOnlyReason ?? '此文档的水印不能修改')
  if (spec !== null && !validDocxWatermarkSpec(spec)) throw new Error('水印文字须为 1–255 个字符，且字号、颜色、透明度在对话框范围内')
  const others = operations.filter(operation => operation.kind !== 'setWatermark')
  const sameAsSource = spec === null ? model.text === null && !model.picture : !model.mixed && !model.picture && canonical(spec) === canonical(sourceDocxWatermark(model))
  return sameAsSource ? others : [...others, { kind: 'setWatermark', expectedHeadersSha256: model.expectedHeadersSha256, watermark: spec === null ? null : JSON.parse(JSON.stringify(spec)) }]
}

let inkContext: CanvasRenderingContext2D | null | undefined
/** 固定源 inkBoxPt：指定字号时 Word 的形状框为该字号下字形墨迹框（无 canvas 时按经验比例估算）。 */
export function docxWatermarkInkBoxPt(spec: DocxWatermarkSpec, sizePt: number): { widthPt: number; heightPt: number } {
  if (inkContext === undefined) { try { inkContext = document.createElement('canvas').getContext('2d') } catch { inkContext = null } }
  const fallback = { widthPt: Math.round(sizePt * 0.6 * spec.text.length * 100) / 100, heightPt: Math.round(sizePt * 0.72 * 100) / 100 }
  if (!inkContext) return fallback
  inkContext.font = `${spec.italic ? 'italic' : 'normal'} ${spec.bold ? 'bold' : 'normal'} ${sizePt}px "${spec.fontFamily ?? DOCX_WATERMARK_DEFAULT_FONT}", sans-serif`
  const metrics = inkContext.measureText(spec.text)
  const width = (metrics.actualBoundingBoxLeft ?? 0) + (metrics.actualBoundingBoxRight ?? metrics.width)
  const height = (metrics.actualBoundingBoxAscent ?? 0) + (metrics.actualBoundingBoxDescent ?? 0)
  if (!(width > 0) || !(height > 0)) return fallback
  const round = (value: number) => Math.min(2000, Math.round(value * 100) / 100)
  return { widthPt: round(width), heightPt: round(height) }
}
