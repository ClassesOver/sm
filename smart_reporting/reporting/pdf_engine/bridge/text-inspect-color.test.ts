import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,rgb} from 'pdf-lib'
import {inspectTextObjects} from '../src/main/text-edit'

test('text inspection returns PDFium fill color without changing text or bounds',async()=>{
 const document=await PDFDocument.create(),page=document.addPage([300,400])
 page.drawText('Color target',{x:30,y:350,size:12,color:rgb(20/255,40/255,60/255)})
 const [target]=(await inspectTextObjects(await document.save()))[0]!
 assert.equal(target!.text,'Color target')
 assert.deepEqual(target!.fillColor,[20,40,60])
 assert.deepEqual(target!.rect.map(value=>Number.isFinite(value)),[true,true,true,true])
})
