import type { MasterTextPart } from './slides-master-text-model'

export type MasterTextBoxAddition = { kind: 'addTextBox'; partPath: string; clientId: string; text: string; box: { x: number; y: number; width: number; height: number } }
export type MasterElementEdit = MasterTextBoxAddition | { kind: 'delete'; partPath: string; spid: number } | { kind: 'setFill'; partPath: string; spid: number; fill: string } | { kind: 'setStroke'; partPath: string; spid: number; stroke: { color: string; widthPt: 1 } | null } | { kind: 'setTransform'; partPath: string; spid: number; box: { x: number; y: number; width: number; height: number; rotationDeg: number } }

export function validateMasterElementDraft(input: unknown, parts: readonly MasterTextPart[]): MasterElementEdit[] {
  if (input === undefined) return []
  if (!Array.isArray(input) || input.length > 200) throw Error('母版文字对象草稿无效')
  const seen = new Set<string>(); let total = 0
  for (const item of input) {
    const part = parts.find(part => part.partPath === item?.partPath)
    if (!part?.structureEditable) throw Error('母版或版式来源身份无效')
    if (item.kind === 'delete' || item.kind === 'setFill' || item.kind === 'setStroke' || item.kind === 'setTransform') {
      const key = `${item.partPath}:${item.spid}`
      const element = part.elements.find(el => el.spid === item.spid)
      const expected = item.kind === 'setFill' ? 'fill,kind,partPath,spid' : item.kind === 'setStroke' ? 'kind,partPath,spid,stroke' : item.kind === 'setTransform' ? 'box,kind,partPath,spid' : 'kind,partPath,spid'
      const box = item.kind === 'setTransform' ? item.box : undefined
      if (Object.keys(item).sort().join() !== expected || !Number.isInteger(item.spid) || item.spid < 1 || item.spid > 4294967295
        || !(item.kind === 'setFill' ? element?.fillEditable : item.kind === 'setStroke' ? element?.strokeEditable : item.kind === 'setTransform' ? element?.transformEditable : element?.editable) || seen.has(key)
        || item.kind === 'setFill' && (typeof item.fill !== 'string' || !/^(?:none|#[0-9A-Fa-f]{6})$/.test(item.fill))
        || item.kind === 'setStroke' && !(item.stroke === null || !!item.stroke && Object.keys(item.stroke).sort().join() === 'color,widthPt' && item.stroke.widthPt === 1 && typeof item.stroke.color === 'string' && /^#[0-9A-Fa-f]{6}$/.test(item.stroke.color))
        || item.kind === 'setTransform' && (!box || Object.keys(box).sort().join() !== 'height,rotationDeg,width,x,y' || !['x', 'y', 'width', 'height', 'rotationDeg'].every(axis => typeof box[axis] === 'number' && Number.isFinite(box[axis]) && Math.abs(box[axis]) <= (axis === 'rotationDeg' ? 360 : 100000)) || box.width <= 0 || box.height <= 0)) throw Error('母版对象填充、几何或删除身份无效')
      seen.add(key); continue
    }
    const box = item.box, key = `new:${item.clientId}`
    if (item.kind !== 'addTextBox' || Object.keys(item).sort().join() !== 'box,clientId,kind,partPath,text' || typeof item.clientId !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(item.clientId) || seen.has(key)
      || typeof item.text !== 'string' || item.text.length > 20000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ud800-\udfff\ufffe\uffff]/u.test(item.text)) throw Error('新增文字框身份或文字无效')
    if (!box || Object.keys(box).sort().join() !== 'height,width,x,y' || !['x', 'y', 'width', 'height'].every(axis => typeof box[axis] === 'number' && Number.isFinite(box[axis]) && box[axis] >= 0 && box[axis] <= 100000) || !box.width || !box.height) throw Error('文字框位置或尺寸无效')
    total += item.text.length; if (total > 200000) throw Error('母版新增文字超过总量限制')
    seen.add(key)
  }
  return structuredClone(input)
}
