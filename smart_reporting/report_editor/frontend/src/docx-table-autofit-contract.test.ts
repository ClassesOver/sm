import { expect, it } from 'vitest'
import { replayDocxOperations, type DocxAnchor } from './docx-operations'

it('rejects AutoFit with same-section layout or section-break drafts before projection', () => {
  const fit = { kind: 'setTableAutoFit', blockId: 'table', expectedObjectSha256: 'sha', steps: [{ mode: 'fixed' }] }
  const anchor = { blockId: 'table', autoFitSectionId: 'section' } as DocxAnchor
  const layout = { kind: 'setSectionLayout', sectionId: 'section', expectedSectionSha256: 'section-sha', values: { marginLeft: 2500 } }
  for (const operations of [[fit, layout], [layout, fit], [fit, { kind: 'insertSectionBreak' }]]) {
    expect(() => replayDocxOperations({ type: 'doc' }, operations, [anchor])).toThrow(/自动调整与/)
  }
})

it('allows an independently anchored section break through the AutoFit dependency guard', () => {
  const fit = { kind: 'setTableAutoFit', blockId: 'table', expectedObjectSha256: 'sha', steps: [{ mode: 'fixed' }] }
  const anchors = [{ blockId: 'table', autoFitSectionId: 'first' }, { blockId: 'paragraph', sourceSectionId: 'second' }] as DocxAnchor[]
  // 来源节点故意缺失；不同节先通过依赖守卫，再由真实对象身份校验拒绝。
  expect(() => replayDocxOperations({ type: 'doc' }, [fit, { kind: 'insertSectionBreak', blockId: 'paragraph' }], anchors)).toThrow('草稿对象不属于当前 Word 文件')
})
