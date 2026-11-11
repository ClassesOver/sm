import {describe,it,expect} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {getDocxTextRevisionTargets,projectDocxTextRevisions,normalizeDocxTextRevisions,replayDocxTextRevisions} from './docx-text-revisions'
import type {DocxTextRevisionAnchor,DocxTextRevisionOperation} from './docx-text-revisions-core'
import type {DocxPmNode} from './docx-operations'
const schema=new Schema({nodes:{doc:{content:'docParagraph+'},docParagraph:{content:'inline*',attrs:{docxIndex:{default:0},nativeTextRevisionOperations:{default:null}}},text:{group:'inline'},hardBreak:{inline:true,group:'inline',attrs:{pageBreak:{default:false},colBreak:{default:false},wrapBreak:{default:false}}}},marks:{bold:{},italic:{},ins:{attrs:{author:{default:'A'},date:{default:null},id:{default:'7'},move:{default:null}}},del:{attrs:{author:{default:'A'},date:{default:null},id:{default:'7'},move:{default:null}}}}})
const target=(revisionId:string,type:'insertion'|'deletion',from:number,text:string)=>({blockId:'b',expectedObjectSha256:'sha',revisionId,originalRevisionId:'7',type,author:'A',date:null,sourceRange:{from,to:from+text.length,text}})
const anchor:DocxTextRevisionAnchor={docxIndex:0,blockId:'b',expectedObjectSha256:'sha',reviewTargets:[target('one','insertion',1,'😀同'),target('two','insertion',4,'同'),target('three','deletion',5,'删\t\n')],revisionReadOnlyReason:null}
const p=()=>schema.nodeFromJSON({type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'前'},{type:'text',text:'😀',marks:[{type:'ins'},{type:'bold'}]},{type:'text',text:'同同',marks:[{type:'ins'}]},{type:'text',text:'删\t',marks:[{type:'del'},{type:'italic'}]},{type:'hardBreak',marks:[{type:'del'}]},{type:'text',text:'尾'}]}).toJSON() as DocxPmNode
const doc=()=>({type:'doc',content:[p()]})
const op=(revisionId:string,action:'accept'|'reject'):DocxTextRevisionOperation=>({kind:'resolveTextRevision',blockId:'b',expectedObjectSha256:'sha',revisionId,action})
const text=(n:DocxPmNode)=>(n.content??[]).map(c=>c.text??'\n').join('')
describe('原XML范围绑定的正文修订投影',()=>{
 it('maps merged adjacent marks, duplicate original ids, repeated text, multi-run emoji exactly',()=>{
  expect(getDocxTextRevisionTargets(p(),anchor).map(t=>[t.revisionId,t.from,t.to,t.text])).toEqual([['one',1,4,'😀同'],['two',4,5,'同'],['three',5,8,'删\t\n']])
  const accepted=projectDocxTextRevisions(p(),anchor,[op('one','accept')],schema)
  expect(text(accepted)).toBe('前😀同同删\t\n尾')
  expect(accepted.content!.filter(n=>n.marks?.some(m=>m.type==='ins')).map(n=>n.text).join('')).toBe('同')
  expect(accepted.content!.find(n=>n.text==='😀')?.marks).toContainEqual({type:'bold'})
  expect(text(projectDocxTextRevisions(p(),anchor,[op('one','reject')],schema))).toBe('前同删\t\n尾')
  expect(text(projectDocxTextRevisions(p(),anchor,[op('three','accept')],schema))).toBe('前😀同同尾')
  const rejected=projectDocxTextRevisions(p(),anchor,[op('three','reject')],schema)
  expect(text(rejected)).toBe('前😀同同删\t\n尾');expect(rejected.content!.some(n=>n.marks?.some(m=>m.type==='del'))).toBe(false)
 })
 it('collects strict baseline plus decisions, and replays a snapshot batch',()=>{
  const operations=[op('one','reject'),op('three','reject')],projected=projectDocxTextRevisions(p(),anchor,operations,schema),live={type:'doc',content:[projected]}
  const normalized=normalizeDocxTextRevisions(doc(),live,[anchor],schema)
  expect(normalized.current).toEqual(doc());expect(normalized.operations).toEqual(operations)
  expect(replayDocxTextRevisions(doc(),operations,[anchor],schema)).toEqual(live)
  const forged=structuredClone(live);forged.content[0].content![0].text='伪造'
  expect(()=>normalizeDocxTextRevisions(doc(),forged,[anchor],schema)).toThrow()
  const attrs=structuredClone(live);attrs.content[0].attrs!.nativeOtherIntent={foo:1}
  expect(()=>normalizeDocxTextRevisions(doc(),attrs,[anchor],schema)).toThrow()
 })
 it('rejects stale, unknown, duplicate, conflicting, mixed and forged fields atomically',()=>{
  for(const operations of [[op('one','accept'),op('one','reject')],[op('one','accept'),op('missing','accept')],[{...op('one','accept'),expectedObjectSha256:'old'}],[{...op('one','accept'),xml:'x'}]])expect(()=>projectDocxTextRevisions(p(),anchor,operations as DocxTextRevisionOperation[],schema)).toThrow()
  for(const other of [{kind:'setSectionLayout',sectionId:'elsewhere'},{kind:'insertSectionBreak',afterBlockId:'other'}, {kind:'replaceParagraph',blockId:'b'},{kind:'patchParagraphRuns',blockId:'b'},{kind:'insertSectionBreak',afterBlockId:'b'}])expect(()=>replayDocxTextRevisions(doc(),[op('one','accept'),other],[anchor],schema)).toThrow()
  expect(()=>replayDocxTextRevisions(doc(),[op('one','accept'),{kind:'formatParagraph',blockId:'other'}],[anchor],schema)).not.toThrow()
 })
 it('refuses guessed ranges, unmarked payload, overlapping targets, half-surrogates and undeclared revisions',()=>{
  for(const targets of [[{...anchor.reviewTargets![0],sourceRange:{from:2,to:4,text:'\ude00同'}}],anchor.reviewTargets!.slice(1),[...anchor.reviewTargets!,anchor.reviewTargets![0]],anchor.reviewTargets!.map(t=>t.revisionId==='two'?{...t,sourceRange:{from:0,to:1,text:'前'}}:t),anchor.reviewTargets!.map(t=>({...t,sourceRange:undefined}))])expect(()=>getDocxTextRevisionTargets(p(),{...anchor,reviewTargets:targets} as DocxTextRevisionAnchor)).toThrow()
  expect(()=>getDocxTextRevisionTargets(p(),{...anchor,revisionReadOnlyReason:'protected'})).toThrow()
 })
 it('preserves empty paragraph identity when the final text revision is removed',()=>{
  const a={...anchor,reviewTargets:[target('last','insertion',0,'😀')]},source=schema.nodeFromJSON({type:'docParagraph',content:[{type:'text',text:'😀',marks:[{type:'ins'}]}]}).toJSON() as DocxPmNode
  const live=projectDocxTextRevisions(source,a,[op('last','reject')],schema)
  expect(live.type).toBe('docParagraph');expect(live.content??[]).toEqual([]);expect(live.attrs!.docxIndex).toBe(0)
  expect(normalizeDocxTextRevisions({type:'doc',content:[source]},{type:'doc',content:[live]},[a],schema).operations).toEqual([op('last','reject')])
 })
})
