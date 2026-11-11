/** 九宫格仅补选中owner的直属jc与全部physical vAlign，保留continue隐藏段落。 */
import type {Block, TableParagraph} from '@genoffice/docx-engine'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {tableCellTextDirectionAvailability} from './docx-table-cell-text-direction.ts'
import {applyTableCellAlignmentSteps,Schema,type TableCellAlignmentStep,type CellAlignmentParagraph} from '../../../report_editor/frontend/src/docx-table-cell-alignment-core.ts'
import {inferredBidi} from '../../../report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/direction.ts'
interface Element { name: string; xml: string; start: number }
export interface CellAlignmentCell { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }
function fail(): never { throw new Error('docx_table_cell_alignment_unsupported') }
function children(node: Element): Element[] {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0]
  if (!open) fail()
  if (open.endsWith('/>')) return []
  const inner = node.xml.slice(open.length, node.xml.lastIndexOf('</')), parts = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== parts.map(p => p.xml).join('').replace(/\s/g, '')) fail()
  let cursor = open.length
  return parts.map(p => { const at = node.xml.indexOf(p.xml, cursor); cursor = at + p.xml.length; return { ...p, start: node.start + at } })
}
function attr(node: Element, key: string) {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  const m = [...open.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].filter(a => a[1] === key)
  if (m.length > 1) fail()
  if (!m.length) return undefined
  const start = node.start + m[0].index! + m[0][0].indexOf(m[0][2]) + 1
  return { value: m[0][3], start, end: start + m[0][3].length }
}
function leaf(node: Element, fields: string[], required: string[] = fields) {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  const attrs = [...open.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].map(m => m[1])
  if (attrs.some(a => !fields.includes(a)) || new Set(attrs).size !== attrs.length || required.some(a => !attrs.includes(a)) || !open.endsWith('/>') && node.xml.slice(open.length, node.xml.lastIndexOf('</')).trim()) fail()
}
function one(parts: Element[], name: string, required = true) { const matches = parts.filter(p => p.name === name); if (matches.length > 1 || required && !matches.length) fail(); return matches[0] }
type VAlign='center'|'bottom'|null
function sourceOf(block:Block){
 const geometry=tableCellTextDirectionAvailability(block)
 if(!geometry.cellTextDirectionEditable||!block.table||!block.originalXml)fail()
 const xml=block.originalXml,root:Element={name:'w:tbl',xml,start:0},rows=children(root).filter(p=>p.name==='w:tr'),cells=geometry.cellTextDirectionCells
 const physical:{node:Element;props?:Element;vertical?:Element;value:VAlign;owner:number;paras:{node:Element;props?:Element;jc?:Element;semantic:CellAlignmentParagraph}[]}[]=[],alignments:VAlign[]=[],paragraphs:CellAlignmentParagraph[][]=[]
 const directionSafe=(parts:Element[],target:string)=>{if(parts.some(p=>p.name!==target&&new RegExp(`<${target}\\b`).test(p.xml)))fail()}
 let owner=0
 rows.forEach((row,r)=>children(row).filter(p=>p.name==='w:tc').forEach((node,c)=>{
  const cp=children(node),props=one(cp,'w:tcPr',false),pr=props?children(props):[],vertical=one(pr,'w:vAlign',false),model=block.table!.rows[r][c]
  directionSafe(pr,'w:vAlign')
  let value:VAlign=null
  if(vertical){leaf(vertical,['w:val']);const raw=attr(vertical,'w:val')!.value;if(!['top','center','bottom'].includes(raw))fail();value=raw==='top'?null:raw as VAlign}
  if((model.vAlign==='top'?null:model.vAlign??null)!==value)fail()
  const isContinuation=model.vMerge==='continue',index=isContinuation?-1:owner++
  // physicalColumn不等于逻辑列；通过本行已消费span定位continue所属owner。
  const left=block.table!.rows[r].slice(0,c).reduce((sum,cell)=>sum+(cell.colSpan??1),0)
  const ownerIndex=isContinuation?cells.findIndex(cell=>cell.left===left&&cell.top<=r&&cell.bottom>r):index
  if(ownerIndex<0)fail()
  const paras:{node:Element;props?:Element;jc?:Element;semantic:CellAlignmentParagraph}[]=[]
  if(!isContinuation){
   if(cp.some(p=>p.name==='w:sdt'))fail()
   const actual=cp.filter(p=>p.name==='w:p'),rich:TableParagraph[]=model.richParas?.length?model.richParas:model.paras.map(text=>({runs:text===''?[]:[{text}],align:model.align}))
   if(actual.length!==rich.length||!actual.length)fail()
   actual.forEach((paragraph,i)=>{
    const pParts=children(paragraph),pPr=one(pParts,'w:pPr',false),pp=pPr?children(pPr):[],jc=one(pp,'w:jc',false)
    if(pPr&&/\s[^\s=<>]+\s*=/.test(/^<[^>]*>/.exec(pPr.xml)?.[0]??''))fail()
    directionSafe(pp,'w:jc')
    if(jc){leaf(jc,['w:val']);if(!['left','center','right','both','distribute','start','end','thaiDistribute','numTab','lowKashida','mediumKashida','highKashida'].includes(attr(jc,'w:val')!.value))fail()}
    const format=rich[i],semantic:CellAlignmentParagraph={type:'list' in format&&format.list?'docListItem':'docParagraph',align:format.align??null,bidi:format.bidi===true,bidiInherited:format.bidiInherited===true,bidiInferred:inferredBidi(format,format.runs)||format.bidiInherited===true}
    paras.push({node:paragraph,props:pPr,jc,semantic})
   })
   alignments.push(value);paragraphs.push(paras.map(p=>p.semantic))
  }
  physical.push({node,props,vertical,value,owner:ownerIndex,paras})
 }))
 if(owner!==cells.length)fail()
 return{xml,rows,cells,physical,alignments,paragraphs}
}
export function tableCellAlignmentAvailability(block:Block){
 try{const s=sourceOf(block);return{cellAlignmentEditable:true,cellAlignmentReadOnlyReason:null,cellAlignmentCells:s.cells,cellAlignments:s.alignments,cellAlignmentParagraphs:s.paragraphs}}
 catch(error){return{cellAlignmentEditable:false,cellAlignmentReadOnlyReason:error instanceof Error?error.message:'docx_table_cell_alignment_unsupported',cellAlignmentCells:[] as CellAlignmentCell[],cellAlignments:[] as VAlign[],cellAlignmentParagraphs:[] as CellAlignmentParagraph[][]}}
}
export function editTableCellAlignment(block:Block,steps:readonly TableCellAlignmentStep[]){
 const s=sourceOf(block),attrs={align:{default:null},bidi:{default:false},bidiInherited:{default:false},bidiInferred:{default:false}}
 const schema=new Schema({nodes:{doc:{content:'table'},text:{},docParagraph:{attrs},docListItem:{attrs},table:{content:'row+',tableRole:'table'},row:{content:'cell*',tableRole:'row'},cell:{content:'(docParagraph|docListItem)+',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1},vAlign:{default:null}}}}})
 const table=schema.node('table',null,s.rows.map((_,r)=>schema.node('row',null,s.cells.map((c,i)=>({c,i})).filter(({c})=>c.top===r).map(({c,i})=>schema.node('cell',{colspan:c.right-c.left,rowspan:c.bottom-c.top,vAlign:s.alignments[i]},s.paragraphs[i].map(p=>schema.node(p.type,p)))))))
 const result=applyTableCellAlignmentSteps(table,steps),edits:{start:number;end:number;value:string}[]=[],physicalAlignments:VAlign[]=[]
 const insert=(at:number,value:string)=>{const prior=edits.find(e=>e.start===at&&e.end===at);if(prior)prior.value+=value;else edits.push({start:at,end:at,value})}
 const leafEdit=(target:Element|undefined,parent:Element|undefined,node:Element,name:string,value:string|null)=>{
  if(target){if(value===null)edits.push({start:target.start,end:target.start+target.xml.length,value:''});else{const field=attr(target,'w:val')!;edits.push({...field,value})}return}
  if(value===null)return
  const tag=`<${name} w:val="${value}"/>`,container=name==='w:vAlign'?'w:tcPr':'w:pPr'
  if(!parent){
   const properties=`<${container}>${tag}</${container}>`
   if(node.xml.endsWith('/>'))edits.push({start:node.start+node.xml.length-2,end:node.start+node.xml.length,value:`>${properties}</${node.name}>`})
   else insert(node.start+node.xml.indexOf('>')+1,properties)
   return
  }
  if(parent.xml.endsWith('/>')){edits.push({start:parent.start+parent.xml.length-2,end:parent.start+parent.xml.length,value:`>${tag}</${container}>`});return}
  const following=name==='w:vAlign'?['w:hideMark','w:cellIns','w:cellDel','w:cellMerge','w:tcPrChange','w:headers']:['w:textDirection','w:textAlignment','w:textboxTightWrap','w:outlineLvl','w:divId','w:cnfStyle','w:rPr','w:sectPr','w:pPrChange']
  const next=children(parent).find(p=>following.includes(p.name));insert(next?.start??parent.start+parent.xml.lastIndexOf('</'),tag)
 }
 for(const item of s.physical){
  const cell=s.cells[item.owner],touched=steps.some(step=>step.top<cell.bottom&&step.bottom>cell.top&&step.left<cell.right&&step.right>cell.left),vertical=touched?result.alignments[item.owner]:item.value
  physicalAlignments.push(vertical)
  if(!touched)continue
  leafEdit(item.vertical,item.props,item.node,'w:vAlign',vertical)
  item.paras.forEach((para,i)=>{const semantic=result.paragraphs[item.owner][i];let jc=semantic.align;if((semantic.bidi||semantic.bidiInherited)&&(jc==='left'||jc==='right'))jc=jc==='left'?'right':'left';leafEdit(para.jc,para.props,para.node,'w:jc',jc)})
 }
 let xml=s.xml;for(const edit of edits.sort((a,b)=>b.start-a.start))xml=xml.slice(0,edit.start)+edit.value+xml.slice(edit.end)
 return{xml,cells:s.cells,alignments:result.alignments,paragraphs:result.paragraphs,physicalAlignments}
}
export function verifyTableCellAlignmentResult(block:Block,result:ReturnType<typeof editTableCellAlignment>){
 const s=sourceOf(block)
 if(block.originalXml!==result.xml||JSON.stringify(s.cells)!==JSON.stringify(result.cells)||JSON.stringify(s.alignments)!==JSON.stringify(result.alignments)||JSON.stringify(s.paragraphs)!==JSON.stringify(result.paragraphs)||JSON.stringify(s.physical.map(p=>p.value))!==JSON.stringify(result.physicalAlignments))fail()
}
