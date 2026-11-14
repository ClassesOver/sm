import type { RenderSlide } from '@genoffice/pptx-render'
import type { MasterRichParagraph } from './slides-master-rich-text'

export type MasterTextEdit = { partPath: string; spid: number; text?: string; paragraphs?: MasterRichParagraph[] }
export type MasterTextPart = { partPath: string; kind: 'master' | 'layout'; name: string; structureEditable?: boolean; elements: { spid: number; name: string; text: string; paragraphs?: MasterRichParagraph[]; editable: boolean; reason: string | null; fillEditable?: boolean; fillValue?: string | null; fillReason?: string | null; strokeEditable?: boolean; strokeValue?: string | null; transformEditable?: boolean; transformValue?: { x: number; y: number; width: number; height: number; rotationDeg: number } | null }[] }
export type MasterTextRenderPart = { partPath: string; slide: RenderSlide }

export function validateMasterTextDraft(input: unknown, parts: readonly MasterTextPart[]): MasterTextEdit[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 200) throw Error('母版文字草稿无效，原草稿已保留')
  const seen = new Set<string>(); let total = 0
  for (const item of input) {
    const key = `${item?.partPath}:${item?.spid}`
    const keys = item && Object.keys(item).sort().join()
    if (!item || !['paragraphs,partPath,spid', 'partPath,spid,text'].includes(keys) || !Number.isInteger(item.spid) || item.spid <= 0
      || (keys === 'partPath,spid,text' && (typeof item.text !== 'string' || item.text.length > 20000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/u.test(item.text)))
      || (keys === 'paragraphs,partPath,spid' && !validParagraphs(item.paragraphs))
      || !parts.some(part => part.partPath === item.partPath && part.elements.some(el => el.spid === item.spid && el.editable)) || seen.has(key)) throw Error('母版文字身份或内容无效，原草稿已保留')
    const validItem = item as MasterTextEdit
    seen.add(key); total += validItem.text?.length ?? validItem.paragraphs!.reduce((sum, p) => sum + p.runs.reduce((runs, r) => runs + r.text.length, 0), 0)
  }
  if (total > 200000) throw Error('母版文字草稿超过总量限制，原草稿已保留')
  return structuredClone(input)
}

function validParagraphs(value: unknown): value is MasterRichParagraph[] {
  if (!Array.isArray(value) || !value.length || value.length > 1000) return false
  let runs = 0
  return value.every((paragraph: any) => {
    if (!paragraph || Object.keys(paragraph).some(key => !['runs', 'srcPara', 'align'].includes(key)) || !Array.isArray(paragraph.runs) || !paragraph.runs.length || paragraph.runs.length > 5000) return false
    if (paragraph.srcPara !== undefined && (!Number.isInteger(paragraph.srcPara) || paragraph.srcPara < 0)) return false
    if (paragraph.align !== undefined && !['left', 'center', 'right', 'justify'].includes(paragraph.align)) return false
    return paragraph.runs.every((run: any) => {
      runs++
      return !!run && Object.keys(run).every(key => ['text', 'srcRun', 'bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color'].includes(key))
        && typeof run.text === 'string' && run.text.length <= 20000 && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/u.test(run.text)
        && (run.srcRun === undefined || Number.isInteger(run.srcRun) && run.srcRun >= 0)
        && ['bold', 'italic', 'underline', 'strike'].every(key => run[key] === undefined || typeof run[key] === 'boolean')
        && (run.fontSize === undefined || Number.isFinite(run.fontSize) && run.fontSize >= 1 && run.fontSize <= 1000)
        && (run.fontFamily === undefined || typeof run.fontFamily === 'string' && run.fontFamily.length <= 256 && !/[\u0000-\u001f]/u.test(run.fontFamily))
        && (run.color === undefined || /^#[0-9A-Fa-f]{6}$/.test(run.color))
    }) && runs <= 5000
  })
}

