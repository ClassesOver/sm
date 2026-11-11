import { expect, it } from 'vitest'
import { commentTextError, sourceComments, validateCommentEdits } from './slides-comments'

const item = { authorId: 0, idx: 1, author: 'Alice', initials: 'A', dt: '', text: '来源批注' }
const sources = [{ comments: { items: [item, { ...item, authorId: 1, author: 'Bob' }], readOnlyReason: null } }, { comments: { items: [], readOnlyReason: null } }]
it('允许中文和emoji并保留首尾空白，拒绝空白、超限及非法XML字符', () => {
  expect(commentTextError(' 中文😀\n')).toBeNull()
  expect(commentTextError(' \n')).toContain('内容')
  expect(commentTextError('x'.repeat(10001))).toContain('10000')
  expect(commentTextError('\u0000')).toContain('字符')
  expect(commentTextError('\ud800')).toContain('字符')
})
it('未知来源或歧义身份保持只读，已核验项目仍可查看', () => {
  expect(sourceComments(undefined).readOnlyReason).toBeTruthy()
  expect(sourceComments({ items: [item], readOnlyReason: '现代批注只读' })).toEqual({ items: [item], readOnlyReason: '现代批注只读' })
  expect(sourceComments({ items: [item, item], readOnlyReason: null }).readOnlyReason).toContain('身份')
  expect(sourceComments({ items: [], readOnlyReason: '' }).readOnlyReason).toBeTruthy()
})
it('有序操作按原始页和作者组合身份校验，不误删同idx另一作者', () => {
  const edits = [{ slideIndex: 0, kind: 'delete', authorId: 1, idx: 1 }, { slideIndex: 0, kind: 'add', clientId: 'new-1', text: ' 新批注 ' }]
  expect(validateCommentEdits(edits, sources)).toEqual(edits)
})
it.each([
  [{ slideIndex: 2, kind: 'add', clientId: 'new-1', text: 'x' }],
  [{ slideIndex: 0, kind: 'delete', authorId: 7, idx: 1 }],
  [{ slideIndex: 0, kind: 'delete', authorId: 0, idx: 1 }, { slideIndex: 0, kind: 'delete', authorId: 0, idx: 1 }],
  [{ slideIndex: 0, kind: 'add', clientId: 'same', text: 'x' }, { slideIndex: 1, kind: 'add', clientId: 'same', text: 'y' }],
  [{ slideIndex: 0, kind: 'add', clientId: 'new-1', text: 'x', author: '冒认身份' }],
].map(edits => ({ edits })))('拒绝错误身份、重复或额外字段 %j', ({ edits }) => {
  expect(() => validateCommentEdits(edits, sources)).toThrow('批注')
})
it('拒绝只读页和同批删除页的操作', () => {
  const edit = [{ slideIndex: 0, kind: 'add', clientId: 'new-1', text: 'x' }]
  expect(() => validateCommentEdits(edit, [{ comments: { items: [], readOnlyReason: '现代批注' } }])).toThrow('现代批注')
  expect(() => validateCommentEdits(edit, sources, [0])).toThrow('删除')
})
it('严格处理XML字符、ECMAScript空白与500条上限', () => {
  expect(commentTextError('\ufeff')).toBeTruthy()
  expect(commentTextError('\u0085')).toBeNull()
  expect(commentTextError('😀'.repeat(5001))).toContain('10000')
  expect(() => validateCommentEdits(Array.from({ length: 501 }, (_, i) => ({ slideIndex: 0, kind: 'add', clientId: 'id-' + i, text: 'x' })), sources)).toThrow('500')
})
