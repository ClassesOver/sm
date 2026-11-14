import {describe,expect,it} from 'vitest'
import {Schema} from '@tiptap/pm/model'
import {assertDocxTrackedChangesBatch,normalizeDocxTrackedChanges,replayDocxTrackedChanges} from './docx-tracked-changes'
import type {DocxAnchor,DocxPmNode} from './docx-operations'

const schema=new Schema({nodes:{doc:{content:'docParagraph+'},docParagraph:{content:'text*',attrs:{docxIndex:{default:0}}},text:{group:'inline',marks:'_'}},marks:{bold:{},ins:{attrs:{author:{default:''},date:{default:null}}},del:{attrs:{author:{default:''},date:{default:null}}}}})
const anchor:DocxAnchor={docxIndex:0,blockId:'body',expectedObjectSha256:'source-hash',editable:true}
const paragraph=(content:DocxPmNode['content']):DocxPmNode=>({type:'docParagraph',attrs:{docxIndex:0},content})
const root=(node:DocxPmNode):DocxPmNode=>({type:'doc',content:[node]})

describe('DOCX tracked text changes',()=>{
 it('collects one UTF-16 replacement without client author or date and restores the ordinary diff baseline',()=>{
  const baseline=root(paragraph([{type:'text',text:'前😀旧后'}])),live=root(paragraph([
   {type:'text',text:'前😀'},{type:'text',text:'旧',marks:[{type:'del',attrs:{author:'untrusted',date:'forged'}}]},
   {type:'text',text:'新',marks:[{type:'ins',attrs:{author:'untrusted',date:'forged'}}]},{type:'text',text:'后'},
  ]))
  const normalized=normalizeDocxTrackedChanges(baseline,live,[anchor])
  expect(normalized.operations).toEqual([{kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:3,to:4,text:'新'}])
  expect(normalized.current).toEqual(baseline)
 })
 it('replays only source-bound single edits with the current authenticated user identity',()=>{
  const baseline=root(paragraph([{type:'text',text:'before'}])),operation={kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:1,to:3,text:'XX'}
  const replayed=replayDocxTrackedChanges(baseline,[operation],[anchor],schema,'user-17','2026-11-13T02:03:04Z')
  expect(replayed.content![0].content).toEqual([
   {type:'text',text:'b'},
   {type:'text',text:'ef',marks:[{type:'del',attrs:{author:'user-17',date:'2026-11-13T02:03:04Z'}}]},
   {type:'text',text:'XX',marks:[{type:'ins',attrs:{author:'user-17',date:'2026-11-13T02:03:04Z'}}]},
   {type:'text',text:'ore'},
  ])
 })
 it('records a pure deletion without inventing an insertion mark',()=>{
  const baseline=root(paragraph([{type:'text',text:'abc'}])),live=root(paragraph([
   {type:'text',text:'a'},{type:'text',text:'b',marks:[{type:'del'}]},{type:'text',text:'c'},
  ]))
  const normalized=normalizeDocxTrackedChanges(baseline,live,[anchor])
  expect(normalized.operations).toEqual([{kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:1,to:2,text:''}])
  expect(replayDocxTrackedChanges(baseline,normalized.operations,[anchor],schema,'user-17',null).content![0].content).toContainEqual({type:'text',text:'b',marks:[{type:'del',attrs:{author:'user-17',date:null}}]})
 })
 it('collects and restores disjoint changes in one paragraph against the same original source',()=>{
  const baseline=root(paragraph([{type:'text',text:'前😀甲中乙尾',marks:[{type:'bold'}]}]))
  const live=root(paragraph([
   {type:'text',text:'前😀',marks:[{type:'bold'}]},
   {type:'text',text:'甲',marks:[{type:'bold'},{type:'del',attrs:{author:'untrusted'}}]},
   {type:'text',text:'新😀',marks:[{type:'bold'},{type:'ins',attrs:{author:'untrusted'}}]},
   {type:'text',text:'中',marks:[{type:'bold'}]},
   {type:'text',text:'乙',marks:[{type:'bold'},{type:'del'}]},
   {type:'text',text:'另',marks:[{type:'bold'},{type:'ins'}]},
   {type:'text',text:'尾',marks:[{type:'bold'}]},
  ]))
  const normalized=normalizeDocxTrackedChanges(baseline,live,[anchor])
  expect(normalized.current).toEqual(baseline)
  expect(normalized.operations).toEqual([
   {kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:3,to:4,text:'新😀'},
   {kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:5,to:6,text:'另'},
  ])
  expect(()=>assertDocxTrackedChangesBatch(normalized.operations)).not.toThrow()
  const restored=replayDocxTrackedChanges(baseline,normalized.operations,[anchor],schema,'user-17',null)
  expect(normalizeDocxTrackedChanges(baseline,restored,[anchor]).operations).toEqual(normalized.operations)
  expect(restored.content![0].content!.filter(node=>!node.marks?.some(mark=>mark.type==='del')).map(node=>node.text).join('')).toBe('前😀新😀中另尾')
  expect(restored.content![0].content!.filter(node=>!node.marks?.some(mark=>mark.type==='ins')).map(node=>node.text).join('')).toBe('前😀甲中乙尾')
  for(const node of restored.content![0].content!)expect(node.marks).toContainEqual({type:'bold'})
 })
 it('rejects overlapping source edits and forged operation metadata',()=>{
  const baseline=root(paragraph([{type:'text',text:'abcdef'}])),anchors=[anchor]
  const overlap=[{kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:1,to:3,text:'x'},{kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:2,to:4,text:'y'}]
  expect(()=>replayDocxTrackedChanges(baseline,overlap,anchors,schema,'user-17','2026-11-13T02:03:04Z')).toThrow()
  expect(()=>replayDocxTrackedChanges(baseline,[{...overlap[0],author:'forged'}],anchors,schema,'user-17','2026-11-13T02:03:04Z')).toThrow()
 })
 it('cancels newly inserted text deleted while tracking and combines adjacent revision runs',()=>{
  const baseline=root(paragraph([{type:'text',text:'abc'}]))
  const live=root(paragraph([{type:'text',text:'a'},
   {type:'text',text:'临时😀',marks:[{type:'ins'},{type:'del'}]},
   {type:'text',text:'b',marks:[{type:'del'}]},
   {type:'text',text:'新',marks:[{type:'ins'}]},
   {type:'text',text:'😀',marks:[{type:'ins'}]},
   {type:'text',text:'c'},
  ]))
  expect(normalizeDocxTrackedChanges(baseline,live,[anchor]).operations).toEqual([
   {kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:1,to:2,text:'新😀'},
  ])
  const canceled=root(paragraph([{type:'text',text:'a'},{type:'text',text:'临时',marks:[{type:'ins'},{type:'del'}]},{type:'text',text:'bc'}]))
  expect(normalizeDocxTrackedChanges(baseline,canceled,[anchor])).toEqual({baseline,current:baseline,operations:[]})
 })
 it('keeps the writer contract for ordered separated ranges and unchanged source text',()=>{
  const baseline=root(paragraph([{type:'text',text:'abcdef'}])),first={kind:'recordTextRevision',blockId:'body',expectedObjectSha256:'source-hash',from:1,to:2,text:'B'}
  for(const second of [{...first},{...first,from:2,to:3},{...first,from:4,to:5,expectedObjectSha256:'foreign'}]){
   expect(()=>assertDocxTrackedChangesBatch([first,second])).toThrow()
   expect(()=>replayDocxTrackedChanges(baseline,[first,second],[anchor],schema,'user-17',null)).toThrow()
  }
  expect(()=>assertDocxTrackedChangesBatch([{...first,from:4,to:5},first])).toThrow()
  const changed=root(paragraph([{type:'text',text:'a!'},{type:'text',text:'b',marks:[{type:'del'}]},{type:'text',text:'cdef'}]))
  expect(()=>normalizeDocxTrackedChanges(baseline,changed,[anchor])).toThrow()
 })
})
