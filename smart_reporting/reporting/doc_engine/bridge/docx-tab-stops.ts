export interface DocxTabStop {
  pos: number
  val: 'left' | 'center' | 'right' | 'decimal' | 'bar' | 'clear'
  leader?: 'none' | 'dot' | 'hyphen' | 'underscore' | 'heavy' | 'middleDot'
}
/** 仅接受可逆的原生绝对制表位；显示用 inherited/rel 不进入保存协议。 */
export function normalizeDocxTabStops(value: unknown): DocxTabStop[] {
  if (!Array.isArray(value) || value.length > 128) throw new Error('制表位列表无效')
  const seen = new Set<number>()
  return value.map(stop => {
    if (!stop || typeof stop !== 'object' || Array.isArray(stop)
      || Object.keys(stop).some(key => !['pos', 'val', 'leader'].includes(key))
      || !Number.isSafeInteger(stop.pos) || Math.abs(stop.pos) > 31680 || seen.has(stop.pos)
      || !['left', 'center', 'right', 'decimal', 'bar', 'clear'].includes(stop.val)
      || stop.leader !== undefined && !['none', 'dot', 'hyphen', 'underscore', 'heavy', 'middleDot'].includes(stop.leader)) throw new Error('制表位字段或位置无效')
    seen.add(stop.pos)
    return { pos: stop.pos, val: stop.val, ...(stop.leader !== undefined ? { leader: stop.leader } : {}) } as DocxTabStop
  }).sort((a, b) => a.pos - b.pos)
}
