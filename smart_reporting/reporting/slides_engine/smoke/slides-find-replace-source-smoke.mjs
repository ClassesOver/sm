import assert from 'node:assert/strict'
import { addElement, createBlankPptx, openPptx, savePptx } from '../packages/pptx-engine/src/index.ts'
import { findReplaceEditable } from '../bridge/pptx-find-replace.ts'

const bytes = await createBlankPptx()
const opened = await openPptx(bytes)
const slide = opened.deck.slides[0]
addElement(slide, { kind: 'rect', offset: { x: 0, y: 0, cx: 100000, cy: 100000 }, paragraphs: [{ runs: [{ text: 'ordinary text' }] }] })
const saved = await savePptx(opened)
const reopened = await openPptx(saved)
const source = reopened.deck.slides[0].elements.find(element => element.text?.paragraphs[0]?.runs[0]?.text === 'ordinary text')
assert.ok(source && findReplaceEditable(source), source?.anchor.originalXml)
assert.equal(findReplaceEditable({ ...source, anchor: { ...source.anchor, originalXml: source.anchor.originalXml.replace('</a:p>', '<a:extLst><a:ext uri="custom"/></a:extLst></a:p>') } }), false)
console.log(JSON.stringify({ sourceBytes: bytes.byteLength, savedBytes: saved.byteLength, safeElement: source.id, safe: true, extensionRejected: true }))
