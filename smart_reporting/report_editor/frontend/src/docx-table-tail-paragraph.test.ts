import {describe,it,expect} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {tableTailParagraphOperation,replayTableTailParagraph} from './docx-table-tail-paragraph'
import {validateTableTailParagraph} from '../../../reporting/doc_engine/bridge/docx-table-tail-paragraph'
const schema=new Schema({nodes:{doc:{content:'docParagraph*'},text:{},docParagraph:{content:'text*',attrs:{docxIndex:{default:null},align:{default:null},styleId:{default:null}}}}})
const table={type:'docTable',attrs:{docxIndex:2,align:'right',styleId:'TableGrid'}}
const anchor={docxIndex:2,blockId:'tbl2',expectedObjectSha256:'a'.repeat(64),editable:false}
const fresh=(text='')=>({type:'docParagraph',attrs:{docxIndex:null},...(text?{content:[{type:'text',text}]}:{})})
describe('paragraphs after original table',()=>{
 it('anchors consecutive empty and typed paragraphs to table rather than earlier text',()=>{
  const before=[{type:'docParagraph',attrs:{docxIndex:1}},table]
  const after=[...before,fresh(),fresh('tail')]
  for(const index of [2,3])expect(tableTailParagraphOperation(before,after,index,[anchor])).toMatchObject({kind:'insertParagraph',blockId:'tbl2',position:'after',text:index===2?'':'tail'})
 })
 it('replays in order using paragraph defaults and roundtrips diff',()=>{
  const content=[table],counts=new Map<string,number>()
  for(const text of ['', 'tail'])replayTableTailParagraph(content,table,{kind:'insertParagraph',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,position:'after',text},anchor,schema,counts)
  expect(content.slice(1).map(n=>n.attrs)).toEqual([{docxIndex:null,align:null,styleId:null},{docxIndex:null,align:null,styleId:null}])
  expect(tableTailParagraphOperation([table],content,2,[anchor])).toMatchObject({text:'tail'})
  expect(content[0]).toBe(table)
 })
 it('rejects table modification identity, rich text, protection and unexpected attrs',()=>{
  expect(()=>tableTailParagraphOperation([table],[table,{...fresh('x'),content:[{type:'text',text:'x',marks:[{type:'bold'}]}]}],1,[anchor])).toThrow()
  expect(()=>tableTailParagraphOperation([table],[table,{...fresh('x'),attrs:{docxIndex:null,spaceAfter:12}}],1,[anchor],schema)).toThrow()
  expect(()=>tableTailParagraphOperation([table],[table,{...fresh('x'),attrs:{docxIndex:null,indentRight:24}}],1,[anchor],schema)).toThrow()
  const op={kind:'insertParagraph',blockId:'tbl2',expectedObjectSha256:anchor.expectedObjectSha256,position:'after',text:'尾段'}
  const block={type:'table',originalXml:'<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>'}
  expect(validateTableTailParagraph(op,block,'tbl2',anchor.expectedObjectSha256,false)).toBe('尾段')
  expect(()=>validateTableTailParagraph(op,block,'tbl2',anchor.expectedObjectSha256,true)).toThrow()
  expect(()=>validateTableTailParagraph({...op,position:'before'},block,'tbl2',anchor.expectedObjectSha256,false)).toThrow()
  expect(()=>validateTableTailParagraph({...op,expectedObjectSha256:'bad'},block,'tbl2',anchor.expectedObjectSha256,false)).toThrow()
  expect(()=>validateTableTailParagraph({...op,pageBreakBefore:true},block,'tbl2',anchor.expectedObjectSha256,false)).toThrow()
 })
})
