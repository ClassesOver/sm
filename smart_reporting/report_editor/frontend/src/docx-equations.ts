import {Extension,type Editor} from '@tiptap/core'
import {closeHistory} from '@tiptap/pm/history'
import {NodeSelection} from '@tiptap/pm/state'
import type {Schema} from '@tiptap/pm/model'
import {inlineEquationNodeJson,equationBlockJson} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/equation'
import type {DocxEquationsModel,EquationOperation,EquationStep,EquationTarget} from '../../../reporting/doc_engine/bridge/docx-equations-core'
import type {DocxPmNode} from './docx-operations'
import type {NativeOperation} from './native-draft'
const clone=<T>(v:T):T=>JSON.parse(JSON.stringify(v))
const error=(s:string):never=>{throw new Error('公式：'+s)}
const attrs=['nativeEquationTarget','nativeEquationId','nativeEquationOffset']
export const NativeDocxEquations=Extension.create({name:'nativeDocxEquations',addGlobalAttributes:()=>[
 {types:['doc'],attributes:{nativeEquationOperation:{default:null,rendered:false}}},
 {types:['docParagraph','docHeading','docListItem','docInlineMath','docProtected'],attributes:Object.fromEntries(attrs.map(k=>[k,{default:null,rendered:false}]))},
]})
interface Token {node:DocxPmNode;size:number;formulaId?:string;display?:boolean}
const size=(n:DocxPmNode)=>n.type==='text'?(n.text??'').length:1
function inlineTokens(n:DocxPmNode):Token[]{return (n.content??[]).map(node=>({node,size:size(node),...(node.type==='docInlineMath'?{formulaId:String(node.attrs?.nativeEquationId),display:!!node.attrs?.display}:{})}))}
function formulaToken(latex:string,id:string,display:boolean,targetId:string):Token{
 if(typeof latex!=='string'||!latex.trim()||latex.length>20000)error('请输入有效 LaTeX')
 const node=inlineEquationNodeJson(latex) as DocxPmNode
 return {node:{...node,attrs:{...node.attrs,display,nativeEquationId:id,nativeEquationTarget:targetId}},size:1,formulaId:id,display}
}
function splitInsert(tokens:Token[],offset:number,token:Token){let at=0
 for(let i=0;i<tokens.length;i++){const t=tokens[i];if(offset===at){tokens.splice(i,0,token);return}if(offset>at&&offset<at+t.size){if(t.node.type!=='text')error('字符边界无效');const cut=offset-at,value=t.node.text!;if(/[\uD800-\uDBFF]/.test(value[cut-1])&&/[\uDC00-\uDFFF]/.test(value[cut]))error('不能拆开 Unicode 字符');tokens.splice(i,1,{...t,node:{...t.node,text:value.slice(0,cut)},size:cut},token,{...t,node:{...t.node,text:value.slice(cut)},size:value.length-cut});return}at+=t.size}
 if(offset!==at||!Number.isSafeInteger(offset)||offset<0)error('插入位置已变化');tokens.push(token)
}
function walk(n:DocxPmNode,visit:(n:DocxPmNode)=>void){visit(n);n.content?.forEach(c=>walk(c,visit))}
const registry=new WeakMap<Editor,EquationControls>()
export type EquationControls={reason:()=>string|null;insert:(latex:string,inline:boolean)=>void;update:(pos:number,latex:string)=>void;delete:(pos:number)=>void}
export const equationControls=(editor:Editor)=>registry.get(editor)
export function createDocxEquations(input:DocxEquationsModel|undefined){
 const model=input?clone(input):{sourceId:'',targets:[],readOnlyReason:'来源未提供公式编辑身份'},byId=new Map(model.targets.map(t=>[t.targetId,t]))
 const annotate=(value:DocxPmNode):DocxPmNode=>{
  const doc=clone(value)
  for(const block of doc.content??[]){const candidates=model.targets.filter(t=>t.blockIndex===block.attrs?.docxIndex),paragraphs:DocxPmNode[]=[]
   walk(block,n=>{if(['docParagraph','docHeading','docListItem'].includes(n.type)||n.type==='docProtected'&&n.attrs?.formulaDisplay)paragraphs.push(n)})
   if(candidates.length!==paragraphs.length){for(const t of candidates)t.readOnlyReason??='嵌套表格或保护容器的公式尚不能核验编辑投影';continue}
   candidates.forEach((target,i)=>{const n=paragraphs[i],text=(n.content??[]).filter(c=>c.type==='text').map(c=>c.text??'').join(''),math=(n.content??[]).filter(c=>c.type==='docInlineMath')
    if(target.readOnlyReason||target.text!==text||n.type==='docProtected'&&(target.formulas.length!==1||!!target.text)||n.type!=='docProtected'&&math.length!==target.formulas.length){target.readOnlyReason??='原文与公式编辑投影不一致';return}
    n.attrs={...n.attrs,nativeEquationTarget:target.targetId,nativeEquationOffset:0}
    if(n.type==='docProtected')n.attrs.nativeEquationId=target.formulas[0].formulaId
    else math.forEach((m,j)=>{m.attrs={...m.attrs,nativeEquationTarget:target.targetId,nativeEquationId:target.formulas[j].formulaId}})
   })
  }return doc
 }
 const read=(value:unknown):EquationOperation=>{
  if(!value||typeof value!=='object'||Array.isArray(value))error('草稿意图无效');const op=value as EquationOperation
  if(Object.keys(op).sort().join('|')!=='kind|sourceId|steps'||op.kind!=='editEquations'||op.sourceId!==model.sourceId||!Array.isArray(op.steps)||!op.steps.length||op.steps.length>500||model.readOnlyReason)error('来源身份已变化')
  for(const step of op.steps){const keys=step.action==='insert'?['action','display','latex','offset','targetId']:step.action==='update'?['action','formulaId','latex','targetId']:['action','formulaId','targetId'];if(!step||Object.keys(step).sort().join('|')!==keys.sort().join('|')||!['insert','update','delete'].includes(step.action)||!byId.has(step.targetId)||byId.get(step.targetId)!.readOnlyReason)error('操作身份无效');if(step.action==='insert'&&typeof step.display!=='boolean')error('显示方式无效')}
  return op
 }
 const project=(baseline:DocxPmNode,value:unknown,schema:Schema):DocxPmNode=>{
  const op=read(value),doc=clone(baseline),states=new Map<string,{target:EquationTarget;template:DocxPmNode;tokens:Token[]}>()
  walk(doc,n=>{const id=n.attrs?.nativeEquationTarget;if(typeof id!=='string'||!byId.has(id)||!['docParagraph','docHeading','docListItem','docProtected'].includes(n.type))return
   const target=byId.get(id)!;let tokens:Token[]
   if(n.type==='docProtected'){const f=target.formulas[0];tokens=[{...formulaToken(f.latex??'x',f.formulaId,true,id),node:clone(n)}]}else tokens=inlineTokens(n)
   states.set(id,{target,template:clone(n),tokens})
  })
  op.steps.forEach((step,index)=>{const state=states.get(step.targetId);if(!state)error('原段落不再存在');const {tokens}=state!
   if(step.action==='insert')splitInsert(tokens,step.offset,formulaToken(step.latex,'insert:'+index,step.display,step.targetId))
   else{const at=tokens.findIndex(t=>t.formulaId===step.formulaId);if(at<0)error('原公式不再存在');if(step.action==='delete')tokens.splice(at,1);else{const original=model.targets.flatMap(t=>t.formulas).find(f=>f.formulaId===step.formulaId);if(original?.readOnlyReason)error(original.readOnlyReason);tokens[at]=formulaToken(step.latex,step.formulaId,!!tokens[at].display,step.targetId)}}
  })
  const render=(n:DocxPmNode):DocxPmNode[]=>{
   const state=states.get(String(n.attrs?.nativeEquationTarget));if(state&&n===findTemplate(doc,state.target.targetId)){
    const {target,tokens,template}=state,base=template.type==='docProtected'?{type:'docParagraph',attrs:{docxIndex:template.attrs?.docxIndex,nativeEquationTarget:target.targetId}}:template
    if(target.container!=='body')return [{...base,content:tokens.map(t=>t.node)}]
    const result:DocxPmNode[]=[];let content:DocxPmNode[]=[],offset=0,start=0
    const flush=()=>{if(content.length)result.push({...base,attrs:{...base.attrs,docxIndex:result.length?null:base.attrs?.docxIndex,nativeEquationOffset:start},content});content=[]}
    for(const token of tokens){if(token.display){flush();const block=token.node.type==='docProtected'?token.node:equationBlockJson(String(token.node.attrs?.latex)) as DocxPmNode;result.push({...block,attrs:{...block.attrs,nativeEquationTarget:target.targetId,nativeEquationId:token.formulaId,nativeEquationOffset:offset}});offset++;start=offset}else{content.push(token.node);offset+=token.size}}
    flush();if(!result.length)result.push({...base,content:[]});return result
   }
   return [{...n,...(n.content?{content:n.content.flatMap(render)}:{})}]
  }
  const projected=render(doc)[0];projected.attrs={...projected.attrs,nativeEquationOperation:op};return schema.nodeFromJSON(projected).toJSON() as DocxPmNode
 }
 const findTemplate=(doc:DocxPmNode,id:string)=>{let result:DocxPmNode|undefined;walk(doc,n=>{if(!result&&n.attrs?.nativeEquationTarget===id&&['docParagraph','docHeading','docListItem','docProtected'].includes(n.type))result=n});return result}
 const replay=(baseline:DocxPmNode,operations:readonly NativeOperation[],schema:Schema)=>{const ops=operations.filter(op=>op.kind==='editEquations');if(!ops.length)return baseline;if(ops.length!==1||operations.length!==1)error('公式修改请单独保存');return project(baseline,ops[0],schema)}
 const normalize=(baseline:DocxPmNode,current:DocxPmNode,schema:Schema)=>{
  const op=current.attrs?.nativeEquationOperation;if(op==null)return {current,operations:[] as NativeOperation[]}
  const expected=project(baseline,op,schema);if(JSON.stringify(expected)!==JSON.stringify(current))error('公式结构或周围正文已变化，请撤销后重新操作')
  return {current:baseline,operations:[read(op) as unknown as NativeOperation]}
 }
 const controls=(editor:Editor,pending:()=>readonly NativeOperation[],containerReason:()=>string|null=()=>null):EquationControls=>{
  const baseline=editor.getJSON() as DocxPmNode
  const guard=()=>{const reason=containerReason();if(reason)error(reason);if(!editor.isEditable)error('当前文档不可编辑或正在保存');if(model.readOnlyReason)error(model.readOnlyReason);if(pending().some(op=>op.kind!=='editEquations'))error('请先保存其他修改，再编辑公式')}
  const commit=(step:EquationStep)=>{guard();const previous=editor.state.doc.attrs.nativeEquationOperation as EquationOperation|null,op:EquationOperation={kind:'editEquations',sourceId:model.sourceId,steps:[...(previous?.steps??[]),step]},next=editor.schema.nodeFromJSON(project(baseline,op,editor.schema)),tr=closeHistory(editor.state.tr.replaceWith(0,editor.state.doc.content.size,next.content).setDocAttribute('nativeEquationOperation',op));editor.view.dispatch(tr);editor.view.focus()}
  const targetAt=(pos:number)=>{const node=editor.state.doc.nodeAt(pos),id=node?.attrs.nativeEquationTarget;if(typeof id!=='string'||!byId.has(id))error('请选择可编辑的原生公式');return {node:node!,targetId:id as string}}
  const result:EquationControls={reason(){try{guard();const {$from,empty}=editor.state.selection;if(!empty||!$from.parent.attrs.nativeEquationTarget)error('请将光标放在正文或表格段落中');return null}catch(e){return (e as Error).message}},insert(latex,inline){guard();const {$from,empty}=editor.state.selection,id=$from.parent.attrs.nativeEquationTarget;if(!empty||typeof id!=='string')error('请选择正文或表格段落中的插入位置');commit({targetId:id,action:'insert',offset:Number($from.parent.attrs.nativeEquationOffset??0)+$from.parentOffset,display:!inline,latex})},update(pos,latex){const {node,targetId}=targetAt(pos);commit({targetId,action:'update',formulaId:String(node.attrs.nativeEquationId),latex})},delete(pos){const {node,targetId}=targetAt(pos);commit({targetId,action:'delete',formulaId:String(node.attrs.nativeEquationId)})}}
  registry.set(editor,result)
  const key=(event:KeyboardEvent)=>{if(!['Delete','Backspace'].includes(event.key)||!(editor.state.selection instanceof NodeSelection))return;const {from,node}=editor.state.selection;if(!node.attrs.nativeEquationId)return;event.preventDefault();try{result.delete(from)}catch(e){editor.view.dom.dispatchEvent(new CustomEvent('native-equation-error',{detail:e,bubbles:true}))}}
  editor.view.dom.addEventListener('keydown',key);editor.on('destroy',()=>{registry.delete(editor);editor.view.dom.removeEventListener('keydown',key)})
  return result
 }
 return {model,annotate,normalize,replay,controls}
}
