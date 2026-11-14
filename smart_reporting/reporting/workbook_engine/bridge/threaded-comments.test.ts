import {expect,it} from 'vitest'
import * as engine from '../packages/xlsx-engine/src/index'
import {applyWorkbookOperations} from './operations'
import JSZip from 'jszip'
const root={row:3,column:3,id:'{11111111-1111-4111-8111-111111111111}',personId:'{22222222-2222-4222-8222-222222222222}',author:'scope-user',dT:'2026-11-13T01:02:03.00',text:'根帖<&',done:false,replies:[]}
it('writes real threaded parts and reads replies resolve reopen while retaining legacy VML',async()=>{
 expect(typeof (engine as any).readSheetThreads).toBe('function')
 const bytes=await engine.applySheetNotes(await engine.createBlankWorkbook('Report'),'Report',[{row:0,column:0,author:'旧作者',text:'原批注'}])
 const before=await JSZip.loadAsync(bytes), source=await engine.createBufferEntrySource(bytes)
 const originalVml=await before.file('xl/drawings/vmlDrawing1.vml')!.async('text')
 const state=await (engine as any).readSheetThreads(source,'xl/worksheets/sheet1.xml')
 const after=await applyWorkbookOperations(bytes,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:state.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:null,thread:root}]}])
 const model=await engine.readWorkbook(after), thread=(model.sheets[0] as any).threads.threads[0]
 expect(thread).toEqual(root)
 const zip=await JSZip.loadAsync(after)
 expect(await zip.file('xl/drawings/vmlDrawing1.vml')!.async('text')).toContain(originalVml.slice(originalVml.indexOf('<v:shape '),originalVml.lastIndexOf('</xml>')))
 expect(await zip.file('xl/threadedComments/threadedComment1.xml')!.async('text')).toContain('根帖&lt;&amp;')
 expect(await zip.file('xl/persons/person.xml')!.async('text')).toContain('scope-user')
 for(const done of [true,false]){
  const next={...thread,done,replies:[{id:'{33333333-3333-4333-8333-333333333333}',personId:root.personId,author:root.author,dT:root.dT,text:'回复'}]}
  const output=await applyWorkbookOperations(after,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:(model.sheets[0] as any).threads.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:root.id,thread:next}]}])
  expect((await engine.readWorkbook(output)).sheets[0]!.threads!.threads[0]).toEqual(next)
 }
 await expect(applyWorkbookOperations(after,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:'0'.repeat(64),changes:[]}])).rejects.toThrow(/身份|变化/)
})
it('rejects malformed parent identities, changed historical authors and duplicate ids',async()=>{
 const bytes=await engine.createBlankWorkbook('Report')
 const state=await engine.readSheetThreads(await engine.createBufferEntrySource(bytes),'xl/worksheets/sheet1.xml')
 const write=(data:Uint8Array,sourceIdentity:string,thread:any)=>applyWorkbookOperations(data,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity,changes:[{row:3,column:3,expectedThreadId:data===bytes?null:root.id,thread}]}])
 const saved=await write(bytes,state.sourceIdentity,root)
 const current=(await engine.readWorkbook(saved)).sheets[0]!.threads!
 await expect(write(saved,current.sourceIdentity,{...root,author:'伪造作者'})).rejects.toThrow(/历史/)
 await expect(write(saved,current.sourceIdentity,{...root,replies:[{...root,row:undefined,column:undefined,done:undefined,replies:undefined}]})).rejects.toThrow()
 const zip=await JSZip.loadAsync(saved)
 const name='xl/threadedComments/threadedComment1.xml'
 zip.file(name,(await zip.file(name)!.async('text')).replace('</ThreadedComments>',`<threadedComment ref="D4" dT="${root.dT}" personId="${root.personId}" id="{33333333-3333-4333-8333-333333333333}" parentId="{44444444-4444-4444-8444-444444444444}"><text>孤儿回复</text></threadedComment></ThreadedComments>`))
 const malformed=await zip.generateAsync({type:'uint8array'})
 expect((await engine.readWorkbook(malformed)).sheets[0]!.threads!.readOnlyReason).toMatch(/父身份/)
 await expect(write(malformed,(await engine.readWorkbook(malformed)).sheets[0]!.threads!.sourceIdentity,root)).rejects.toThrow(/父身份/)
})
it('deleting the last thread preserves shared persons and unrelated legacy notes',async()=>{
 const bytes=await engine.applySheetNotes(await engine.createBlankWorkbook('Report'),'Report',[{row:0,column:0,author:'保留',text:'旧批注'}])
 const state=await engine.readSheetThreads(await engine.createBufferEntrySource(bytes),'xl/worksheets/sheet1.xml')
 const saved=await applyWorkbookOperations(bytes,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:state.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:null,thread:root}]}])
 const current=(await engine.readWorkbook(saved)).sheets[0]!.threads!
 const deleted=await applyWorkbookOperations(saved,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:current.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:root.id,thread:null}]}])
 const model=await engine.readWorkbook(deleted), zip=await JSZip.loadAsync(deleted)
 expect(model.sheets[0]!.threads!.threads).toEqual([])
 expect(model.sheets[0]!.notes!.notes).toEqual([{row:0,column:0,author:'保留',text:'旧批注'}])
 expect(zip.file('xl/persons/person.xml')).not.toBeNull()
 expect(zip.file('xl/threadedComments/threadedComment1.xml')).toBeNull()
})
it('preserves legacy picture bytes and allows their removal alongside modern threads',async()=>{
 const {readNotePictures,applyNotePictureOperation}=await import('../packages/xlsx-engine/src/note-pictures')
 const {sha256Hex}=await import('../packages/xlsx-engine/src/sha256')
 const png=Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=','base64'))
 const blank=await engine.applySheetNotes(await engine.createBlankWorkbook('Report'),'Report',[{row:0,column:0,author:'保留作者',text:'保留图片文字'}])
 const bytes=await applyNotePictureOperation(blank,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:(await readNotePictures(blank)).sheets[0]!.sourceIdentity,picture:{mediaType:'image/png',bytesBase64:Buffer.from(png).toString('base64'),size:png.length,sha256:sha256Hex(png),widthPx:1,heightPx:1,name:'保留.png'}}),before=await readNotePictures(bytes)
 const state=(await engine.readWorkbook(bytes)).sheets[0]!.threads!
 const saved=await applyWorkbookOperations(bytes,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:state.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:null,thread:root}]}])
 const pictures=await readNotePictures(saved)
 expect(pictures.issues).toEqual([])
 expect(pictures.pictures.map(p=>[p.author,p.text,p.sha256])).toEqual(before.pictures.map(p=>[p.author,p.text,p.sha256]))
 const removed=await applyNotePictureOperation(saved,{kind:'setNotePicture',sheetName:'Report',row:0,column:0,sourceIdentity:pictures.sheets[0]!.sourceIdentity,picture:null})
 expect((await engine.readWorkbook(removed)).sheets[0]!.threads!.threads[0]).toEqual(root)
 await expect(applyNotePictureOperation(saved,{kind:'setNotePicture',sheetName:'Report',row:3,column:3,sourceIdentity:pictures.sheets[0]!.sourceIdentity,picture:null})).rejects.toThrow(/线程批注/)
})
it('rejects structural changes and foreign namespaces without damaging existing bytes',async()=>{
 const bytes=await engine.createBlankWorkbook('Report'),state=(await engine.readWorkbook(bytes)).sheets[0]!.threads!
 const saved=await applyWorkbookOperations(bytes,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:state.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:null,thread:root}]}])
 for(const operation of [{kind:'applyRowColumnOps',sheetName:'Report',ops:[]},{kind:'applyCellShift',sheetName:'Report',range:'A1:B2',shift:'right'},{kind:'sortRange',sheetName:'Report',spec:{}}])await expect(applyWorkbookOperations(saved,[operation])).rejects.toThrow(/线程批注/)
 const zip=await JSZip.loadAsync(saved),path='xl/threadedComments/threadedComment1.xml'
 const original=await zip.file(path)!.async('text')
 zip.file(path,original.replace('<threadedComment ref=', '<threadedComment done="true" ref='))
 expect((await engine.readWorkbook(await zip.generateAsync({type:'uint8array'}))).sheets[0]!.threads!.threads[0]!.done).toBe(true)
 zip.file(path,original.replace('<text>根帖&lt;&amp;</text>', '<text><![CDATA[保留]]></text>'))
 expect((await engine.readWorkbook(await zip.generateAsync({type:'uint8array'}))).sheets[0]!.threads!.readOnlyReason).toMatch(/保真/)
 zip.file(path,original)
 zip.file(path,(await zip.file(path)!.async('text')).replace('http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments','urn:foreign'))
 expect((await engine.readWorkbook(await zip.generateAsync({type:'uint8array'}))).sheets[0]!.threads!.readOnlyReason).toMatch(/命名空间/)
})
it('rejects a shared person identity with a conflicting display name',async()=>{
 const bytes=await engine.createBlankWorkbook('Report'),state=(await engine.readWorkbook(bytes)).sheets[0]!.threads!
 const saved=await applyWorkbookOperations(bytes,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:state.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:null,thread:root}]}])
 const next=(await engine.readWorkbook(saved)).sheets[0]!.threads!
 await expect(applyWorkbookOperations(saved,[{kind:'patchThreadedComments',sheetName:'Report',sourceIdentity:next.sourceIdentity,changes:[{row:3,column:3,expectedThreadId:root.id,thread:null},{row:4,column:4,expectedThreadId:null,thread:{...root,id:'{55555555-5555-4555-8555-555555555555}',row:4,column:4,author:'冒名'}}]}])).rejects.toThrow(/人物名称冲突/)
})
