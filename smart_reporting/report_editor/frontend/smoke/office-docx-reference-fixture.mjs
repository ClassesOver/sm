// 产品组件夹具；来源模型显式构造，仅用于布局与键盘检查，不代表文件写回或后端授权。
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Editor, Extension } from '@tiptap/core'
import { DocxInsertSource } from '../src/docx-insert-source'
import { editorExtensions } from '../src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxBookmarksControls } from '../src/docx-bookmarks'
import { createDocxCrossReferenceControls, NativeDocxCrossReference } from '../src/docx-cross-reference'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/docx.css'

const mode = new URLSearchParams(location.search).get('mode') ?? 'link'
const root = document.body.appendChild(document.createElement('main'))
root.className = 'docx-native'
const opener = root.appendChild(document.createElement('button'))
opener.textContent = '打开设置'
const ribbon = root.appendChild(document.createElement('div'))
const panelHost = root.appendChild(document.createElement('div'))
const paper = root.appendChild(document.createElement('div'))
const text = '年度经营情况与财务数据说明'
const bookmarkIntent = Extension.create({ name: 'nativeBookmarkIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeBookmarkOperations: { default: null, rendered: false } } }] })
const editor = new Editor({ element: paper, extensions: [...editorExtensions, NativeDocxCrossReference, ...(mode.startsWith('bookmark') ? [bookmarkIntent] : [])],
  editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text }] },
  ] } })
editor.commands.setTextSelection({ from: 1, to: 5 })
window.officeReferenceEditor = editor
const sha = value => value.repeat(64)
const target = { targetId: sha('c'), blockIndex: 0, paragraphOrdinal: 0, expectedParagraphSha256: sha('d'), text, readOnlyReason: null }
const count = mode.endsWith('empty') ? 0 : 32
const model = { sourceSha256: sha('a'), sourceId: sha('b'), readOnlyReason: null, targets: [target],
  bookmarks: Array.from({ length: count }, (_, index) => ({ bookmarkId: index.toString(16).padStart(64, '0'),
    name: index % 2 ? '年度经营与财务数据对比分析专用书签名称_' + index : 'FinancialReportBookmarkWithLongUnbrokenName' + index,
    ranges: [{ targetId: target.targetId, expectedParagraphSha256: target.expectedParagraphSha256, from: 0, to: 4, text: text.slice(0, 4) }],
    readOnlyReason: index === 1 ? '复杂来源对象仅可查看，请在原始文件中核对。'.repeat(5) : null })) }
const readOnlyReason = () => mode.endsWith('readonly') ? '当前文档仅可查看，请联系文档所有者。'.repeat(4) : null
let controls
if (mode.startsWith('bookmark')) controls = createDocxBookmarksControls({ editor, container: panelHost, model, collectOperations: () => [], readOnlyReason, onError() {} })
else if (mode.startsWith('cross-reference')) controls = createDocxCrossReferenceControls({ editor, container: panelHost, model, collectOperations: () => [], readOnlyReason, onError() {} })
else {
  const react = createRoot(ribbon)
  const render = editable => flushSync(() => react.render(createElement(DocxInsertSource, { editor, editable, anchors: [{ docxIndex: 0, blockId: sha('e'), expectedObjectSha256: sha('f'), editable: true }] })))
  render(true)
  window.officeReferenceReadonly = () => { editor.setEditable(false); render(false) }
  opener.addEventListener('click', () => ribbon.querySelector('[data-action=insert-link]').click())
}
if (controls) {
  opener.addEventListener('click', () => controls.open())
  window.officeReferenceSetEditable = editable => { editor.setEditable(editable); controls.refresh() }
}
document.documentElement.dataset.fixtureReady = 'true'
