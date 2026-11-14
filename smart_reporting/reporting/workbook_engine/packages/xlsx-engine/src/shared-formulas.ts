/// Eager counterpart of GenOffice shared-formula-index.ts. Only explicitly
/// stored formula cells participate; a ref span never creates missing cells.
import { parseAddress } from './cell-address'
import { offsetFormulaRefs } from './conditional-formatting-offset-source'
import { decodeXmlText, escapeXmlText, readXmlAttribute } from './xml'

const CELL = /<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g
const FORMULA = /<f\b([^>]*?)(?:\/>|>([\s\S]*?)<\/f>)/

interface Member { address: string; id: string; text: string }
interface SharedIndex {
  members: Map<string, Member>
  formulas: Map<string, string>
}

function invalid(reason: string): never {
  throw new Error(`共享公式无法解析：${reason}。`)
}

function sharedIndex(xml: string): SharedIndex {
  const members = new Map<string, Member>()
  const masters = new Map<string, Member>()
  for (const cell of xml.matchAll(CELL)) {
    const f = (cell[2] ?? '').match(FORMULA)
    if (!f || readXmlAttribute(f[1] ?? '', 't') !== 'shared') continue
    const address = readXmlAttribute(cell[1] ?? '', 'r')
    const si = readXmlAttribute(f[1] ?? '', 'si')
    if (!address || !/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(address)) invalid('单元格地址无效')
    if (si === undefined || !/^\d+$/.test(si) || Number(si) > 0xffffffff) invalid(`${address} 缺少有效 si`)
    const id = String(Number(si))
    const text = decodeXmlText(f[2] ?? '')
    const member = { address, id, text }
    if (members.has(address)) invalid(`${address} 重复`)
    members.set(address, member)
    if (text !== '') {
      if (masters.has(id)) invalid(`组 ${id} 有多个主单元格`)
      masters.set(id, member)
    }
  }
  const formulas = new Map<string, string>()
  for (const member of members.values()) {
    const master = masters.get(member.id)
    if (!master) invalid(`组 ${member.id} 缺少主单元格`)
    const origin = parseAddress(master.address), target = parseAddress(member.address)
    formulas.set(member.address, offsetFormulaRefs(master.text, target.row - origin.row, target.column - origin.column))
  }
  return { members, formulas }
}

export function sharedFormulaTexts(xml: string): ReadonlyMap<string, string> {
  return sharedIndex(xml).formulas
}

/// Detach a touched group before rewriting any member, including its master.
/// Other cell attributes, styles, cached values and untouched groups survive.
export function materializeEditedSharedFormulas(xml: string, addresses: ReadonlySet<string>): string {
  const { members, formulas } = sharedIndex(xml)
  const touched = new Set<string>()
  for (const address of addresses) {
    const member = members.get(address)
    if (member) touched.add(member.id)
  }
  if (touched.size === 0) return xml
  return xml.replace(CELL, (full: string, attrs: string, body: string | undefined) => {
    const address = readXmlAttribute(attrs, 'r')
    const member = address === undefined ? undefined : members.get(address)
    if (!member || !touched.has(member.id)) return full
    return `<c${attrs}>${body!.replace(FORMULA, () => `<f>${escapeXmlText(formulas.get(member.address)!)}</f>`)}</c>`
  })
}
