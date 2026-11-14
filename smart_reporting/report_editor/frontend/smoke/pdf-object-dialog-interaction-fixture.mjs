// 复用既有真实PDF产品宿主；仅聚焦对象属性，不导入其他格式，不执行保存。
import { openPdfHostDialog } from './office-pdf-host-fixture.mjs'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/pdf.css'

const root = document.createElement('main')
document.body.append(root)
window.pdfObjectInteractionHost = await openPdfHostDialog(root, new URLSearchParams(location.search).get('mode') ?? 'drawing-move')
document.documentElement.dataset.objectInteractionReady = 'true'
