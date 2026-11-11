import {describe,it,expect} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {docxOperations,replayDocxOperations,type DocxAnchor,type DocxPmNode} from './docx-operations'
import {projectDocxTextRevisions} from './docx-text-revisions'
const schema=new Schema({nodes:{doc:{content:'docParagraph+'},docParagraph:{content:'text*',attrs:{docxIndex:{default:0},nativeTextRevisionOperations:{default:null}}},text:{}},marks:{ins:{attrs:{author:{default:'甲'},date:{default:null},move:{default:null}}}}})
const anchor:DocxAnchor={docxIndex:0,blockId:'block',expectedObjectSha256:'snapshot',editable:false,reviewTargets:[{blockId:'block',expectedObjectSha256:'snapshot',revisionId:'wrapper',originalRevisionId:'1',type:'insertion',author:'甲',date:null,sourceRange:{from:1,to:3,text:'新增'}}]}
const baseline=schema.nodeFromJSON({type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'前'},{type:'text',text:'新增',marks:[{type:'ins'}]},{type:'text',text:'后'}]}]}).toJSON() as DocxPmNode
const op={kind:'resolveTextRevision',blockId:'block',expectedObjectSha256:'snapshot',revisionId:'wrapper',action:'reject'}
describe('正文修订接入普通收集与草稿恢复',()=>{
 it('round trips exact review intent without granting ordinary paragraph editing',()=>{
  const current={...baseline,content:[projectDocxTextRevisions(baseline.content![0],anchor,[op],schema)]}
  expect(docxOperations(baseline,current,[anchor],undefined,schema)).toEqual([op])
  expect(replayDocxOperations(baseline,[op],[anchor],undefined,schema)).toEqual(current)
  expect(docxOperations(baseline,replayDocxOperations(baseline,[op],[anchor],undefined,schema),[anchor],undefined,schema)).toEqual([op])
  const forged=structuredClone(current);forged.content[0].content![0].text='篡改'
  expect(()=>docxOperations(baseline,forged,[anchor],undefined,schema)).toThrow()
  expect(()=>replayDocxOperations(baseline,[op,{kind:'replaceParagraph',blockId:'block',expectedObjectSha256:'snapshot',text:'篡改'}],[anchor],undefined,schema)).toThrow()
 })
 it('rejects unknown review identities before draft mutation',()=>{
  const snapshot=structuredClone(baseline)
  expect(()=>replayDocxOperations(baseline,[{...op,revisionId:'foreign'}],[anchor],undefined,schema)).toThrow()
  expect(baseline).toEqual(snapshot)
 })
})
