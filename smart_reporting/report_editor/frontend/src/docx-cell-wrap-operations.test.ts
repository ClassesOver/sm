import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {docxOperations,replayDocxOperations,type DocxPmNode} from './docx-operations'
import {projectDocxCellWrap} from './docx-table-cell-wrap'
import {projectDocxTableAlignment} from './docx-table-alignment'

const schema=new Schema({nodes:{doc:{content:'docTable+'},text:{},docParagraph:{},docTable:{content:'row+',tableRole:'table',attrs:{docxIndex:{default:0},nativeTableCellWrap:{default:null},nativeTableAlignment:{default:null}}},row:{content:'cell+',tableRole:'row'},cell:{content:'docParagraph',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1},noWrap:{default:null}}}}})
const source:DocxPmNode=schema.node('doc',null,schema.node('docTable',null,schema.node('row',null,schema.node('cell',null,schema.node('docParagraph'))))).toJSON()
const cell={top:0,left:0,bottom:1,right:1,rawPresent:false,hasPhysicalNoWrap:false,raw:null,noWrap:false,resetNoWrap:false as const}
const anchor={docxIndex:0,blockId:'table',expectedObjectSha256:'sha',editable:false,tableCellWrapEditable:true,tableCellWrapSource:{cells:[cell]}}
const step={top:0,left:0,bottom:1,right:1,wrap:false}

it('collects and replays exact wrap intent while rejecting payload and hash changes',()=>{
 const edited={...source,content:[projectDocxCellWrap(source.content![0],anchor,[step],schema)]}
 const ops=docxOperations(source,edited,[anchor],undefined,schema)
 expect(ops).toEqual([{kind:'setTableCellWrap',blockId:'table',expectedObjectSha256:'sha',steps:[step]}])
 expect(replayDocxOperations(source,ops,[anchor],undefined,schema)).toEqual(edited)
 for(const forged of [{...ops[0],xml:'fake'},{...ops[0],expectedObjectSha256:'foreign'}])expect(()=>replayDocxOperations(source,[forged],[anchor],undefined,schema)).toThrow()
 expect(()=>replayDocxOperations(source,[...ops,...ops],[anchor],undefined,schema)).toThrow(/同表/)
 const malicious=structuredClone(edited);malicious.content![0].content![0].content![0].attrs!.colspan=2
 expect(()=>docxOperations(source,malicious,[anchor],undefined,schema)).toThrow()
})

it('rejects the new pending wrap when another table projection is requested',()=>{
 const edited=projectDocxCellWrap(source.content![0],anchor,[step],schema)
 expect(()=>projectDocxTableAlignment(edited,{...anchor,tableAlignmentEditable:true,tableAlignmentSource:{alignment:null,raw:null,rawIndent:null,rawWidth:null,bidiVisual:false,positioning:'inline',cells:[cell]}},'right',schema)).toThrow(/先保存/)
})
