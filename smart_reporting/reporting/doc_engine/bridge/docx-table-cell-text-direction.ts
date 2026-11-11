/** 单元格文字方向只补直属textDirection，合并owner覆盖所有物理continue。 */
import type {Block} from '@genoffice/docx-engine'
import {XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {applyTableCellTextDirectionSteps,Schema,type TableCellTextDirectionStep} from '../../../report_editor/frontend/src/docx-table-cell-text-direction-core.ts'
interface Element { name: string; xml: string; start: number }
export interface CellTextDirectionCell { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }
function fail(): never { throw new Error('docx_table_cell_text_direction_unsupported') }
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
type Direction='tbRl'|'btLr'|null
function sourceOf(block:Block){
 const xml=block.originalXml
 if(block.type!=='table'||!block.table||!xml||xml.length>1024*1024||XMLValidator.validate(xml)!==true||!/^<w:tbl(?:\s|>)/.test(xml)||/<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|cellMerge|tblPrEx)\b/.test(xml))fail()
 const root:Element={name:'w:tbl',xml,start:0},parts=children(root)
 if(parts.some(p=>!['w:tblPr','w:tblGrid','w:tr'].includes(p.name)))fail()
 const tableProps=one(parts,'w:tblPr',false)
 if(tableProps&&/<w:textDirection\b/.test(tableProps.xml))fail()
 const grid=one(parts,'w:tblGrid')!,columns=children(grid)
 if(/\s[^\s=<>]+\s*=/.test(/^<[^>]*>/.exec(grid.xml)?.[0]??'')||!columns.length||columns.length>30||columns.some(c=>c.name!=='w:gridCol'))fail()
 columns.forEach(c=>{leaf(c,['w:w']);const w=attr(c,'w:w')!.value;if(!/^\d+$/.test(w)||Number(w)<1||Number(w)>31680)fail()})
 const rows=parts.filter(p=>p.name==='w:tr')
 if(!rows.length||rows.length>100||rows.length*columns.length>1000||rows.length!==block.table.rows.length)fail()
 const cells:CellTextDirectionCell[]=[],directions:Direction[]=[],physical:{cell:CellTextDirectionCell;node:Element;props?:Element;direction?:Element;value:Direction}[]=[]
 let active=new Map<number,CellTextDirectionCell>()
 rows.forEach((row,r)=>{
  const rp=children(row),trPr=one(rp,'w:trPr',false)
  if(rp.some(p=>!['w:trPr','w:tc'].includes(p.name))||trPr&&/<w:textDirection\b/.test(trPr.xml))fail()
  const sourceCells=rp.filter(p=>p.name==='w:tc'),next=new Map<number,CellTextDirectionCell>()
  if(!sourceCells.length||sourceCells.length!==block.table!.rows[r].length)fail()
  let col=0
  sourceCells.forEach((node,c)=>{
   const cp=children(node),props=one(cp,'w:tcPr',false),pr=props?children(props):[]
   if(props&&/\s[^\s=<>]+\s*=/.test(/^<[^>]*>/.exec(props.xml)?.[0]??'')||cp.some(p=>!['w:tcPr','w:p','w:tbl','w:sdt'].includes(p.name))||new Set(pr.map(p=>p.name)).size!==pr.length)fail()
   const direction=one(pr,'w:textDirection',false),spanEl=one(pr,'w:gridSpan',false),mergeEl=one(pr,'w:vMerge',false)
   if(pr.some(p=>p!==direction&&/<w:textDirection\b/.test(p.xml)))fail()
   let value:Direction=null
   if(direction){leaf(direction,['w:val']);const raw=attr(direction,'w:val')!.value;if(!['lrTb','tbRl','tbRlV','btLr','btLrV'].includes(raw))fail();value=raw==='tbRl'||raw==='tbRlV'?'tbRl':raw==='btLr'||raw==='btLrV'?'btLr':null}
   if(spanEl)leaf(spanEl,['w:val']);if(mergeEl)leaf(mergeEl,['w:val'],[])
   if(pr.some(p=>p!==spanEl&&p!==mergeEl&&/<w:(?:gridSpan|vMerge|hMerge|gridBefore|gridAfter)\b/.test(p.xml)))fail()
   const rawSpan=spanEl?attr(spanEl,'w:val')!.value:'1',span=/^\d+$/.test(rawSpan)?Number(rawSpan):0,merge=mergeEl?attr(mergeEl,'w:val')?.value??'continue':undefined
   if(!Number.isSafeInteger(span)||span<1||col+span>columns.length||merge&&!['restart','continue'].includes(merge))fail()
   const model=block.table!.rows[r][c],effective=model.textDirection??null
   if((model.colSpan??1)!==span||model.vMerge!==merge||model.gridGap||effective!==value)fail()
   const cell:CellTextDirectionCell={top:r,left:col,bottom:r+1,right:col+span,physicalRow:r,physicalColumn:c}
   if(merge==='continue'){const owner=active.get(col);if(!owner||owner.right!==cell.right)fail();owner.bottom=r+1;next.set(col,owner)}else{cells.push(cell);directions.push(value);if(merge==='restart')next.set(col,cell)}
   physical.push({cell,node,props,direction,value});col+=span
  })
  if(col!==columns.length)fail();active=next
 })
 return{xml,rows,cells,directions,physical}
}
export function tableCellTextDirectionAvailability(block:Block){
 try{const s=sourceOf(block);return{cellTextDirectionEditable:true,cellTextDirectionReadOnlyReason:null,cellTextDirectionCells:s.cells,cellTextDirections:s.directions}}
 catch(error){return{cellTextDirectionEditable:false,cellTextDirectionReadOnlyReason:error instanceof Error?error.message:'docx_table_cell_text_direction_unsupported',cellTextDirectionCells:[] as CellTextDirectionCell[],cellTextDirections:[] as Direction[]}}
}
export function editTableCellTextDirection(block:Block,steps:readonly TableCellTextDirectionStep[]){
 const s=sourceOf(block),schema=new Schema({nodes:{doc:{content:'table'},text:{},p:{},table:{content:'row+',tableRole:'table'},row:{content:'cell*',tableRole:'row'},cell:{content:'p',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1},textDirection:{default:null},tcPrEdited:{default:false}}}}})
 const table=schema.node('table',null,s.rows.map((_,r)=>schema.node('row',null,s.cells.map((c,i)=>({c,i})).filter(({c})=>c.top===r).map(({c,i})=>schema.node('cell',{colspan:c.right-c.left,rowspan:c.bottom-c.top,textDirection:s.directions[i]},schema.node('p'))))))
 const result=applyTableCellTextDirectionSteps(table,steps),edits:{start:number;end:number;value:string}[]=[],physicalDirections:Direction[]=[]
 s.physical.forEach(item=>{
  const ownerIndex=s.cells.findIndex(c=>c.left<=item.cell.left&&c.right>=item.cell.right&&c.top<=item.cell.top&&c.bottom>item.cell.top)
  if(ownerIndex<0)fail()
  const owner=s.cells[ownerIndex],touched=steps.some(step=>step.top<owner.bottom&&step.bottom>owner.top&&step.left<owner.right&&step.right>owner.left)
  const direction=touched?result.directions[ownerIndex]:item.value;physicalDirections.push(direction)
  if(!touched)return
  const tag=direction?`<w:textDirection w:val="${direction}"/>`:''
  if(item.direction){
   if(!direction)edits.push({start:item.direction.start,end:item.direction.start+item.direction.xml.length,value:''})
   else{const field=attr(item.direction,'w:val')!;edits.push({...field,value:direction})}
  }else if(tag){
   if(!item.props){const at=item.node.start+item.node.xml.indexOf('>')+1;edits.push({start:at,end:at,value:`<w:tcPr>${tag}</w:tcPr>`})}
   else if(item.props.xml.endsWith('/>'))edits.push({start:item.props.start+item.props.xml.length-2,end:item.props.start+item.props.xml.length,value:`>${tag}</w:tcPr>`})
   else{const next=children(item.props).find(p=>['w:tcFitText','w:vAlign','w:hideMark','w:headers'].includes(p.name)),at=next?.start??item.props.start+item.props.xml.lastIndexOf('</');edits.push({start:at,end:at,value:tag})}
  }
 })
 let xml=s.xml;for(const edit of edits.sort((a,b)=>b.start-a.start))xml=xml.slice(0,edit.start)+edit.value+xml.slice(edit.end)
 return{xml,cells:s.cells,directions:result.directions,physicalDirections}
}
export function verifyTableCellTextDirectionResult(block:Block,result:ReturnType<typeof editTableCellTextDirection>){
 const s=sourceOf(block)
 if(block.originalXml!==result.xml||JSON.stringify(s.cells)!==JSON.stringify(result.cells)||JSON.stringify(s.directions)!==JSON.stringify(result.directions)||JSON.stringify(s.physical.map(c=>c.value))!==JSON.stringify(result.physicalDirections))fail()
}
