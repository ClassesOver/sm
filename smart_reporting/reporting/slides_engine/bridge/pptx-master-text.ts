/** 母版文字按固定源 masterEditText → part-addressed setText 执行；不接受客户端 XML。 */
import { XMLValidator } from 'fast-xml-parser'
import { elementSpid, listMasterParts, parseMasterPart, type OpenedPptx } from '@genoffice/pptx-engine'

type MasterRichRun = { text: string; srcRun?: number; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean; fontSize?: number; fontFamily?: string; color?: string }
type MasterRichParagraph = { runs: MasterRichRun[]; srcPara?: number; align?: 'left' | 'center' | 'right' | 'justify' }
export type MasterTextEdit = { partPath: string; spid: number; text?: string; paragraphs?: MasterRichParagraph[] }
const partPattern = /^ppt\/(?:slideMasters\/slideMaster|slideLayouts\/slideLayout)[1-9]\d*\.xml$/
const validText = (text: unknown): text is string => typeof text === 'string' && text.length <= 20000 && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/u.test(text)

export function inspectMasterTextParts(opened: OpenedPptx) {
  const parts = listMasterParts(opened.archive)
  return parts.map(part => {
    const xml = opened.archive.readText(part.partPath) ?? ''
    let slide: ReturnType<typeof parseMasterPart> = null
    try { slide = parseMasterPart(opened.archive, part.partPath) } catch { /* 单个畸形部件只读，不阻止普通页面打开。 */ }
    const safePart = partPattern.test(part.partPath) && parts.filter(item => item.partPath === part.partPath).length === 1 && XMLValidator.validate(xml) === true
      && !/<!DOCTYPE|<!ENTITY/.test(xml) && xml.includes('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
      && xml.includes('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')
      && ![...xml.matchAll(/xmlns:(p|a)=["']([^"']+)["']/g)].some(match => match[2] !== (match[1] === 'p' ? 'http://schemas.openxmlformats.org/presentationml/2006/main' : 'http://schemas.openxmlformats.org/drawingml/2006/main'))
    return { ...part, structureEditable: safePart && slide !== null, elements: (slide?.elements ?? []).filter(el => el.type === 'text' || el.type === 'shape').map(el => {
      const spid = elementSpid(el), text = el.text?.paragraphs.map(p => p.runs.map(r => r.text).join('')).join('\n') ?? ''
      const paragraphs: MasterRichParagraph[] = (el.text?.paragraphs ?? []).map((p, srcPara) => ({
        srcPara, ...(p.align ? { align: p.align } : {}), runs: p.runs.map((r, srcRun) => ({
          text: r.text, srcRun, bold: !!r.bold, italic: !!r.italic, underline: !!r.underline, strike: !!r.strike,
          ...(r.fontSize ? { fontSize: r.fontSize } : {}), ...(r.fontFamily ? { fontFamily: r.fontFamily } : {}), ...(r.color && /^#[0-9A-Fa-f]{6}$/.test(r.color) ? { color: r.color.toUpperCase() } : {}),
        })),
      }))
      const validIdentity = safePart && spid !== null && Number.isInteger(spid) && spid > 0 && spid <= 4294967295
        && [...xml.matchAll(/<p:cNvPr\b[^>]*\bid=["'](\d+)["']/g)].filter(match => Number(match[1]) === spid).length === 1 && /^<p:sp[\s>]/.test(el.anchor.originalXml)
      const editable = validIdentity && !!el.text?.paragraphs.length
      const fillEditable = validIdentity && [...el.anchor.originalXml.matchAll(/<p:spPr[\s/>]/g)].length === 1
      const fillValue = el.fill?.type === 'none' ? 'none' : el.fill?.type === 'solid' && /^#[0-9A-Fa-f]{6}$/.test(el.fill.color) ? el.fill.color.toUpperCase() : null
      const strokeValue = !el.stroke || el.stroke.fill.type === 'none' ? 'none' : el.stroke.fill.type === 'solid' && /^#[0-9A-Fa-f]{6}$/.test(el.stroke.fill.color) ? el.stroke.fill.color.toUpperCase() : null
      const offset = el.transform?.offset
      const transformEditable = validIdentity && !!offset && [offset.x, offset.y, offset.cx, offset.cy, el.transform.rot].every(Number.isFinite)
      return { spid, name: el.name ?? `文字对象 ${spid}`, text, paragraphs, editable, reason: editable ? null : '此对象的母版部件、顶层文字或唯一 SPID 身份无法确认',
        fillEditable, fillValue, fillReason: fillEditable ? null : '此对象的母版部件、唯一 SPID 或可写形状属性无法确认',
        transformEditable, transformValue: transformEditable ? { x: offset!.x / 9525, y: offset!.y / 9525, width: offset!.cx / 9525, height: offset!.cy / 9525, rotationDeg: el.transform.rot / 60000 } : null,
        strokeEditable: validIdentity, strokeValue }
    }) }
  })
}

export function validateMasterTextEdits(opened: OpenedPptx, input: unknown): MasterTextEdit[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 200) throw Error('master_text_edits_invalid')
  const parts = inspectMasterTextParts(opened), seen = new Set<string>()
  let total = 0
  return input.map(item => {
    if (!item || typeof item !== 'object' || !['paragraphs,partPath,spid', 'partPath,spid,text'].includes(Object.keys(item).sort().join()) || typeof item.partPath !== 'string' || !partPattern.test(item.partPath)
      || !Number.isSafeInteger(item.spid) || item.spid <= 0 || item.spid > 4294967295
      || ('text' in item && !validText(item.text)) || ('paragraphs' in item && !validParagraphs(item.paragraphs))) throw Error('master_text_edit_invalid')
    const key = `${item.partPath}:${item.spid}`, element = parts.find(part => part.partPath === item.partPath)?.elements.find(el => el.spid === item.spid)
    total += item.text?.length ?? item.paragraphs!.reduce((sum, p) => sum + p.runs.reduce((runs, r) => runs + r.text.length, 0), 0)
    if (seen.has(key) || total > 200000 || !element?.editable) throw Error('master_text_identity_invalid')
    seen.add(key)
    return item.text !== undefined ? { partPath: item.partPath, spid: item.spid, text: item.text.replace(/\r\n?/g, '\n') } : { partPath: item.partPath, spid: item.spid, paragraphs: structuredClone(item.paragraphs!) }
  })
}

function validParagraphs(value: unknown): value is MasterRichParagraph[] {
  if (!Array.isArray(value) || !value.length || value.length > 1000) return false
  let count = 0
  return value.every((p: any) => {
    if (!p || Object.keys(p).some(key => !['runs', 'srcPara', 'align'].includes(key)) || !Array.isArray(p.runs) || !p.runs.length || p.runs.length > 5000
      || p.srcPara !== undefined && (!Number.isSafeInteger(p.srcPara) || p.srcPara < 0)
      || p.align !== undefined && !['left', 'center', 'right', 'justify'].includes(p.align)) return false
    return p.runs.every((r: any) => {
      count++
      return !!r && Object.keys(r).every(key => ['text', 'srcRun', 'bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color'].includes(key))
        && validText(r.text) && (r.srcRun === undefined || Number.isSafeInteger(r.srcRun) && r.srcRun >= 0)
        && ['bold', 'italic', 'underline', 'strike'].every(key => r[key] === undefined || typeof r[key] === 'boolean')
        && (r.fontSize === undefined || Number.isFinite(r.fontSize) && r.fontSize >= 1 && r.fontSize <= 1000)
        && (r.fontFamily === undefined || typeof r.fontFamily === 'string' && r.fontFamily.length <= 256 && !/[\u0000-\u001f]/u.test(r.fontFamily))
        && (r.color === undefined || /^#[0-9A-Fa-f]{6}$/.test(r.color))
    }) && count <= 5000
  })
}

export async function loadMasterOps() {
  let clearRawHook: (() => void) | undefined
  // 开发环境tsx回退与源构建的?raw语义一致；正式bundle由esbuild .md=text内联。
  if (import.meta.url.endsWith('.ts')) {
    const { registerHooks } = await import('node:module')
    const { readFileSync } = await import('node:fs')
    const rawDocs = new Set(['text', 'element', 'insert', 'table', 'slide', 'deck'].map(name => new URL(`../packages/pptx-ops/src/prompts/ops/${name}.md?raw`, import.meta.url).href))
    const hooks = registerHooks({ load(url, context, nextLoad) {
      if (!rawDocs.has(url)) return nextLoad(url, context)
      const file = new URL(url); file.search = ''
      return { format: 'module', source: `export default ${JSON.stringify(readFileSync(file, 'utf8'))}`, shortCircuit: true }
    } })
    clearRawHook = () => hooks.deregister()
  }
  // 沿用源事务的样式/run合并、字段/链接、part写回及继承重解析，不另写删run逻辑。
  const { runTxn } = await import('../packages/pptx-ops/src/index.ts').finally(() => clearRawHook?.())
  return runTxn
}

export async function applyMasterTextEdits(opened: OpenedPptx, edits: MasterTextEdit[]) {
  if (!edits.length) return
  const runTxn = await loadMasterOps()
  const current = inspectMasterTextParts(opened), ops = edits.flatMap(item => {
    const source = current.find(part => part.partPath === item.partPath)?.elements.find(el => el.spid === item.spid)
    if (!source?.editable) throw Error('master_text_identity_changed')
    if (source.text === item.text) return []
    return [{ op: 'setText', target: { part: item.partPath, el: `e_${item.spid}` }, paragraphs: item.paragraphs ?? item.text!.split('\n').map(text => ({ runs: [{ text }] })) }]
  })
  if (ops.length && !runTxn(opened, { ops }).applied) throw Error('master_text_source_transaction_failed')
}
