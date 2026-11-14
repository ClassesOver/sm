// 产品组件 + 显式分页夹具，仅作布局/键盘验证；真实文件由独立built smoke核对。
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Editor } from '@tiptap/core'
import { editorExtensions } from '../src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxNavigation } from '../src/docx-navigation'
import { DocxPageNumberDialog } from '../src/docx-page-number-dialog'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/docx.css'

const mode = new URLSearchParams(location.search).get('mode') ?? 'headings'
const root = document.body.appendChild(document.createElement('main')); root.className = 'docx-native'
Object.assign(root.style, { height:'100dvh', display:'flex', flexDirection:'column' })
const opener = root.appendChild(document.createElement('button')); opener.textContent = '打开设置'
const layout = root.appendChild(document.createElement('div')); layout.className = 'docx-navigation-layout'
const host = layout.appendChild(document.createElement('div')); host.className = 'docx-navigation-host'
const scroll = layout.appendChild(document.createElement('div')); scroll.className = 'editor-scroll'
const paper = scroll.appendChild(document.createElement('div'))
const content = Array.from({ length:36 }, (_, index) => ({ type:mode === 'empty' ? 'docParagraph' : 'docHeading', attrs:{ level:index % 3 + 1, docxIndex:index }, content:[{ type:'text', text:(index % 2 ? '年度经营财务分析与审计记录_' : 'FinancialReportUnbrokenHeadingWithLongName_') + index + ' 经营数据' }] }))
const editor = new Editor({ element:paper, extensions:editorExtensions, editorProps:{ handleScrollToSelection:() => true }, content:{ type:'doc', content } })
window.officeNavigationEditor = editor
window.officeNavigationCommits = []
if (mode.startsWith('page-number')) {
  const react = createRoot(host)
  opener.addEventListener('click', () => flushSync(() => react.render(createElement(DocxPageNumberDialog, { format:'upperRoman', start:3, label:'第2节：年度经营与财务报表'.repeat(3), onChange:values => window.officeNavigationCommits.push(values), onClose:() => flushSync(() => react.render(null)) }))))
} else {
  const nav = createDocxNavigation({ editor, container:host, onError:error => { throw error }, pages:{ getZoom:() => 1, getPagination:async () => {
    const blocks = [...editor.view.dom.children].map((el,index) => ({ el, top:index*24, height:24, domHeight:24 }))
    const section = { pageWidth:11906, pageHeight:16838, marginTop:1440, marginRight:1440, marginBottom:1440, marginLeft:1440 }
    return { section, sections:[{ settings:section }], geoms:[{ topPx:96 }], blocks, colMode:mode === 'pages-unsupported' ? 'mixed' : 'none', cuts:blocks.map((_,index) => ({ section:0, start:index*24, end:(index+1)*24, lead:{ kind:'block', block:index } })) }
  } } })
  opener.addEventListener('click', () => nav.open())
}
document.documentElement.dataset.fixtureReady = 'true'
