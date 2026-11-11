import { expect, it } from 'vitest'
import { docxRulerIndentOperation, normalizeDocxRulerIndent, projectDocxRulerIndent, replayDocxRulerIndent } from './docx-ruler-indent'
import { docxOperations, replayDocxOperations } from './docx-operations'
const anchor = { blockId: 'p1', expectedObjectSha256: 'a'.repeat(64), editable: true, rulerIndentEditable: true }
const source = () => ({ type: 'docParagraph', attrs: { indentLeft: null, indentFirstLine: null, indentRight: 125, styleId: 'Body' }, content: [{ type: 'text', text: '正文' }] })
it('首行与悬挂独立投影、任意左缩进及零值可严格回放', () => {
  const before = source(), after = projectDocxRulerIndent(before, anchor, { leftTwips: -133, firstLineTwips: -277 })
  expect(before.attrs.indentLeft).toBeNull()
  expect(after.attrs).toMatchObject({ indentLeft: -133, indentFirstLine: -277, indentRight: 125, nativeRulerIndent: { leftTwips: -133, firstLineTwips: -277 } })
  const op = docxRulerIndentOperation(before, after, anchor)!
  expect(op).toEqual({ kind: 'setParagraphRulerIndent', blockId: 'p1', expectedObjectSha256: anchor.expectedObjectSha256, leftTwips: -133, firstLineTwips: -277 })
  expect(replayDocxRulerIndent(before, anchor, op)).toEqual(after)
  expect(projectDocxRulerIndent(after, anchor, { firstLineTwips: 0 }).attrs).toMatchObject({ indentFirstLine: 0, indentLeft: -133, nativeRulerIndent: { leftTwips: -133, firstLineTwips: 0 } })
  expect(docxRulerIndentOperation(before, before, anchor)).toBeNull()
})
it('只接受非空整数协议，不接受额外字段、过期身份或复杂来源', () => {
  for (const values of [{}, { leftTwips: 1.5 }, { leftTwips: '120' }, { firstLineTwips: null }, { leftTwips: 14401 }, { leftTwips: 1, rightTwips: 3 }]) expect(() => normalizeDocxRulerIndent(values)).toThrow()
  const op = { kind: 'setParagraphRulerIndent', blockId: 'p1', expectedObjectSha256: anchor.expectedObjectSha256, firstLineTwips: 0 }
  expect(() => replayDocxRulerIndent(source(), anchor, { ...op, expectedObjectSha256: 'b'.repeat(64) })).toThrow()
  for (const node of [{ ...source(), type: 'docListItem' }, { ...source(), attrs: { bidi: true } }, { ...source(), attrs: { indentFirstLineChars: 200 } }]) expect(() => projectDocxRulerIndent(node, anchor, { leftTwips: 100 })).toThrow()
  expect(() => projectDocxRulerIndent(source(), { ...anchor, rulerIndentEditable: false }, { leftTwips: 0 })).toThrow()
})
it('显式意图禁止正文、其它格式混改以及伪造投影', () => {
  const before = source(), after = projectDocxRulerIndent(before, anchor, { firstLineTwips: 100 })
  for (const edited of [{ ...after, content: [{ type: 'text', text: '篡改' }] }, { ...after, attrs: { ...after.attrs, indentRight: 10 } }, { ...after, attrs: { ...after.attrs, indentFirstLine: 99 } }]) expect(() => docxRulerIndentOperation(before, edited, anchor)).toThrow()
})

it('显式零值覆盖继承而不退回样式CSS，草稿保持零值', () => {
  const before = source(), projected = projectDocxRulerIndent(before, anchor, { leftTwips: 0, firstLineTwips: 0 })
  expect(projected.attrs).toMatchObject({ indentLeft: 0, indentFirstLine: 0 })
  const op = docxRulerIndentOperation(before, projected, anchor)!
  expect(op).toMatchObject({ leftTwips: 0, firstLineTwips: 0 })
  expect(replayDocxRulerIndent(before, anchor, op).attrs).toMatchObject({ indentLeft: 0, indentFirstLine: 0 })
})

it('通过实际collector与草稿回放保持原子标尺操作并拒绝同段混改或重复', () => {
  const before = { type: 'doc', content: [{ ...source(), attrs: { ...source().attrs, docxIndex: 0, nativeRulerIndent: null } }] }
  const anchors = [{ ...anchor, docxIndex: 0 }]
  const edited = structuredClone(before)
  edited.content[0] = projectDocxRulerIndent(before.content[0]!, anchor, { leftTwips: 810, firstLineTwips: -277 }) as typeof before.content[0]
  const ops = docxOperations(before, edited, anchors)
  expect(ops).toEqual([{ kind: 'setParagraphRulerIndent', blockId: 'p1', expectedObjectSha256: anchor.expectedObjectSha256, leftTwips: 810, firstLineTwips: -277 }])
  expect(replayDocxOperations(before, ops, anchors)).toEqual(edited)
  expect(() => replayDocxOperations(before, [...ops, ...ops], anchors)).toThrow()
  expect(() => replayDocxOperations(before, ops, [{ ...anchors[0]!, editable: false }])).toThrow()
  expect(() => replayDocxOperations(before, ops, [{ ...anchors[0]!, rulerIndentEditable: false }])).toThrow()
  const combined = [...ops, { kind: 'setParagraphSpecialIndent', blockId: 'p1', expectedObjectSha256: anchor.expectedObjectSha256, twips: 277 }]
  expect(() => replayDocxOperations(before, combined, anchors)).toThrow()
  edited.content[0]!.content = [{ type: 'text', text: '混改' }]
  expect(() => docxOperations(before, edited, anchors)).toThrow()
})
