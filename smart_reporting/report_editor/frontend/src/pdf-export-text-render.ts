import { Editor } from '@tiptap/core'
import { parseDocx, readSections, readSectionSettings } from '@genoffice/docx-engine'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { documentToMarkdown } from './vendor/genoffice-docs/apps/docs/src/renderer/export-markdown'
import { buildStandaloneHtml } from './vendor/genoffice-docs/apps/docs/src/renderer/html-export'
import { MARKDOWN_MEDIA_DIR_TOKEN } from './vendor/genoffice-docs/apps/docs/src/shared/ipc'
import { docStyleCss } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css'
import { setResolverFontTable } from './vendor/genoffice-docs/apps/docs/src/renderer/font-resolve'
import { adoptEmbeddedFonts } from './vendor/genoffice-docs/apps/docs/src/renderer/embedded-fonts'
import { loadDocxBundledFonts } from './docx-bundled-fonts'
import { scopeDocxStyleRules } from './docx-style-scope'
import './vendor/genoffice-docs/scoped.css'
import './docx.css'

export async function renderPdfTextExport(content:Uint8Array,format:'markdown'|'html'){
  const parsed=await parseDocx(content)
  setResolverFontTable(parsed.fontTable)
  await adoptEmbeddedFonts(parsed.embeddedFonts)
  await loadDocxBundledFonts()
  const host=document.createElement('div');host.className='docx-native'
  host.style.cssText='position:fixed;left:-100000px;top:0;pointer-events:none;z-index:-1'
  const settings=readSectionSettings(parsed),width=(settings.pageWidth-settings.marginLeft-settings.marginRight)/15
  const canvas=document.createElement('div');canvas.className='docx-canvas';canvas.style.width=width+'px';host.append(canvas)
  const style=document.createElement('style');style.textContent=docStyleCss(parsed);host.append(style);document.body.append(host)
  if(style.sheet)scopeDocxStyleRules(style.sheet)
  let editor:Editor|undefined
  try{
    editor=new Editor({element:canvas,editable:false,extensions:editorExtensions,content:blocksToPmDoc(parsed.blocks,readSections(parsed),pmDocOptions(parsed)) as never})
    editor.storage.listNumbering.styles=parsed.styles
    await document.fonts?.ready
    await Promise.all(Array.from(editor.view.dom.querySelectorAll('img')).map(async image=>{
      if(!/^data:image\/(?:png|jpeg|gif|webp|bmp);base64,/i.test(image.src))throw Error('导出图片缺少自包含数据，请下载已生成的 Word 文件核对')
      if(typeof image.decode==='function')await image.decode()
    }))
    const warnings=['内容与版式尚未通过完整保真验收，请人工核对；OCR 已禁用。','HTML/Markdown 基于转换后的 Word 正文重建，页眉页脚、分页与字体显示可能变化。']
    if(format==='markdown'){
      const exported=documentToMarkdown(editor)
      let text=exported.markdown
      for(const image of exported.images){
        if(!/^data:image\/(?:png|jpeg|gif|webp|bmp);base64,/i.test(image.src))throw Error('Markdown 图片缺少内嵌数据，请下载 Word 文件核对')
        text=text.split(MARKDOWN_MEDIA_DIR_TOKEN+'/'+image.name).join(image.src)
      }
      if(text.includes(MARKDOWN_MEDIA_DIR_TOKEN))throw Error('Markdown 图片引用未完成内嵌')
      warnings.push('Markdown 内嵌图片使用 data URL；部分阅读器不显示时请使用 HTML 或 Word。')
      return {text,warnings}
    }
    return {text:buildStandaloneHtml(editor.view.dom,{title:'PDF 转换报告',lang:'zh-CN',textWidthPx:width}),warnings}
  }finally{editor?.destroy();host.remove()}
}
