import {afterEach,describe,it,expect,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NodeSelection} from '@tiptap/pm/state'
import {createDocxPictureFormatControls} from './docx-picture-format-controls'
const Doc=Node.create({name:'doc',topNode:true,content:'block+'})
const Text=Node.create({name:'text',group:'inline'})
const Picture=Node.create({name:'docProtected',group:'block',atom:true,selectable:true,addAttributes:()=>Object.fromEntries(Object.entries({blockType:'image',docxIndex:1,imageDataUrl:'data:image/png;base64,YQ==',imageWidthPx:192,imageHeightPx:144,imageRotDeg:null,imageFlipH:false,imageFlipV:false,imageWrap:null,imageAlign:null,imagePosH:null,imagePosV:null,imageOffsetXEmu:null,imageOffsetYEmu:null,imageFormat:null,imageReplace:null}).map(([key,value])=>[key,{default:value}])),renderHTML:()=>['div']})
const anchor={docxIndex:1,blockId:'p',expectedObjectSha256:'xml',editable:false,imageEditable:true,imageFormatEditable:true,imageSha256:'media'}
const cleanup:(()=>void)[]=[]
afterEach(()=>{cleanup.splice(0).forEach(fn=>fn());vi.unstubAllGlobals()})
function setup(){const host=document.createElement('div');document.body.append(host);const editor=new Editor({element:host.appendChild(document.createElement('div')),extensions:[Doc,Text,Picture,UndoRedo],content:{type:'doc',content:[{type:'docProtected'}]},editorProps:{handleScrollToSelection:()=>true}});editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,0)));const errors:unknown[]=[];const controls=createDocxPictureFormatControls(editor,[anchor],host,()=>null,e=>errors.push(e),()=>624);cleanup.push(()=>{controls.dispose();editor.destroy();host.remove()});return{host,editor,controls,errors}}
describe('图片格式控制器',()=>{
 it('旋转保持图片选择并支持撤销',()=>{const {editor,controls,errors}=setup();controls.open('rotateRight');expect(editor.state.selection).toBeInstanceOf(NodeSelection);expect(editor.state.doc.firstChild!.attrs).toMatchObject({imageRotDeg:90,imageFormat:{rotDeg:90}});editor.commands.undo();expect(editor.state.doc.firstChild!.attrs.imageRotDeg).toBeNull();expect(errors).toEqual([])})
 it('位置预设清除拖动offset并产生配套环绕',()=>{const {editor,controls,host,errors}=setup();controls.open('position');const selects=host.querySelectorAll('select');selects[2].value='right';selects[3].value='bottom';host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));expect(editor.state.doc.firstChild!.attrs).toMatchObject({imagePosH:'right',imagePosV:'bottom',imageWrap:'square-right',imageOffsetXEmu:null,imageOffsetYEmu:null});expect(errors).toEqual([])})
 it('异步自然尺寸返回时文档改变，不写入迟到结果',()=>{let image:any;vi.stubGlobal('Image',class{naturalWidth=1200;naturalHeight=800;onload?:()=>void;src='';constructor(){image=this}});const {editor,controls,errors}=setup();controls.open('resetSize');controls.open('rotateRight');image.onload();expect(editor.state.doc.firstChild!.attrs.imageWidthPx).toBe(192);expect(errors).toHaveLength(1)})
})
