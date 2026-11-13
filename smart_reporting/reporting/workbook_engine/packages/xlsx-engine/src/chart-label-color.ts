import {SaxesParser} from 'saxes'
import {applyDrawingMlLuminance, resolveStyleColor, themeSlotIndex} from './style-color'

const DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main'

// Deliberately bounded to one RGB/scheme color, optionally lumMod then lumOff.
// Reject unknown, repeated, nested or reordered transforms as a whole.
export function chartLabelColor(fill: string, palette?: readonly string[]): string | undefined {
  try {
    const parser = new SaxesParser({xmlns:true})
    let depth = 0, colors = 0, invalid = false, color: string | undefined
    let multiplier = 1, offset = 0, seenMod = false, seenOff = false
    parser.on('opentag', node => {
      depth++
      if (node.uri !== DRAWING) invalid = true
      if (depth === 1) return
      const attrs = Object.values(node.attributes).filter(attr => attr.uri !== 'http://www.w3.org/2000/xmlns/')
      const raw = attrs.length === 1 && attrs[0]!.local === 'val' && !attrs[0]!.uri ? attrs[0]!.value : undefined
      if (depth === 2) {
        if (++colors !== 1) invalid = true
        if (node.local === 'srgbClr' && raw !== undefined && /^[a-fA-F0-9]{6}$/.test(raw)) color = '#'+raw.toUpperCase()
        else if (node.local === 'schemeClr' && raw !== undefined && palette) {
          const index = themeSlotIndex(raw)
          if (index !== undefined) color = resolveStyleColor({theme:index}, palette)
        }
      } else if (depth === 3) {
        if (raw === undefined || !/^\d+$/.test(raw) || Number(raw) > 100000) invalid = true
        const value = Number(raw) / 100000
        if (node.local === 'lumMod' && !seenMod && !seenOff) {multiplier = value; seenMod = true}
        else if (node.local === 'lumOff' && !seenOff) {offset = value; seenOff = true}
        else invalid = true
      } else invalid = true
    })
    parser.on('closetag', () => {depth--})
    parser.on('text', text => {if (text.trim()) invalid = true})
    parser.write(`<a:solidFill xmlns:a="${DRAWING}">${fill}</a:solidFill>`).close()
    if (invalid || colors !== 1 || !color) return undefined
    return seenMod || seenOff ? applyDrawingMlLuminance(color, multiplier, offset) : color
  } catch {
    return undefined
  }
}
