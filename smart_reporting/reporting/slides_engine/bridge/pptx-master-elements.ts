/** 固定源 MasterView 的文字框增删；只操作源包中现有的母版/版式部件。 */
import type { OpenedPptx } from '@genoffice/pptx-engine'
import { inspectMasterTextParts, loadMasterOps } from './pptx-master-text.ts'

export type MasterElementEdit =
  | { kind: 'addTextBox'; partPath: string; clientId: string; text: string; box: { x: number; y: number; width: number; height: number } }
  | { kind: 'delete'; partPath: string; spid: number }
  | { kind: 'setFill'; partPath: string; spid: number; fill: string }
  | { kind: 'setStroke'; partPath: string; spid: number; stroke: { color: string; widthPt: 1 } | null }
  | { kind: 'setTransform'; partPath: string; spid: number; box: { x: number; y: number; width: number; height: number; rotationDeg: number } }

export function validateMasterElementEdits(opened: OpenedPptx, input: unknown): MasterElementEdit[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 200) throw Error('master_element_edits_invalid')
  const parts = inspectMasterTextParts(opened), seen = new Set<string>(); let total = 0
  return input.map(item => {
    if (!item || typeof item !== 'object' || !parts.some(part => part.partPath === item.partPath && part.structureEditable)) throw Error('master_element_part_invalid')
    if (item.kind === 'delete' || item.kind === 'setFill' || item.kind === 'setStroke' || item.kind === 'setTransform') {
      const key = `${item.partPath}:${item.spid}`
      const element = parts.find(part => part.partPath === item.partPath)?.elements.find(el => el.spid === item.spid)
      const expected = item.kind === 'setFill' ? 'fill,kind,partPath,spid' : item.kind === 'setStroke' ? 'kind,partPath,spid,stroke' : item.kind === 'setTransform' ? 'box,kind,partPath,spid' : 'kind,partPath,spid'
      const box = item.kind === 'setTransform' ? item.box : undefined
      if (Object.keys(item).sort().join() !== expected
        || !Number.isInteger(item.spid) || item.spid < 1 || item.spid > 4294967295 || !(item.kind === 'setFill' ? element?.fillEditable : item.kind === 'setStroke' ? element?.strokeEditable : item.kind === 'setTransform' ? element?.transformEditable : element?.editable) || seen.has(key)
        || item.kind === 'setFill' && (typeof item.fill !== 'string' || !/^(?:none|#[0-9A-Fa-f]{6})$/.test(item.fill))
        || item.kind === 'setStroke' && !(item.stroke === null || !!item.stroke && Object.keys(item.stroke).sort().join() === 'color,widthPt' && item.stroke.widthPt === 1 && typeof item.stroke.color === 'string' && /^#[0-9A-Fa-f]{6}$/.test(item.stroke.color))
        || item.kind === 'setTransform' && (!box || Object.keys(box).sort().join() !== 'height,rotationDeg,width,x,y' || !['x', 'y', 'width', 'height', 'rotationDeg'].every(axis => typeof box[axis] === 'number' && Number.isFinite(box[axis]) && Math.abs(box[axis]) <= (axis === 'rotationDeg' ? 360 : 100000)) || box.width <= 0 || box.height <= 0)) throw Error('master_element_identity_invalid')
      seen.add(key); return item.kind === 'setFill' ? { kind: 'setFill', partPath: item.partPath, spid: item.spid, fill: item.fill } : item.kind === 'setStroke' ? { kind: 'setStroke', partPath: item.partPath, spid: item.spid, stroke: item.stroke ? { ...item.stroke } : null } : item.kind === 'setTransform' ? { kind: 'setTransform', partPath: item.partPath, spid: item.spid, box: { ...item.box } } : { kind: 'delete', partPath: item.partPath, spid: item.spid }
    }
    const box = item.box, key = `new:${item.clientId}`
    if (item.kind !== 'addTextBox' || Object.keys(item).sort().join() !== 'box,clientId,kind,partPath,text'
      || typeof item.clientId !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(item.clientId) || seen.has(key)
      || typeof item.text !== 'string' || item.text.length > 20000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/u.test(item.text)
      || !box || Object.keys(box).sort().join() !== 'height,width,x,y' || !['x', 'y', 'width', 'height'].every(axis => typeof box[axis] === 'number' && Number.isFinite(box[axis]) && box[axis] >= 0 && box[axis] <= 100000) || box.width === 0 || box.height === 0) throw Error('master_textbox_invalid')
    total += item.text.length; if (total > 200000) throw Error('master_textbox_budget_exceeded')
    seen.add(key); return { kind: 'addTextBox', partPath: item.partPath, clientId: item.clientId, text: item.text.replace(/\r\n?/g, '\n'), box: { ...box } }
  })
}

export async function applyMasterElementEdits(opened: OpenedPptx, edits: MasterElementEdit[]) {
  if (!edits.length) return
  const runTxn = await loadMasterOps()
  const ops = edits.map(item => item.kind === 'delete'
    ? { op: 'deleteElement', target: { part: item.partPath, el: `e_${item.spid}` } }
    : item.kind === 'setFill' ? { op: 'setFill', target: { part: item.partPath, el: `e_${item.spid}` }, fill: item.fill }
    : item.kind === 'setStroke' ? { op: 'setStroke', target: { part: item.partPath, el: `e_${item.spid}` }, stroke: item.stroke ? { color: item.stroke.color, widthEmu: Math.round(item.stroke.widthPt * 12700) } : null }
    : item.kind === 'setTransform' ? { op: 'setTransform', target: { part: item.partPath, el: `e_${item.spid}` }, box: { x: Math.round(item.box.x * 9525), y: Math.round(item.box.y * 9525), cx: Math.round(item.box.width * 9525), cy: Math.round(item.box.height * 9525) }, rotDeg: item.box.rotationDeg }
    : { op: 'addElement', target: { part: item.partPath }, kind: 'textbox', offset: { x: Math.round(item.box.x * 9525), y: Math.round(item.box.y * 9525), cx: Math.round(item.box.width * 9525), cy: Math.round(item.box.height * 9525) }, paragraphs: item.text.split('\n').map(text => ({ runs: [{ text }] })), bodyPr: { wrap: 'none', autoFit: 'resize' } })
  if (!runTxn(opened, { ops }).applied) throw Error('master_element_source_transaction_failed')
}
