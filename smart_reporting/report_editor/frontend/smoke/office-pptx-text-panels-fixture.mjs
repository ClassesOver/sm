// 真实产品组件布局夹具；显式来源/回调不代表文件引擎或生产鉴权。
import { openSlidesFindReplace } from '../src/slides-find-replace'
import { createSlidesNotesPane } from '../src/slides-notes'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/slides.css'

const mode = new URLSearchParams(location.search).get('mode') ?? 'find'
const host = document.body.appendChild(document.createElement('main'))
Object.assign(host.style,{display:'flex',flexDirection:'column',height:'100dvh',minHeight:'0'})
const opener = host.appendChild(document.createElement('button')); opener.textContent = '打开面板'; opener.className = 'ui-button'
const canvas = host.appendChild(document.createElement('div'))
const documentLabel = canvas.appendChild(document.createElement('span')); documentLabel.textContent = '经营数据 Revenue 2026'; documentLabel.dataset.fixtureDocument = ''
Object.assign(canvas.style,{flex:'1',minHeight:'0',overflow:'auto',background:'var(--office-canvas)'})
window.officePptxPanelCommits = []; window.officePptxPanelNavigations = []
const source = [{slideIndex:0,elements:[{id:'title',type:'text',text:'经营数据 Revenue 经营数据',editable:true,findReplaceEditable:true}]}]
if(mode.startsWith('find')) opener.addEventListener('click',()=>{
  openSlidesFindReplace(host,{getSlides:()=>source,getEdits:()=>[],isLocked:()=>mode==='find-locked',onNavigate:(...target)=>window.officePptxPanelNavigations.push(target),onReplace:plan=>{
    if(mode==='find-error') throw Error('草稿暂未能写入：来源记录已经变化，请保留当前文字，重新选择来源对象后重试。'.repeat(3))
    window.officePptxPanelCommits.push(plan)
  }})
})
else {
  if(mode.startsWith('notes-host')) {
    host.classList.add('editor-format-pptx'); canvas.className='slides-stage'
    const frame=canvas.appendChild(document.createElement('div'));frame.className='slides-canvas'
    const figure=frame.appendChild(document.createElement('div'));figure.className='konvajs-content'
    Object.assign(figure.style,{position:'relative',width:'100%',height:'900px'})
    const bitmap=figure.appendChild(document.createElement('canvas'));bitmap.width=900;bitmap.height=900
    Object.assign(bitmap.style,{position:'absolute',inset:'0',width:'100%',height:'900px'})
    figure.append(documentLabel)
    const status=canvas.appendChild(document.createElement('p'));status.className='canvas-status';status.textContent='显式高画布夹具，不代表真实PPTX分页或内容'
  }
  const notes = createSlidesNotesPane(mode.startsWith('notes-host')?canvas:host,{onChange:(slideIndex,text)=>{
    if(mode.endsWith('error')) throw Error('演讲者备注暂未能提交，请保留输入后重试。'.repeat(4))
    window.officePptxPanelCommits.push({slideIndex,text})
  }})
  notes.update({slideIndex:0,text:'演讲者备注与财务口径\n'+'Revenue2026WithoutSpaces'.repeat(12),editable:!mode.endsWith('readonly'),reason:'当前来源备注包含复杂结构，暂仅支持阅读。'.repeat(4),visible:false})
  opener.addEventListener('click',()=>notes.setVisible(mode!=='notes-collapsed'))
}
document.documentElement.dataset.fixtureReady = 'true'
