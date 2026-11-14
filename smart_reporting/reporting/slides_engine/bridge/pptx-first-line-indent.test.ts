import assert from 'node:assert/strict'
import test from 'node:test'
import { buildPagePptx, parsePageSpecObject } from '../packages/pipelines/src/slides/page-spec.ts'
import { openPptx } from '@genoffice/pptx-engine'
import { HeuristicMetrics, layoutText } from '@genoffice/pptx-render'

test('普通首行缩进按磅输出，项目符号仍保留负悬挂', async () => {
  const parsed = parsePageSpecObject({ background: '#FFFFFF', elements: [{
    type: 'text', x: 100, y: 100, w: 400, h: 200,
    paragraphs: [
      { indentPt: 48, runs: [{ text: '普通首行正文', sizePt: 18 }] },
      { indentPt: 48, bullet: true, runs: [{ text: '项目符号正文', sizePt: 18 }] },
      { indentPt: 0, runs: [{ text: '零首行正文', sizePt: 18 }] },
    ],
  }] })
  assert.equal(parsed.ok, true)
  if (!parsed.ok) throw new Error(parsed.error)
  const built = await buildPagePptx(parsed.spec, { fetchImage: async () => null })
  const opened = await openPptx(built.bytes)
  const text = opened.deck.slides[0]!.elements.find(element => element.type === 'text') as any
  assert.equal(text.transform.offset.x, 100 * 9525)
  const paragraphs = text.text.paragraphs
  assert.equal(paragraphs[0].indent, 48 * 12700)
  assert.equal(paragraphs[1].indent, -228600)
  assert.equal(paragraphs[1].marL, 228600)
  assert.equal(paragraphs[2].indent, 0)
  const layout = layoutText({ body: { paragraphs: paragraphs.slice(0, 1), wrap: true,
    anchor: 'top', insets: { l: 0, t: 0, r: 0, b: 0 } }, boxWidthPx: 400, boxHeightPx: 200,
    metrics: new HeuristicMetrics(), vp: { widthPx: 1280, heightPx: 720, scale: 1 } })
  assert.equal(layout.lines[0]!.runs[0]!.x, 64)
})
