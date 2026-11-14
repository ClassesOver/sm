import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '@genoffice/docx-engine'
import {buildDocx} from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import {tableStyleAvailability,editTableStyle,verifyTableStyleResult,validateTableStyleOperation} from '../../../reporting/doc_engine/bridge/docx-table-style'
import {normalizeTableStylePatch,DEFAULT_TABLE_LOOK} from './docx-table-style-core'
import {projectDocxTableStyle,normalizeDocxTableStyle,replayDocxTableStyle} from './docx-table-style'
const style='<w:style w:type="table" w:styleId="Custom"><w:name w:val="Custom blue"/><w:tblStylePr w:type="firstRow"><w:tcPr><w:shd w:val="clear" w:fill="123456"/></w:tcPr></w:tblStylePr></w:style>'
const para='<w:p w:rsidR="0099"><w:bookmarkStart w:id="4" w:name="keep"/><w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> Keep &amp; rich </w:t></w:r><w:bookmarkEnd w:id="4"/></w:p>'
const cell=`<w:tc><w:tcPr><w:tcW w:w="2345" w:type="dxa"/><w:tcMar><w:left w:w="77" w:type="dxa"/></w:tcMar><w:vAlign w:val="center"/></w:tcPr>${para}</w:tc>`
const xml=`<w:tbl><w:tblPr><w:tblStyle w:val="Custom"/><w:tblW w:w="3333" w:type="dxa"/><w:tblCaption w:val="Keep"/></w:tblPr><w:tblGrid><w:gridCol w:w="3333"/></w:tblGrid><w:tr><w:trPr><w:cantSplit/></w:trPr>${cell}</w:tr><w:tr>${cell}</w:tr></w:tbl>`
async function source(){return parseDocx(await buildDocx({bodyXml:xml,extraStylesXml:style,headerXml:para}))}
it('writes all fixed source presets and look via source writer while preserving source paragraphs and non-target ZIP parts',async()=>{
 const parsed=await source(),block=parsed.blocks[0]
 expect(tableStyleAvailability(block,parsed).tableStyleEditable).toBe(true)
 for(const id of ['grid','blue-header','blue-banded','gray-banded','green-header'] as const){
 const result=editTableStyle(block,{style:{kind:'preset',id},look:{...DEFAULT_TABLE_LOOK,lastRow:true}},parsed)
 expect(result.xml).toContain(para);expect(result.xml).toContain('<w:tcW w:w="2345" w:type="dxa"/>');expect(result.xml).toContain('<w:tblCaption w:val="Keep"/>');expect(result.xml).toContain('<w:cantSplit/>');expect(result.xml).not.toContain('<w:tblStyle ')
 const output=await saveDocx(parsed,[{kind:'xml',docxIndex:0,xml:result.xml}]),reread=await parseDocx(output)
 verifyTableStyleResult(reread.blocks[0],result)
 expect(reread.blocks[0].table!.tableLook!.lastRow).toBe(true)
 const original=await JSZip.loadAsync(await buildDocx({bodyXml:xml,extraStylesXml:style,headerXml:para})),saved=await JSZip.loadAsync(output)
 for(const part of ['word/styles.xml','word/header1.xml','word/_rels/document.xml.rels'])expect(await saved.file(part)!.async('string')).toBe(await original.file(part)!.async('string'))
 }
})
it('none only clears style reference; document styles are source enumerated and do not overwrite direct cell formatting',async()=>{
 const parsed=await source(),block=parsed.blocks[0]
 expect(editTableStyle(block,{style:{kind:'none'}},parsed).xml).toBe(xml.replace('<w:tblStyle w:val="Custom"/>',''))
 expect(editTableStyle(block,{style:{kind:'document',styleId:'Custom'}},parsed).xml).toContain('<w:tblStyle w:val="Custom"/>')
 expect(()=>editTableStyle(block,{style:{kind:'document',styleId:'Normal'}},parsed)).toThrow()
 expect(()=>editTableStyle(block,{style:{kind:'document',styleId:'Missing'}},parsed)).toThrow()
})
it('validates exact source hash, protection, malformed XML and runtime keys before generating',async()=>{
 const parsed=await source(),block=parsed.blocks[0],op={kind:'setTableStyle',blockId:'b0',expectedObjectSha256:createHash('sha256').update(xml).digest('hex'),style:{kind:'none'}}
 expect(validateTableStyleOperation(block,op,parsed).xml).not.toContain('<w:tblStyle ')
 for(const input of [{...op,expectedObjectSha256:'f'.repeat(64)},{...op,xml:'<evil/>'},{...op,look:{...DEFAULT_TABLE_LOOK,lastRow:1}},{...op,style:{kind:'preset',id:'invented'}}])expect(()=>validateTableStyleOperation(block,input,parsed)).toThrow()
 expect(()=>editTableStyle(block,{style:{kind:'none'}},{...parsed,protection:{enforced:true}} as any)).toThrow()
 for(const broken of [xml.replace('<w:tblPr>','<w:tblPr><w:tblStyle w:val="other"/>'),xml.replace('<w:tcPr>','<w:tcPr><w:shd/><w:shd/>'),xml.replace('</w:tbl>','')])expect(tableStyleAvailability({...block,originalXml:broken},parsed).tableStyleEditable).toBe(false)
 for(const input of [{},{look:{}},{look:{...DEFAULT_TABLE_LOOK,alien:true}},{style:{kind:'none',xml:'x'}}])expect(()=>normalizeTableStylePatch(input)).toThrow()
})
const schema=new Schema({nodes:{doc:{content:'docTable'},text:{},p:{content:'text*'},docTable:{content:'row+',attrs:{docxIndex:{default:0},tblStyleId:{default:'Custom'},tblLook:{default:null},tblLookEdited:{default:false},nativeTableStyle:{default:null},nativeTableProperties:{default:null}}},row:{content:'cell+'},cell:{content:'p',attrs:{fill:{default:null},borders:{default:null}}}}})
const pm=()=>structuredClone(schema.node('docTable',null,[schema.node('row',null,[schema.node('cell',null,schema.node('p',null,schema.text('rich')))]),schema.node('row',null,[schema.node('cell',null,schema.node('p',null,schema.text('second')))])]).toJSON())
it('projects source attributes through real PM, normalizes dedicated intent and replays bound operations; rejects forged/mixed drafts',()=>{
 const anchor={docxIndex:0,blockId:'b0',expectedObjectSha256:'a'.repeat(64),tableStyleEditable:true,tableStyleSource:{styleId:'Custom',look:{...DEFAULT_TABLE_LOOK}},tableStyleOptions:[{styleId:'Custom',name:'Custom blue'}]},baseline={type:'doc',content:[pm()]}
 const projected=projectDocxTableStyle(pm(),anchor,{style:{kind:'preset',id:'blue-banded'},look:{...DEFAULT_TABLE_LOOK,lastRow:true}},schema)
 expect(projected.content![0].content![0].attrs!.fill).toBe('BDD7EE');expect(projected.content![1].content![0].attrs!.fill).toBe('DDEBF7')
 const live={type:'doc',content:[projected]},normalized=normalizeDocxTableStyle(baseline,live,[anchor],schema)
 expect(normalized.current).toEqual(baseline);expect(normalized.operations).toHaveLength(1)
 expect(replayDocxTableStyle(baseline,normalized.operations,[anchor],schema)).toEqual(live)
 const forged=structuredClone(live);forged.content[0].content![0].content![0].content![0].content![0].text='tampered'
 expect(()=>normalizeDocxTableStyle(baseline,forged,[anchor],schema)).toThrow()
 expect(()=>replayDocxTableStyle(baseline,[{...normalized.operations[0],expectedObjectSha256:'f'.repeat(64)}],[anchor],schema)).toThrow()
 expect(()=>projectDocxTableStyle(pm(),{...anchor,tableStyleEditable:false},{style:{kind:'none'}},schema)).toThrow()
 const mixed=pm();mixed.attrs!.nativeTableProperties={table:{align:'right'}};expect(()=>projectDocxTableStyle(mixed,anchor,{style:{kind:'none'}},schema)).toThrow()
 const stale=pm();stale.attrs!.tblStyleId='Missing';expect(()=>projectDocxTableStyle(stale,anchor,{style:{kind:'none'}},schema)).toThrow()
})
it('retains portable direct preset formatting when later selecting a document style or none',async()=>{
 const parsed=await source(),block=parsed.blocks[0],anchor={...tableStyleAvailability(block,parsed)}
 const first=projectDocxTableStyle(pm(),anchor,{style:{kind:'preset',id:'green-header'}},schema)
 const final=projectDocxTableStyle(first,anchor,{style:{kind:'document',styleId:'Custom'}},schema)
 expect(final.attrs!.tblStyleId).toBe('Custom');expect(final.content![0].content![0].attrs!.fill).toBe('E2F0D9')
 const result=editTableStyle(block,final.attrs!.nativeTableStyle,parsed),reread=await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:0,xml:result.xml}]))
 verifyTableStyleResult(reread.blocks[0],result)
 expect(reread.blocks[0].table!.rows[0][0].fill).toBe('E2F0D9')
 const cleared=projectDocxTableStyle(final,anchor,{style:{kind:'none'}},schema)
 expect(cleared.attrs!.tblStyleId).toBeNull();expect(cleared.content).toEqual(final.content)
})
it('lets document style inheritance return after grid clears direct shading',async()=>{
 const parsed=await source(),block=parsed.blocks[0],result=editTableStyle(block,{preset:'grid',style:{kind:'document',styleId:'Custom'}},parsed)
 const reread=await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:0,xml:result.xml}]))
 expect(reread.blocks[0].table!.rows[0][0].fill).toBe('123456')
 verifyTableStyleResult(reread.blocks[0],result)
})
import {afterEach} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {NodeSelection,TextSelection} from '@tiptap/pm/state'
import {applyDocxTableStyle,toggleDocxTableStyleLook,docxTableStyleUnavailable} from './docx-table-style-controls'
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(e=>e.destroy()))
function editorFixture(){
 const Doc=Node.create({name:'doc',topNode:true,content:'docTable+'}),Text=Node.create({name:'text',group:'inline'}),P=Node.create({name:'p',content:'text*',renderHTML:()=>['p',0]}),Row=Node.create({name:'row',content:'cell+',renderHTML:()=>['tr',0]}),Cell=Node.create({name:'cell',content:'p',addAttributes:()=>({fill:{default:null},borders:{default:null}}),renderHTML:()=>['td',0]})
 const Table=Node.create({name:'docTable',content:'row+',addAttributes:()=>({docxIndex:{default:0},tblStyleId:{default:'Custom'},tblLook:{default:null},tblLookEdited:{default:false},nativeTableStyle:{default:null},nativeTableProperties:{default:null}}),renderHTML:()=>['table',['tbody',0]]})
 const editor=new Editor({extensions:[Doc,Text,P,Row,Cell,Table,UndoRedo],content:{type:'doc',content:[pm()]},editorProps:{handleScrollToSelection:()=>true}});editors.push(editor)
 const anchors=[{docxIndex:0,blockId:'b0',expectedObjectSha256:'a'.repeat(64),tableStyleEditable:true,tableStyleSource:{styleId:'Custom',look:{...DEFAULT_TABLE_LOOK}},tableStyleOptions:[{styleId:'Custom',name:'Custom blue'}]}]
 return{editor,anchors}
}
it('controller selects the table from caret or node selection, dispatches one undoable transaction and reflects look toggles',()=>{
 const {editor,anchors}=editorFixture();editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc,4)))
 const selection=editor.state.selection.toJSON(),original=editor.getJSON()
 expect(docxTableStyleUnavailable(editor,anchors)).toBeNull()
 expect(applyDocxTableStyle(editor,{style:{kind:'preset',id:'blue-header'}},anchors)).toBe(true)
 expect(editor.state.doc.child(0).child(0).child(0).attrs.fill).toBe('D9EAF7');expect(editor.state.selection.toJSON()).toEqual(selection)
 expect(editor.commands.undo()).toBe(true);expect(editor.getJSON()).toEqual(original)
 expect(editor.commands.redo()).toBe(true)
 editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,0)))
 expect(toggleDocxTableStyleLook(editor,'lastColumn',anchors)).toBe(true)
 expect(editor.state.doc.child(0).attrs.tblLook.lastColumn).toBe(true)
 const live=editor.getJSON(),normalized=normalizeDocxTableStyle(original,live,anchors,editor.schema)
 expect(normalized.operations).toHaveLength(1);expect(replayDocxTableStyle(original,normalized.operations,anchors,editor.schema)).toEqual(live)
})
it('controller keeps readonly and protected source tables unchanged',()=>{
 const {editor,anchors}=editorFixture(),before=editor.getJSON();editor.setEditable(false)
 expect(applyDocxTableStyle(editor,{style:{kind:'none'}},anchors)).toBe(false);expect(editor.getJSON()).toEqual(before)
 editor.setEditable(true);anchors[0].tableStyleEditable=false
 expect(applyDocxTableStyle(editor,{style:{kind:'preset',id:'grid'}},anchors)).toBe(false);expect(editor.getJSON()).toEqual(before)
})
import {createDocxTableStyleControls} from './docx-table-style-controls'
it('source gallery exposes fixed presets, source document styles and all look toggles, refreshing on transactions and disposing listeners',()=>{
 const {editor,anchors}=editorFixture(),controls=createDocxTableStyleControls({editor,anchors,onError:error=>{throw error}})
 document.body.append(controls.element)
 expect(controls.element.querySelectorAll('[data-table-style]')).toHaveLength(7)
 expect(controls.element.querySelectorAll('[data-table-look]')).toHaveLength(6)
 ;(controls.element.querySelector('[data-table-style="blue-banded"]') as HTMLButtonElement).click()
 expect(editor.state.doc.child(0).child(0).child(0).attrs.fill).toBe('BDD7EE')
 ;(controls.element.querySelector('[data-table-look="lastRow"]') as HTMLButtonElement).click()
 expect(controls.element.querySelector('[data-table-look="lastRow"]')!.getAttribute('aria-pressed')).toBe('true')
 ;(controls.element.querySelector('[data-table-style="document:Custom"]') as HTMLButtonElement).click()
 expect(editor.state.doc.child(0).attrs.tblStyleId).toBe('Custom')
 expect(controls.element.querySelector('[data-table-style="document:Custom"]')!.getAttribute('aria-pressed')).toBe('true')
 editor.setEditable(false);controls.refresh()
 expect(Array.from(controls.element.querySelectorAll('button')).every(b=>b.disabled)).toBe(true)
 controls.dispose();expect(controls.element.isConnected).toBe(false)
})
