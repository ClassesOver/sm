import { expect, it } from 'vitest'
import { BULLET_GLYPHS, BULLET_SYMBOLS, NUMBER_TYPES, paragraphCommandPatch, projectParagraphs, uniformParagraphValue } from './slides-paragraph'

it('replays list operations in order, including per-paragraph clamping at both level bounds', () => {
  const source = [{ level: 0 }, { level: 8 }]
  const result = projectParagraphs([], source, [{ indentDelta: 1 }, { indentDelta: -1 }])
  expect(result.map(p => p.level ?? 0)).toEqual([0, 7])
  expect(source).toEqual([{ level: 0 }, { level: 8 }])
  expect(uniformParagraphValue(result, 'level')).toBeUndefined()
})
it('projects none and conditional options without claiming values the engine will not apply', () => {
  const source = [{ bulletKind: 'char' as const, bulletColor: '#123456', bulletSizePct: 90 }, { bulletKind: 'none' as const }]
  let states = projectParagraphs([], source, [{ bulletSizePct: 125 }, { startAt: 3 }])
  expect(states.map(p => p.bulletSizePct)).toEqual([125, undefined])
  expect(states.map(p => p.startAt)).toEqual([undefined, undefined])
  states = projectParagraphs([], source, [{ bullet: 'none' }, { bulletColor: '#000000' }, { bullet: 'number', numType: 'romanUcPeriod' }])
  expect(states.map(p => [p.bulletKind, p.bulletColor, p.bulletSizePct, p.numType])).toEqual([
    ['number', null, null, 'romanUcPeriod'], ['number', null, null, 'romanUcPeriod'],
  ])
})
it('distinguishes unset direction and spacing from explicit false and zero', () => {
  expect(uniformParagraphValue(projectParagraphs(), 'rtl')).toBeUndefined()
  const states = projectParagraphs([], [{ rtl: null }, { rtl: false }], [{ rtl: false, spaceBeforePt: 0 }])
  expect(uniformParagraphValue(states, 'rtl')).toBe(false)
  expect(uniformParagraphValue(states, 'spaceBeforePt')).toBe(0)
})
it('covers every pinned gallery and rejects malformed scalar, numeric and enum inputs', () => {
  for (const [index, [bulletChar, bulletFont]] of BULLET_GLYPHS.entries()) expect(paragraphCommandPatch('bulletCharPreset', String(index))).toEqual({ bullet: 'char', bulletChar, bulletFont })
  for (const symbol of BULLET_SYMBOLS) expect(paragraphCommandPatch('bulletSymbol', symbol)?.bulletChar).toBe(symbol)
  for (const numType of NUMBER_TYPES) expect(paragraphCommandPatch('numType', numType)).toEqual({ bullet: 'number', numType })
  expect(paragraphCommandPatch('bulletCustomChar', ' 😀extra ')).toEqual({ bullet: 'char', bulletChar: '😀', bulletFont: 'Arial' })
  for (const char of ['\u0000', '\ud800']) expect(paragraphCommandPatch('bulletCustomChar', char)).toBeNull()
  for (const bad of ['0', '32768', '1.5', '2suffix', '1e2', '-1']) expect(paragraphCommandPatch('startAt', bad)).toBeNull()
  expect(paragraphCommandPatch('startAt', '32767')).toEqual({ startAt: 32767 })
  expect(paragraphCommandPatch('bulletHangPx', '12,5')).toEqual({ bulletHangEmu: 119063 })
  expect(paragraphCommandPatch('bulletHangPx', 'NaN')).toBeNull()
  expect(paragraphCommandPatch('bulletSizePct', '99')).toBeNull()
  expect(paragraphCommandPatch('bulletColor', '#ab12cd')).toEqual({ bulletColor: '#AB12CD' })
})

it('checks each ordered margin mutation using the source explicit hanging flag', () => {
  const own = { bulletKind: 'char' as const, bulletChar: '•', level: 0, marLEmu: 51206400, indentEmu: -51206400, hasExplicitHangingIndent: true }
  expect(() => projectParagraphs([], [own], [{ indentDelta: 1 }])).toThrow('OOXML')
  expect(() => projectParagraphs([], [own], [{ indentDelta: 1 }, { indentDelta: -1 }])).toThrow('OOXML')
  const inherited = { ...own, hasExplicitHangingIndent: false }
  expect(projectParagraphs([], [inherited], [{ indentDelta: 1 }])[0]).toMatchObject({ level: 1, marLEmu: 51206400 })
  expect(() => projectParagraphs([], [{ ...inherited, indentEmu: null }], [{ bulletHangEmu: 51206400 }, { indentDelta: 1 }])).toThrow('OOXML')
  expect(projectParagraphs([], [own], [{ bullet: 'none' }, { indentDelta: 1 }])[0]).toMatchObject({ hasExplicitHangingIndent: false, marLEmu: 0, indentEmu: 0 })
})
