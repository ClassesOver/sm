import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateDocxPageBorderProps } from './docx-page-border-props.ts'

const props = {
  display: 'firstPage', offsetFrom: 'text', zOrder: 'back', spacePt: 7, widthPt: 2.25,
  sides: {
    top: { val: 'double', widthPt: 2.25, spacePt: 7, color: '123456', shadow: true },
    right: { val: 'single', widthPt: 0.5, spacePt: 4 },
  },
}

test('accepts the complete page border properties exposed by the source dialog', () => {
  assert.equal(validateDocxPageBorderProps(props), true)
  assert.equal(validateDocxPageBorderProps({
    display: 'notFirstPage', offsetFrom: 'page', spacePt: 0, widthPt: 1,
    sides: { bottom: { val: 'zigZagStitch', art: true, widthPt: 16, spacePt: 0 } },
  }), true)
})

test('rejects unknown, contradictory, and out-of-range page border data while allowing explicit clear', () => {
  for (const value of [
    { ...props, xml: '<w:pgBorders/>' },
    { ...props, display: 'oddPage' },
    { ...props, sides: { ...props.sides, top: { ...props.sides.top, color: '#123456' } } },
    { ...props, sides: { top: { val: 'single', widthPt: 0.51, spacePt: 7 } } },
    { ...props, sides: { top: { val: 'thick', widthPt: 1, spacePt: 7 } } },
    { ...props, sides: { top: { ...props.sides.top, frame: false } } },
    { ...props, sides: { top: { val: 'not-an-art-border', art: true, widthPt: 16, spacePt: 7 } } },
  ]) assert.equal(validateDocxPageBorderProps(value), false)
  assert.equal(validateDocxPageBorderProps(null), false)
  assert.equal(validateDocxPageBorderProps(null, true), true)
})
