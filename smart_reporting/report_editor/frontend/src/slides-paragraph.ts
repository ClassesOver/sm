/** Fixed GenOffice paragraph options; wire patches retain execution order. */
export const BULLET_GLYPH_LABELS = ['•', '○', '▪', '❑', '❖', '➢', '✓'] as const
export const BULLET_GLYPHS = [['•', 'Arial'], ['o', 'Courier New'], ['§', 'Wingdings'], ['q', 'Wingdings'], ['v', 'Wingdings'], ['Ø', 'Wingdings'], ['ü', 'Wingdings']] as const
export const BULLET_SYMBOLS = [...'◆◇★☆✦➤➔→✓✗♦◉◎▸‣–']
export const NUMBER_TYPES = ['arabicPeriod', 'arabicParenR', 'romanUcPeriod', 'alphaUcPeriod', 'alphaLcParenR', 'alphaLcPeriod', 'romanLcPeriod', 'circleNumDbPlain', 'ea1ChsPeriod'] as const
export const BULLET_COLORS = ['#000000', '#5A5A5A', '#FFFFFF', '#C43E1C', '#E97132', '#FFC000', '#4EA72E', '#0F9ED5', '#0A50A1', '#7030A0']
export type ParagraphPatch = {
  align?: 'left' | 'center' | 'right' | 'justify'; lineSpacingPct?: number; spaceBeforePt?: number; spaceAfterPt?: number
  bullet?: 'char' | 'number' | 'none'; bulletChar?: string; bulletFont?: string; numType?: typeof NUMBER_TYPES[number]; startAt?: number
  bulletHangEmu?: number; bulletSizePct?: number; bulletColor?: string; rtl?: boolean; indentDelta?: 1 | -1
}
export type ParagraphFormatting = ParagraphPatch & { slideIndex: number; elementId: string }
export type ParagraphSourceFormatting = { [K in 'align' | 'lineSpacingPct' | 'spaceBeforePt' | 'spaceAfterPt']?: ParagraphPatch[K] | null } & {
  lineSpacingPt?: number | null; spaceBeforePct?: number | null; spaceAfterPct?: number | null
}
export type ParagraphList = {
  bulletKind?: 'char' | 'number' | 'none' | 'blip' | null; bulletChar?: string | null; bulletFont?: string | null
  numType?: string | null; startAt?: number | null; bulletSizePct?: number | null; bulletSizePt?: number | null; bulletColor?: string | null
  hasExplicitHangingIndent?: boolean; level?: number | null; rtl?: boolean | null; marLEmu?: number | null; indentEmu?: number | null
}
export type ParagraphState = ParagraphSourceFormatting & ParagraphList
/** UI projection only: preserves unspecified/mixed values and the source's conditional mutations. */
export function projectParagraphs(formatting: ParagraphSourceFormatting[] = [], lists: ParagraphList[] = [], patches: ParagraphPatch[] = []): ParagraphState[] {
  const states: ParagraphState[] = Array.from({ length: Math.max(formatting.length, lists.length, 1) }, (_, i) => ({ ...formatting[i], ...lists[i] }))
  const ownMargins = new Set(states.filter(state => state.hasExplicitHangingIndent))
  for (const patch of patches) for (const state of states) {
    if (patch.bullet) {
      if (patch.bullet === 'none') {
        ownMargins.delete(state)
        state.hasExplicitHangingIndent = false
        Object.assign(state, { bulletKind: 'none', bulletChar: null, bulletFont: null, numType: null, startAt: null, bulletSizePct: null, bulletSizePt: null, bulletColor: null, marLEmu: 0, indentEmu: 0 })
      } else {
        const previous = state.bulletKind
        const font = patch.bulletChar ? patch.bulletFont : (patch.bulletFont ?? state.bulletFont)
        if (!previous || previous === 'none') Object.assign(state, { bulletSizePct: null, bulletSizePt: null, bulletColor: null })
        Object.assign(state, patch.bullet === 'number'
          ? { bulletKind: 'number', bulletChar: null, bulletFont: null, numType: patch.numType ?? (previous === 'number' ? state.numType : null) ?? 'arabicPeriod', startAt: patch.startAt ?? (previous === 'number' ? state.startAt : null) }
          : { bulletKind: 'char', bulletChar: patch.bulletChar ?? '•', bulletFont: font ?? null, numType: null, startAt: null })
        if (patch.bulletHangEmu !== undefined || !(typeof state.indentEmu === 'number' && state.indentEmu < 0)) {
          const hang = patch.bulletHangEmu ?? 285750
          if (hang > 0) ownMargins.add(state)
          else ownMargins.delete(state)
          state.hasExplicitHangingIndent = hang > 0
          state.marLEmu = hang * ((state.level ?? 0) + 1); state.indentEmu = -hang
        }
      }
    } else {
      if (patch.bulletHangEmu !== undefined && ((state.bulletKind && state.bulletKind !== 'none') || (state.indentEmu ?? 0) < 0)) {
        if (patch.bulletHangEmu > 0) ownMargins.add(state)
        else ownMargins.delete(state)
        state.hasExplicitHangingIndent = patch.bulletHangEmu > 0
        state.marLEmu = patch.bulletHangEmu * ((state.level ?? 0) + 1); state.indentEmu = -patch.bulletHangEmu
      }
      if (state.bulletKind === 'number') {
        if (patch.numType !== undefined) state.numType = patch.numType
        if (patch.startAt !== undefined) state.startAt = patch.startAt
      }
    }
    if (state.bulletKind && state.bulletKind !== 'none') {
      if (patch.bulletSizePct !== undefined) { state.bulletSizePct = patch.bulletSizePct; state.bulletSizePt = null }
      if (patch.bulletColor !== undefined) state.bulletColor = patch.bulletColor
    }
    if (patch.align !== undefined) state.align = patch.align
    if (patch.rtl !== undefined) state.rtl = patch.rtl
    if (patch.lineSpacingPct !== undefined) { state.lineSpacingPct = patch.lineSpacingPct; state.lineSpacingPt = null }
    if (patch.spaceBeforePt !== undefined) { state.spaceBeforePt = patch.spaceBeforePt; state.spaceBeforePct = null }
    if (patch.spaceAfterPt !== undefined) { state.spaceAfterPt = patch.spaceAfterPt; state.spaceAfterPct = null }
    if (patch.indentDelta !== undefined) {
      const level = Math.max(0, Math.min(8, (state.level ?? 0) + patch.indentDelta))
      if (level !== (state.level ?? 0)) {
        state.level = level || null
        if (ownMargins.has(state) && (state.indentEmu ?? 0) < 0) state.marLEmu = -state.indentEmu! * (level + 1)
      }
    }
    // Match the bridge after every record; a later inverse operation cannot conceal overflow.
    if ((state.marLEmu != null && (state.marLEmu < 0 || state.marLEmu > 51206400)) || (state.indentEmu != null && Math.abs(state.indentEmu) > 51206400)) {
      throw new Error('悬挂缩进或段落缩进超出 OOXML 范围（56 英寸）；当前操作未应用')
    }
  }
  return states
}
export function uniformParagraphValue<K extends keyof ParagraphState>(states: ParagraphState[], field: K): ParagraphState[K] | undefined {
  return states.length && states.every(state => state[field] === states[0]![field]) ? states[0]![field] : undefined
}
const decimal = (value: string) => /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim().replace(',', '.')) ? Number(value.trim().replace(',', '.')) : NaN
export function paragraphCommandPatch(command: string, value: unknown): ParagraphPatch | null {
  if (command === 'bulletChar') return { bullet: 'char' }
  if (command === 'bulletNumber') return { bullet: 'number' }
  if (command === 'bulletNone') return { bullet: 'none' }
  if (command === 'indentDecrease' || command === 'indentIncrease') return { indentDelta: command === 'indentIncrease' ? 1 : -1 }
  if (command === 'directionLtr' || command === 'directionRtl') return { rtl: command === 'directionRtl' }
  if (typeof value !== 'string' || !value.trim()) return null
  if (command === 'bulletCharPreset' && /^[0-6]$/.test(value)) {
    const [bulletChar, bulletFont] = BULLET_GLYPHS[Number(value)]!
    return { bullet: 'char', bulletChar, bulletFont }
  }
  if (command === 'bulletSymbol' && BULLET_SYMBOLS.includes(value)) return { bullet: 'char', bulletChar: value, bulletFont: 'Arial' }
  if (command === 'bulletCustomChar') {
    const bulletChar = [...value.trim()][0]!
    const point = bulletChar.codePointAt(0)!
    return /[\p{Cc}\p{Cs}]/u.test(bulletChar) || point === 0x7f ? null : { bullet: 'char', bulletChar, bulletFont: 'Arial' }
  }
  if (command === 'numType' && NUMBER_TYPES.includes(value as typeof NUMBER_TYPES[number])) return { bullet: 'number', numType: value as typeof NUMBER_TYPES[number] }
  if (command === 'startAt' && /^\d+$/.test(value.trim())) {
    const startAt = Number(value); return startAt >= 1 && startAt <= 32767 ? { startAt } : null
  }
  if ((command === 'bulletColor' || command === 'bulletColorPreset') && /^#[0-9a-f]{6}$/i.test(value)) return { bulletColor: value.toUpperCase() }
  const number = decimal(value)
  if (!Number.isFinite(number)) return null
  if (command === 'bulletHangEmu' && [171450, 285750, 342900].includes(number)) return { bulletHangEmu: number }
  if (command === 'bulletHangPx' && number >= 0 && number <= 51206400 / 9525) return { bulletHangEmu: Math.round(number * 9525) }
  if (command === 'bulletSizePct' && [75, 90, 100, 125, 150].includes(number)) return { bulletSizePct: number }
  return null
}
export const PARAGRAPH_LIST_COMMANDS = ['bulletChar', 'bulletNumber', 'bulletNone', 'bulletCharPreset', 'bulletSymbol', 'bulletCustomChar', 'numType', 'startAt', 'bulletHangEmu', 'bulletHangPx', 'bulletSizePct', 'bulletColorPreset', 'bulletColor', 'indentDecrease', 'indentIncrease', 'directionLtr', 'directionRtl']
