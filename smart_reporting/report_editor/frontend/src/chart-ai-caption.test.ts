import { Schema, type Node as ProseMirrorNode } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import { history, undo } from '@milkdown/kit/prose/history'
import type { EditorView } from '@milkdown/kit/prose/view'
import { describe, expect, it, vi } from 'vitest'

import type { ChartAIEditPage } from './api'
import { applyChartPagesReplacement } from './chart-ai-edit'
import { protocolMarkersUnchanged } from './protocol'

const schema = new Schema({ nodes: {
  doc: { content: 'block+' },
  paragraph: { content: 'inline*', group: 'block', attrs: { alignment: { default: null } } },
  image: { group: 'inline', inline: true, atom: true, attrs: { src: {}, alt: { default: '' } } },
  'image-block': { group: 'block', atom: true, attrs: { src: {}, caption: { default: '' } } },
  citation: { group: 'inline', inline: true, atom: true, attrs: { citationId: {}, label: { default: '' } } },
  unknown_atom: { group: 'inline', inline: true, atom: true },
  text: { group: 'inline' },
}, marks: { strong: {} } })
const p = (text: string) => schema.node('paragraph', null, schema.text(text))
const page = (number: number, count: number, id: string, title = `标题${number}`, altText = `图注${number}`): ChartAIEditPage => ({
  pageNumber: number, pageCount: count,
  imagePath: `reports/revision-1/chart-edits/${id}/${number === 1 ? 'chart.png' : `chart--page-${number}.png`}`,
  imageSrc: `chart-edits/${id}/${number === 1 ? 'chart.png' : `chart--page-${number}.png`}`,
  title, altText,
})
function viewFor(doc: ProseMirrorNode, selected = 0) {
  const view = {
    state: EditorState.create({ doc, plugins: [history()] }),
    posAtDOM: () => {
      const positions: number[] = []
      view.state.doc.descendants((node, from) => { if (['image', 'image-block'].includes(node.type.name)) positions.push(from) })
      return positions[selected] ?? positions[0] ?? 0
    },
    dispatch: vi.fn((tr: Transaction) => { view.state = view.state.apply(tr) }),
  }
  return view as unknown as EditorView & { dispatch: ReturnType<typeof vi.fn> }
}
const image = () => document.createElement('img')

describe('单页改图图题与图注完整保留引用', () => {
  it.each(['图表', '图注'])('%s中的文字引用随新文字保留，段落属性不变并可一次撤销', (kind) => {
    const original = schema.node('paragraph', { alignment: 'center' }, [schema.text(`${kind}：旧内容 `),
      schema.text('[[citation:caption_001]]', [schema.marks.strong!.create()])])
    const doc = schema.node('doc', null, [schema.node('image-block', { src: 'original.png' }), original, p('无关正文')])
    const view = viewFor(doc)
    const result = page(1, 1, 'cedit-new12345', '新标题', '新图注')
    expect(applyChartPagesReplacement(view, image(), [result], { basePath: '/b' })).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const caption = view.state.doc.child(1)
    expect(caption.textContent).toBe(`${kind}：${kind === '图表' ? '新标题' : '新图注'} [[citation:caption_001]]`)
    expect(caption.attrs.alignment).toBe('center')
    expect(caption.lastChild!.marks[0]!.type.name).toBe('strong')
    expect(protocolMarkersUnchanged(doc.textContent, view.state.doc.textContent)).toBe(true)
    expect(view.state.doc.lastChild!.textContent).toBe('无关正文')
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('同次更新两个紧邻说明段，保留跨文字节点的引用和原子引用节点', () => {
    const atom = schema.node('citation', { citationId: 'caption_002', label: '冻结来源' }, undefined, [schema.marks.strong!.create()])
    const title = schema.node('paragraph', null, [schema.text('图表：旧标题 '),
      schema.text('[[citation:', [schema.marks.strong!.create()]), schema.text('caption_001]]')])
    const alt = schema.node('paragraph', { alignment: 'right' }, [schema.text('图注：旧说明 '), atom])
    const doc = schema.node('doc', null, [schema.node('paragraph', null, schema.node('image', { src: 'original.png' })), title, alt])
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, image(), [page(1, 1, 'cedit-new12345', '长一些的新标题', '新的完整图注')], { basePath: '/b' })).toBe(true)
    expect(view.state.doc.child(1).textContent).toBe('图表：长一些的新标题 [[citation:caption_001]]')
    expect(view.state.doc.child(2).textContent).toBe('图注：新的完整图注 ')
    expect(view.state.doc.child(2).lastChild).toBe(atom)
    expect(view.state.doc.child(2).attrs.alignment).toBe('right')
    expect(view.state.doc.firstChild!.firstChild!.attrs.alt).toBe('新的完整图注')
    expect(protocolMarkersUnchanged(doc.textContent, view.state.doc.textContent)).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
  })

  it.each(['[[claim:claim_001]]', '[[analysis:analysis_001]]', '[[unknown:unknown_001]]', '[[citation:broken'])('未知或不可移动协议%s时整次拒绝', (protocol) => {
    const doc = schema.node('doc', null, [schema.node('image-block', { src: 'original.png' }), p(`图表：旧标题 ${protocol}`)])
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, image(), [page(1, 1, 'cedit-new12345')], { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('未知原子节点不能在替换图注时被删除', () => {
    const doc = schema.node('doc', null, [schema.node('image-block', { src: 'original.png' }),
      schema.node('paragraph', null, [schema.text('图注：旧说明'), schema.node('unknown_atom')])])
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, image(), [page(1, 1, 'cedit-new12345')], { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('新图题不能注入额外协议引用', () => {
    const doc = schema.node('doc', null, [schema.node('image-block', { src: 'original.png' }), p('图表：原标题')])
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, image(), [page(1, 1, 'cedit-new12345', '新标题 [[citation:injected]]')], { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('3→1→1时第二次同时更新图题图注，每次接受都有独立撤销边界', () => {
    const old = Array.from({ length: 3 }, (_, index) => page(index + 1, 3, 'cedit-old12345'))
    const doc = schema.node('doc', null, [...old.flatMap(item => [
      schema.node('paragraph', null, [schema.node('image', { src: item.imageSrc, alt: item.altText }), schema.text(` [[citation:page_${item.pageNumber}]]`)]),
      p(`图表：${item.title}`), p(`图注：${item.altText}`),
    ]), p('不相关正文 [[analysis:analysis_001]]')])
    const view = viewFor(doc, 1)
    const first = page(1, 1, 'cedit-first12345', '第一轮标题', '第一轮图注')
    expect(applyChartPagesReplacement(view, image(), [first], { basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old })).toBe(true)
    const firstDoc = view.state.doc
    const second = page(1, 1, 'cedit-second12345', '第二轮更长的标题', '第二轮更长的图注')
    expect(applyChartPagesReplacement(view, image(), [second], { basePath: '/b', previousEditId: 'cedit-first12345', previousPages: [first] })).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(2)
    expect(view.state.doc.child(1).textContent).toBe('图表：第二轮更长的标题')
    expect(view.state.doc.child(2).textContent).toBe('图注：第二轮更长的图注')
    expect(view.state.doc.lastChild!.eq(doc.lastChild!)).toBe(true)
    expect(protocolMarkersUnchanged(doc.textContent, view.state.doc.textContent)).toBe(true)
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(firstDoc)).toBe(true)
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })
})
