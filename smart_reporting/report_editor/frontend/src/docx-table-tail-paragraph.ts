import {docxInsertionAnchor} from './docx-insertion-anchor'
import type {Schema} from '@tiptap/pm/model'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
type Anchor={docxIndex:number;blockId:string;expectedObjectSha256:string;editable?:boolean}
const id=(node:DocxPmNode)=>node.attrs?.docxIndex
const fail=():never=>{throw new Error('表格后新增段落暂只支持普通文字，请保存后再修改格式')}
/** Called before the ordinary editable-paragraph fallback. New siblings share their nearest retained table. */
export function tableTailParagraphOperation(before:DocxPmNode[],after:DocxPmNode[],index:number,anchors:Anchor[],schema?:Schema):NativeOperation|undefined {
 const node=after[index]
 if(!node||id(node)!=null||node.type!=='docParagraph')return undefined
 // Use the common paragraph interval whenever possible so mixed rich/plain
 // siblings share one anchor instead of reversing across two source groups.
 if(docxInsertionAnchor(before,after,index,n=>['docParagraph','docHeading','docListItem'].includes(n.type)&&anchors.some(a=>a.docxIndex===id(n)&&a.editable===true)))return undefined
 const previous=after.slice(0,index).reverse().find(n=>id(n)!=null)
 if(previous?.type!=='docTable')return undefined
 const original=before.find(n=>id(n)===id(previous))
 const anchor=anchors.find(a=>a.docxIndex===id(previous))
 if(original?.type!=='docTable'||!anchor)fail()
 // A run of new plain paragraphs may follow a table; no intervening new object is silently reordered.
 const previousIndex=after.indexOf(previous)
 if(after.slice(previousIndex+1,index).some(n=>n.type!=='docParagraph'||id(n)!=null))fail()
 if(schema){
  const defaults=schema.nodes.docParagraph?.create({docxIndex:null}).attrs
  if(!defaults)fail()
  if(Object.entries(node.attrs??{}).some(([key,value])=>key==='docxIndex'?value!=null:JSON.stringify(value)!==JSON.stringify(defaults[key])))fail()
 }else if(Object.entries(node.attrs??{}).some(([key,value])=>key!=='docxIndex'&&value!=null&&value!==false))fail()
 if((node.content??[]).some(n=>n.type!=='text'||(n.marks??[]).some(m=>m.type!=='textStyle'||Object.values(m.attrs??{}).some(v=>v!=null&&v!==false))))fail()
 const text=(node.content??[]).map(n=>n.text??'').join('')
 return {kind:'insertParagraph',blockId:anchor!.blockId,expectedObjectSha256:anchor!.expectedObjectSha256,position:'after',text}
}
/** The schema supplies paragraph defaults; table attributes must never leak into the new paragraph. */
export function replayTableTailParagraph(content:DocxPmNode[],table:DocxPmNode,op:NativeOperation,anchor:Anchor,schema:Schema,afterCounts:Map<string,number>):void {
 if(table.type!=='docTable'||op.kind!=='insertParagraph'||op.position!=='after'||op.blockId!==anchor.blockId||op.expectedObjectSha256!==anchor.expectedObjectSha256
  ||Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','position','text'].includes(k))||typeof op.text!=='string'||op.text.length>20000||/[\x00-\x08\x0b-\x1f]/.test(op.text))fail()
 const index=content.indexOf(table)
 if(index<0||!schema.nodes.docParagraph)fail()
 const paragraph=schema.nodes.docParagraph.create({docxIndex:null},op.text?schema.text(op.text as string):undefined).toJSON() as DocxPmNode
 const offset=(afterCounts.get(anchor.blockId)??0)+1
 content.splice(index+offset,0,paragraph)
 afterCounts.set(anchor.blockId,offset)
}
