import {docxInsertionAnchor} from './docx-insertion-anchor'
import {closeHistory} from '@tiptap/pm/history'
import type {Editor} from '@tiptap/core'
import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import {normalizeDocxInsertObject, type DocxInsertObject} from './docx-insert-object-params'
import {WORDART_PRESETS,wordArtSolidColor} from './vendor/genoffice-docs/packages/ui/src/wordart-presets'
export {DOCX_OBJECT_SHAPES,normalizeDocxInsertObject,type DocxInsertObject} from './docx-insert-object-params'
export {WORDART_PRESETS}
/** Fixed-source display projection. genXml is deliberately absent: server generates it. */
export function projectNewDocxObject(value:unknown,schema:Schema):DocxPmNode {
 const v=normalizeDocxInsertObject(value), art=v.type==='wordArt', line=v.type==='shape'&&['line','lineArrow','lineArrowDouble','lineBent','lineCurved'].includes(v.preset!)
 const width=v.widthEmu??(art?2700000:1800000),height=line&&['line','lineArrow','lineArrowDouble'].includes(v.preset!)?114300:v.heightEmu??(art?720000:1080000)
 const p=art?WORDART_PRESETS.find(p=>p.id===v.preset):undefined
 const color=p?wordArtSolidColor(p).replace('#',''):undefined
 const box={widthPx:Math.round(width/9525),heightPx:Math.round(height/9525),
 ...(art?{wordArtId:v.preset}:line?{prst:v.preset,borderColor:'000000',readOnly:true,insetTopPx:0,insetRightPx:0,insetBottomPx:0,insetLeftPx:0}:v.type==='shape'?{prst:v.preset,fill:'4472C4',borderColor:'2F5496',vAlign:'center',textColor:'FFFFFF'}:{fill:'FFFFFF',borderColor:'000000'}),
 paras:line?[]:[{runs:[{text:v.text??(art?'艺术字':''),...(art?{color,bold:true,italic:p?.italic,sizeHalfPoints:72}:{})}],...(art||v.type==='shape'?{align:'center'}:{})}]}
 return schema.nodeFromJSON({type:'docProtected',attrs:{docxIndex:null,blockType:'passthrough',label:art?'艺术字':v.type==='shape'?'形状':'文本框',nativeObjectInsert:v,textboxes:[box]}}).toJSON() as DocxPmNode
}
export function docxObjectInsertUnavailable(editor:Editor,editable:boolean):string|undefined {
 if(!editable||!editor.isEditable)return '当前文档不可编辑或正在保存'
 if(!editor.schema.nodes.docProtected)return '当前编辑器不支持浮动对象'
 return undefined
}
export function insertDocxObject(editor:Editor,value:DocxInsertObject):boolean {
 const reason=docxObjectInsertUnavailable(editor,true);if(reason)throw new Error(reason)
 const {$from}=editor.state.selection,at=$from.depth>0?$from.after(1):editor.state.selection.to
 const previous=editor.state.doc
 const inserted=editor.chain().command(({tr})=>{closeHistory(tr);return true}).focus().insertContentAt(at,projectNewDocxObject(value,editor.schema)).run()
 if(!inserted||editor.state.doc===previous)throw new Error('对象未插入：此位置暂不能保存')
 return true
}

/** Strict per-node diff hook for docxOperations' existing ordered insertion loop. */
export function docxInsertObjectOperation(original:DocxPmNode,current:DocxPmNode,index:number,anchors:import('./docx-operations').DocxAnchor[],schema:Schema):import('./native-draft').NativeOperation|undefined {
 const node=current.content?.[index]
 if(node?.attrs?.nativeObjectInsert==null)return undefined
 if(node.type!=='docProtected'||node.attrs.docxIndex!=null)throw new Error('新增对象来源身份无效')
 const object=normalizeDocxInsertObject(node.attrs.nativeObjectInsert)
 if(JSON.stringify(node)!==JSON.stringify(projectNewDocxObject(object,schema)))throw new Error('新增对象保存前请使用对象设置修改纯文字和尺寸；暂不支持直接富文本或拖动布局')
 const byIndex=new Map(anchors.map(a=>[a.docxIndex,a]))
 const id=(n:DocxPmNode)=>n.attrs?.docxIndex
 const after=current.content??[],before=original.content??[]
 const retained=after.filter(n=>id(n)!=null),positions=retained.map(n=>before.findIndex(b=>id(b)===id(n)))
 if(positions.some((p,i)=>p<0||(i>0&&p<=positions[i-1])))throw new Error('文档锚点无效')
 const valid=(n:DocxPmNode)=>id(n)!=null&&byIndex.get(Number(id(n)))?.editable===true
 const insertion=docxInsertionAnchor(before,after,index,valid),target=insertion?.target
 const anchor=target&&byIndex.get(Number(id(target)))
 if(!anchor)throw new Error('新增对象没有可编辑的锚点段落')
 return {kind:'insertDocxObject',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,position:insertion!.position,object}
}
/** Replay hook: uses caller's shared afterCounts to retain mixed insertion order. */
export function replayDocxInsertObject(result:DocxPmNode,operation:import('./native-draft').NativeOperation,anchors:import('./docx-operations').DocxAnchor[],schema:Schema,afterCounts:Map<string,number>):void {
 if(Object.keys(operation).some(k=>!['kind','blockId','expectedObjectSha256','position','object'].includes(k))||operation.kind!=='insertDocxObject'||!['before','after'].includes(operation.position as string))throw new Error('草稿新增对象字段无效')
 const anchor=anchors.find(a=>a.blockId===operation.blockId&&a.expectedObjectSha256===operation.expectedObjectSha256&&a.editable)
 if(!anchor)throw new Error('草稿新增对象来源身份无效')
 const index=result.content?.findIndex(n=>n.attrs?.docxIndex===anchor.docxIndex)??-1
 if(index<0)throw new Error('草稿插入锚点已删除')
 const offset=operation.position==='after'?(afterCounts.get(anchor.blockId)??0)+1:0
 result.content!.splice(index+offset,0,projectNewDocxObject(operation.object,schema))
 if(operation.position==='after')afterCounts.set(anchor.blockId,offset)
}
