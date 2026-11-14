import {describe,it,expect} from 'vitest'
import {inspectDocxInk,validateDocxInkOperations} from '../../../reporting/doc_engine/bridge/docx-ink'
import {annotationsFromParsed,buildInkImages,decodeInkPayload} from './docx-ink'
describe('fixed-source editable ink',()=>{
 it('round trips vectors with mapped paragraph anchors',()=>{
 const anns=annotationsFromParsed([{anchorIndex:5,widthPx:20,heightPx:10,offsetXPx:0,offsetYPx:0,dataUrl:null,payload:'{"v":1,"tool":"highlighter","color":"FFFF00","width":6,"points":[[1,2],[10,4]]}'}])
 const images=buildInkImages(anns,new Map([[5,2]]),()=>({base64:'iVBORw0KGgo=',widthPx:20,heightPx:10,offsetXPx:0,offsetYPx:0}))
 expect(images[0].blockIndex).toBe(2);expect(decodeInkPayload(images[0].payload!)?.tool).toBe('highlighter')
 expect(buildInkImages(anns,new Map())).toEqual([])
 })
 it('checks source binding and permits explicit clearing only',()=>{
 const m=inspectDocxInk([],false)
 expect(validateDocxInkOperations([],m,new Map())).toBeUndefined()
 expect(validateDocxInkOperations([{kind:'setInk',expectedInkSha256:m.expectedInkSha256,inks:[]}],m,new Map())).toEqual([])
 expect(()=>validateDocxInkOperations([{kind:'setInk',expectedInkSha256:'stale',inks:[]}],m,new Map())).toThrow('anchor_invalid')
 })
 it('rejects corrupt raster, unmapped anchors and protected documents',()=>{
 const m=inspectDocxInk([],false),op={kind:'setInk',expectedInkSha256:m.expectedInkSha256,inks:[{anchorIndex:4,base64:'invalid',widthPx:2,heightPx:2,offsetXPx:0,offsetYPx:0}]}
 expect(()=>validateDocxInkOperations([op],m,new Map([[4,0]]))).toThrow()
 expect(()=>validateDocxInkOperations([{...op,inks:[]}],inspectDocxInk([],true),new Map())).toThrow('source_unsupported')
 })
})

import {parseDocx,saveDocx} from '../../../reporting/doc_engine/packages/docx-engine/src/index'
import {buildDocx,TINY_PNG_BASE64} from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import {assertDocxInkWritten} from '../../../reporting/doc_engine/bridge/docx-ink'
import {createDocxInkController} from './docx-ink-controller'
it('writes source-format OOXML, reopens editable vectors and clears only ink',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:t>anchor</w:t></w:r></w:p>'})
 const doc=await parseDocx(bytes),model=inspectDocxInk(doc.inks,false)
 const payload=JSON.stringify({v:1,tool:'pen',color:'C00000',width:2,points:[[2,3],[12,4]]})
 const images=validateDocxInkOperations([{kind:'setInk',expectedInkSha256:model.expectedInkSha256,inks:[{anchorIndex:0,base64:TINY_PNG_BASE64,widthPx:20,heightPx:10,offsetXPx:2,offsetYPx:3,payload}]}],model,new Map([[0,0]]))!
 const saved=await saveDocx(doc,[{kind:'original',docxIndex:0}],{inks:images})
 const reopened=await parseDocx(saved)
 assertDocxInkWritten(reopened.inks,images)
 expect(annotationsFromParsed(reopened.inks)[0].stroke?.points).toEqual([{x:2,y:3},{x:12,y:4}])
 const cleared=await parseDocx(await saveDocx(reopened,[{kind:'original',docxIndex:0}],{inks:[]}))
 expect(cleared.inks).toEqual([]);expect(JSON.stringify(cleared.blocks[0])).toContain('anchor')
})
it('controller reads draft/history journal and keeps eraser identifiers stable',()=>{
 const model=inspectDocxInk([{anchorIndex:0,widthPx:1,heightPx:1,offsetXPx:0,offsetYPx:0,dataUrl:`data:image/png;base64,${TINY_PNG_BASE64}`,payload:null}],false)
 let ops:any[]=[]
 const ctrl=createDocxInkController({editor:()=>({isEditable:true}) as any,model:()=>model,operations:()=>ops,commit:op=>{ops=[op];return true},canEdit:()=>true})
 const first=ctrl.annotations()[0].id
 expect(ctrl.annotations()[0].id).toBe(first)
 expect(ctrl.remove([first])).toBe(true);expect(ctrl.annotations()).toEqual([])
 ops=[];expect(ctrl.annotations()).toHaveLength(1)
})
it('verifies multiple paragraph anchors independently of stroke creation order',async()=>{
 const doc=await parseDocx(await buildDocx({bodyXml:'<w:p><w:r><w:t>one</w:t></w:r></w:p><w:p><w:r><w:t>two</w:t></w:r></w:p>'}))
 const images=[1,0].map(blockIndex=>({blockIndex,base64:TINY_PNG_BASE64,widthPx:12,heightPx:6,offsetXPx:blockIndex+1,offsetYPx:-3,payload:JSON.stringify({v:1,tool:'highlighter',color:'FFFF00',width:6,points:[[1,2],[3,4]]})}))
 const reopened=await parseDocx(await saveDocx(doc,[{kind:'original',docxIndex:0},{kind:'original',docxIndex:1}],{inks:images}))
 assertDocxInkWritten(reopened.inks,images)
 expect(reopened.inks.map(i=>[i.anchorIndex,i.offsetXPx])).toEqual([[0,1],[1,2]])
})
