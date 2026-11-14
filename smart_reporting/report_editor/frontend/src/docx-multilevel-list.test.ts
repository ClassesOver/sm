import { expect, it } from 'vitest'
import { docxOperations, replayDocxOperations, type DocxPmNode } from './docx-operations'

const levels = Array.from({ length: 9 }, (_, ilvl) => ({ numFmt: 'decimal', lvlText: Array.from({ length: ilvl + 1 }, (_, i) => `%${i + 1}`).join('.') + '.', indentLeft: 720 * (ilvl + 1), hanging: 360, ...(ilvl ? { lvlRestart: ilvl } : {}) }))
const definition = { id: 'library-legal', levels }
const anchor = { docxIndex: 0, blockId: 'body', expectedObjectSha256: 'source', editable: true }
const baseline: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'center' }, content: [{ type: 'text', text: '原有正文', marks: [{ type: 'bold' }] }] }] }
const operation = { kind: 'setParagraphCustomList', blockId: 'body', expectedObjectSha256: 'source', definitionId: definition.id, levels, ilvl: 2 }

it('将同一份九级定义和段落绑定收集到既有草稿，并可独立恢复', () => {
  const edited = structuredClone(baseline), node = edited.content![0]!
  node.type = 'docListItem'
  node.attrs = { ...node.attrs, kind: 'ordered', numId: 'native-custom-library-legal', ilvl: 2, nativeListDefinition: definition }
  expect(docxOperations(baseline, edited, [anchor])).toEqual([operation])
  const restored = replayDocxOperations(baseline, [operation], [anchor])
  expect(restored.content![0]).toMatchObject(node)
  expect(docxOperations(baseline, restored, [anchor])).toEqual([operation])
  expect(baseline.content![0]!.type).toBe('docParagraph')
})

it('编号定义可以与同段人工文字和字符格式修改组合保存', () => {
  const edited = structuredClone(baseline), node = edited.content![0]!
  node.type = 'docListItem'
  node.attrs = { ...node.attrs, kind: 'ordered', numId: 'native-custom-library-legal', ilvl: 0, nativeListDefinition: definition }
  node.content = [{ type: 'text', text: '新的正文', marks: [{ type: 'bold' }] }]
  const operations = docxOperations(baseline, edited, [anchor])
  expect(operations).toEqual([{ ...operation, ilvl: 0 }, { kind: 'replaceParagraph', blockId: 'body', expectedObjectSha256: 'source', text: '新的正文' }])
  expect(docxOperations(baseline, replayDocxOperations(baseline, operations, [anchor]), [anchor])).toEqual(operations)
})

it.each([
  { ...operation, levels: [] },
  { ...operation, ilvl: 9 },
  { ...operation, levels: [{ ...levels[0], lvlRestart: 2 }] },
  { ...operation, levels: [{ ...levels[0], indentLeft: Infinity }] },
  { ...operation, levels: [{ ...levels[0], xml: '<w:lvl/>' }] },
])('恢复时拒绝无效编号定义：%j', invalid => {
  expect(() => replayDocxOperations(baseline, [invalid], [anchor])).toThrow()
})
