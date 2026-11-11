import {expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {docxOperations,replayDocxOperations,type DocxPmNode} from './docx-operations'
import {projectDocxTableAltText} from './docx-table-alt-text'
const schema=new Schema({nodes:{doc:{content:'docTable+'},text:{},docParagraph:{},docTable:{content:'row+',tableRole:'table',attrs:{docxIndex:{default:0},tblCaption:{default:null},tblDescription:{default:null},nativeTableAltText:{default:null}}},row:{content:'cell+',tableRole:'row'},cell:{content:'docParagraph',tableRole:'cell',attrs:{colspan:{default:1},rowspan:{default:1}}}}})
const source:DocxPmNode=schema.node('doc',null,schema.node('docTable',null,schema.node('row',null,schema.node('cell',null,schema.node('docParagraph'))))).toJSON()
const anchor={docxIndex:0,blockId:'table',expectedObjectSha256:'sha',editable:false,tableAltTextEditable:true,tableAltTextSource:{title:'',description:'',rawTitle:null,rawDescription:null}}
it('collects final pair and replays exactly without accepting extra wire or altered file identity',()=>{
 const edited={...source,content:[projectDocxTableAltText(source.content![0],anchor,{title:'中文',description:'首行\n次行 &#10;'},schema)]}
 const ops=docxOperations(source,edited,[anchor],undefined,schema)
 expect(ops).toEqual([{kind:'setTableAltText',blockId:'table',expectedObjectSha256:'sha',title:'中文',description:'首行\n次行 &#10;'}])
 expect(replayDocxOperations(source,ops,[anchor],undefined,schema)).toEqual(edited)
 for(const op of [{...ops[0],raw:'fake'},{...ops[0],expectedObjectSha256:'foreign'}])expect(()=>replayDocxOperations(source,[op],[anchor],undefined,schema)).toThrow()
 expect(()=>replayDocxOperations(source,[...ops,...ops],[anchor],undefined,schema)).toThrow(/同表/)
})
it('rejects simultaneous cell geometry changes and malformed final intent',()=>{
 const edited={...source,content:[projectDocxTableAltText(source.content![0],anchor,{title:'a',description:'b'},schema)]}
 const forged=structuredClone(edited);forged.content![0].content![0].content![0].attrs!.colspan=2
 expect(()=>docxOperations(source,forged,[anchor],undefined,schema)).toThrow()
 const invalid=structuredClone(edited);invalid.content![0].attrs!.nativeTableAltText={title:'a',description:'b',xml:'fake'}
 expect(()=>docxOperations(source,invalid,[anchor],undefined,schema)).toThrow()
})
