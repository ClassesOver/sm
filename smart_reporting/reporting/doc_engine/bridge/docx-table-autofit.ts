/** AutoFit仅补目标表直属几何，复杂格内容与其他XML原样保留。 */
import type { Block } from '@genoffice/docx-engine'
import { XMLValidator } from 'fast-xml-parser'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { applyTableAutoFitSteps, Schema, type TableAutoFitStep, type TableAutoFitMode } from '../../../report_editor/frontend/src/docx-table-autofit-core.ts'
interface Element { name: string; xml: string; start: number }
export interface AutoFitCell { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }
function fail(): never { throw new Error('docx_table_autofit_unsupported') }
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
function sourceOf(block: Block, contentWidthTwips: number) {
  const xml = block.originalXml
  if (block.type !== 'table' || !block.table || !xml || xml.length > 1024*1024 || !Number.isSafeInteger(contentWidthTwips) || contentWidthTwips < 1 || contentWidthTwips > 31680 || XMLValidator.validate(xml) !== true || !/^<w:tbl(?:\s|>)/.test(xml) || /<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|cellMerge|tblPrEx|tblpPr|bidiVisual)\b/.test(xml)) fail()
  const root: Element = {name:'w:tbl',xml,start:0}, parts = children(root)
  if (parts.some(p=>!['w:tblPr','w:tblGrid','w:tr'].includes(p.name))) fail()
  const props = one(parts,'w:tblPr',false), grid = one(parts,'w:tblGrid')!
  const container = (node: Element) => { if (/\s[^\s=<>]+\s*=/.test(/^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0]??'')) fail(); return children(node) }
  const propParts = props ? container(props) : []
  if (new Set(propParts.map(p=>p.name)).size !== propParts.length || propParts.some(p=>!['w:tblW','w:tblLayout','w:tblBorders','w:tblCellMar','w:tblStyle','w:tblLook','w:jc','w:shd','w:tblCaption','w:tblDescription'].includes(p.name))) fail()
  const tableWidth = one(propParts,'w:tblW',false), layout = one(propParts,'w:tblLayout',false)
  const widthOf = (node: Element) => {
    leaf(node,['w:w','w:type'],['w:w'])
    const value = attr(node,'w:w')!.value, type = attr(node,'w:type')?.value ?? 'dxa'
    if (!/^\d+$/.test(value) || Number(value)>31680 || !['dxa','pct','auto','nil'].includes(type)) fail()
    return {value:Number(value),type}
  }
  const preferred = tableWidth ? widthOf(tableWidth) : {value:0,type:'auto'}
  if(layout){leaf(layout,['w:type']);if(!['fixed','autofit'].includes(attr(layout,'w:type')!.value))fail()}
  for(const p of propParts.filter(p=>p!==tableWidth&&p!==layout))if(/<w:(?:tblW|tblLayout|tblGrid|gridCol|tcW)\b/.test(p.xml))fail()
  const columns = container(grid)
  if(!columns.length||columns.length>30||columns.some(p=>p.name!=='w:gridCol'))fail()
  const widths = columns.map(p=>{leaf(p,['w:w']);const raw=attr(p,'w:w')!.value;if(!/^\d+$/.test(raw)||Number(raw)<1||Number(raw)>31680)fail();return Number(raw)})
  if(widths.reduce((a,b)=>a+b,0)>31680)fail()
  const rows = parts.filter(p=>p.name==='w:tr')
  if(!rows.length||rows.length>100||rows.length*widths.length>1000||rows.length!==block.table.rows.length)fail()
  const cells: AutoFitCell[] = [], physical: {cell:AutoFitCell; node:Element; props?:Element; width?:Element}[] = []
  let active = new Map<number,AutoFitCell>()
  rows.forEach((row,r)=>{
    const rowParts=children(row), rowProps=one(rowParts,'w:trPr',false)
    if(rowParts.some(p=>!['w:trPr','w:tc'].includes(p.name)))fail()
    if(rowProps){const rp=container(rowProps);if(new Set(rp.map(p=>p.name)).size!==rp.length||rp.some(p=>!['w:trHeight','w:cantSplit','w:tblHeader','w:hidden'].includes(p.name)))fail();if(rp.some(p=>/<w:(?:tcW|tblW|tblLayout|gridCol)\b/.test(p.xml)))fail()}
    const sourceCells=rowParts.filter(p=>p.name==='w:tc'),next=new Map<number,AutoFitCell>()
    if(!sourceCells.length||sourceCells.length!==block.table!.rows[r].length)fail()
    let col=0
    sourceCells.forEach((node,c)=>{
      const cp=children(node),props=one(cp,'w:tcPr',false),pr=props?container(props):[]
      if(cp.some(p=>!['w:tcPr','w:p','w:tbl','w:sdt'].includes(p.name))||new Set(pr.map(p=>p.name)).size!==pr.length||pr.some(p=>!['w:tcW','w:gridSpan','w:vMerge','w:tcBorders','w:shd','w:vAlign','w:textDirection','w:tcMar','w:noWrap','w:hideMark'].includes(p.name)))fail()
      const width=one(pr,'w:tcW',false),spanEl=one(pr,'w:gridSpan',false),mergeEl=one(pr,'w:vMerge',false)
      if(width)widthOf(width)
      if(spanEl)leaf(spanEl,['w:val']);if(mergeEl)leaf(mergeEl,['w:val'],[])
      for(const p of pr.filter(p=>p!==width&&p!==spanEl&&p!==mergeEl))if(/<w:(?:tcW|gridSpan|vMerge|tblW|tblLayout|gridCol)\b/.test(p.xml))fail()
      const rawSpan=spanEl?attr(spanEl,'w:val')!.value:'1',span=/^\d+$/.test(rawSpan)?Number(rawSpan):0,merge=mergeEl?attr(mergeEl,'w:val')?.value??'continue':undefined
      if(!Number.isSafeInteger(span)||span<1||col+span>widths.length||merge&&!['restart','continue'].includes(merge))fail()
      const model=block.table!.rows[r][c]
      if((model.colSpan??1)!==span||model.vMerge!==merge||model.gridGap)fail()
      const cell:AutoFitCell={top:r,left:col,bottom:r+1,right:col+span,physicalRow:r,physicalColumn:c}
      if(merge==='continue'){const owner=active.get(col);if(!owner||owner.right!==cell.right)fail();owner.bottom=r+1;next.set(col,owner)}else{cells.push(cell);if(merge==='restart')next.set(col,cell)}
      physical.push({cell,node,props,width});col+=span
    })
    if(col!==widths.length)fail();active=next
  })
  const pct=preferred.type==='pct'&&preferred.value>0&&preferred.value<=5000?preferred.value/50:0
  const autoWidth=!tableWidth||preferred.type==='auto'||preferred.type==='dxa'&&preferred.value===0
  const mode:TableAutoFitMode=layout&&attr(layout,'w:type')?.value==='fixed'||!autoWidth&&!pct?'fixed':pct===100?'window':'contents'
  if(block.table.autoFit!==mode)fail()
  return {xml,root,parts,props,propParts,grid,columns,tableWidth,layout,preferred,widths,cells,physical,rows,mode:mode as TableAutoFitMode}
}
export function tableAutoFitAvailability(block: Block, contentWidthTwips: number) {
  try { const s=sourceOf(block,contentWidthTwips);return {autoFitEditable:true,autoFitReadOnlyReason:null,autoFitMode:s.mode,autoFitWidthType:s.preferred.type,autoFitWidthValue:s.preferred.value,autoFitWidthsTwips:s.widths,autoFitContentWidthTwips:contentWidthTwips,autoFitCells:s.cells} }
  catch(error){return {autoFitEditable:false,autoFitReadOnlyReason:error instanceof Error?error.message:'docx_table_autofit_unsupported',autoFitMode:null,autoFitWidthType:null,autoFitWidthValue:null,autoFitWidthsTwips:[] as number[],autoFitContentWidthTwips:contentWidthTwips,autoFitCells:[] as AutoFitCell[]}}
}
export function editTableAutoFit(block: Block, contentWidthTwips: number, steps: readonly TableAutoFitStep[]) {
  const s=sourceOf(block,contentWidthTwips)
  const schema=new Schema({nodes:{doc:{content:'docTable'},text:{},p:{},docTable:{content:'row+',tableRole:'table',attrs:{tblAutoFit:{default:s.mode},tblAutoFitEdited:{default:false},widthPx:{default:null},widthPct:{default:null},colWidthsPct:{default:s.widths.map(w=>w/s.widths.reduce((a,b)=>a+b,0)*100)}}},row:{content:'cell*',tableRole:'row'},cell:{content:'p',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1},colwidth:{default:null}}}}})
  const table=schema.node('docTable',null,s.rows.map((_,r)=>schema.node('row',null,s.cells.filter(c=>c.top===r).map(c=>schema.node('cell',{colspan:c.right-c.left,rowspan:c.bottom-c.top},schema.node('p'))))))
  const result=applyTableAutoFitSteps(table,s.widths,contentWidthTwips,steps)
  const edits:{start:number;end:number;value:string}[]=[]
  const replace=(node:Element,value:string)=>edits.push({start:node.start,end:node.start+node.xml.length,value})
  const insert=(at:number,value:string)=>{const previous=edits.find(e=>e.start===at&&e.end===at);if(previous)previous.value+=value;else edits.push({start:at,end:at,value})}
  const total=result.widthsTwips.reduce((a,b)=>a+b,0),type=result.mode==='contents'?'auto':result.mode==='window'?'pct':'dxa',value=result.mode==='contents'?0:result.mode==='window'?5000:total
  const widthTag=`<w:tblW w:w="${value}" w:type="${type}"/>`,layoutTag=`<w:tblLayout w:type="${result.mode==='fixed'?'fixed':'autofit'}"/>`
  const updateWidth=(node:Element,width:number,widthType:string)=>{
    const w=attr(node,'w:w')!,t=attr(node,'w:type');const changes=[{start:w.start-node.start,end:w.end-node.start,value:String(width)}]
    if(t)changes.push({start:t.start-node.start,end:t.end-node.start,value:widthType})
    else{const at=node.xml.indexOf('>')-(node.xml[node.xml.indexOf('>')-1]==='/'?1:0);changes.push({start:at,end:at,value:` w:type="${widthType}"`})}
    let xml=node.xml;for(const c of changes.sort((a,b)=>b.start-a.start))xml=xml.slice(0,c.start)+c.value+xml.slice(c.end);replace(node,xml)
  }
  if(!s.props)insert(s.root.xml.indexOf('>')+1,`<w:tblPr>${widthTag}${layoutTag}</w:tblPr>`)
  else if(s.props.xml.endsWith('/>'))replace(s.props,`<w:tblPr>${widthTag}${layoutTag}</w:tblPr>`)
  else{
    if(s.tableWidth)updateWidth(s.tableWidth,value,type)
    else{const next=s.propParts.find(p=>!['w:tblStyle','w:tblpPr','w:tblOverlap','w:bidiVisual','w:tblStyleRowBandSize','w:tblStyleColBandSize'].includes(p.name));insert(next?.start??s.props.start+s.props.xml.lastIndexOf('</'),widthTag)}
    if(s.layout){const f=attr(s.layout,'w:type')!;edits.push({...f,value:result.mode==='fixed'?'fixed':'autofit'})}
    else{const next=s.propParts.find(p=>['w:tblCellMar','w:tblLook','w:tblCaption','w:tblDescription'].includes(p.name));insert(next?.start??s.props.start+s.props.xml.lastIndexOf('</'),layoutTag)}
  }
  s.columns.forEach((node,c)=>{const f=attr(node,'w:w')!;edits.push({...f,value:String(result.widthsTwips[c])})})
  for(const item of s.physical){const width=result.widthsTwips.slice(item.cell.left,item.cell.right).reduce((a,b)=>a+b,0),tag=`<w:tcW w:w="${width}" w:type="dxa"/>`;if(item.width)updateWidth(item.width,width,'dxa');else if(!item.props)insert(item.node.start+item.node.xml.indexOf('>')+1,`<w:tcPr>${tag}</w:tcPr>`);else if(item.props.xml.endsWith('/>'))replace(item.props,`<w:tcPr>${tag}</w:tcPr>`);else{const pr=children(item.props),next=pr.find(p=>!['w:cnfStyle'].includes(p.name));insert(next?.start??item.props.start+item.props.xml.lastIndexOf('</'),tag)}}
  let xml=s.xml
  for(const edit of edits.sort((a,b)=>b.start-a.start))xml=xml.slice(0,edit.start)+edit.value+xml.slice(edit.end)
  return {xml,mode:result.mode,widthsTwips:result.widthsTwips,cells:s.cells,contentWidthTwips}
}
export function verifyTableAutoFitResult(block:Block,result:ReturnType<typeof editTableAutoFit>){
  const s=sourceOf(block,result.contentWidthTwips)
  if(block.originalXml!==result.xml||s.mode!==result.mode||JSON.stringify(s.widths)!==JSON.stringify(result.widthsTwips)||JSON.stringify(s.cells)!==JSON.stringify(result.cells))fail()
  const expectedType=result.mode==='contents'?'auto':result.mode==='window'?'pct':'dxa',expectedValue=result.mode==='contents'?0:result.mode==='window'?5000:result.widthsTwips.reduce((a,b)=>a+b,0)
  if(!s.tableWidth||s.preferred.type!==expectedType||s.preferred.value!==expectedValue||!s.layout||attr(s.layout,'w:type')?.value!==(result.mode==='fixed'?'fixed':'autofit'))fail()
  for(const {cell,width} of s.physical)if(!width||attr(width,'w:type')?.value!=='dxa'||Number(attr(width,'w:w')?.value)!==result.widthsTwips.slice(cell.left,cell.right).reduce((a,b)=>a+b,0))fail()
}
