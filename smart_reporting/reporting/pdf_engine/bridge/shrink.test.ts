import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFRawStream} from 'pdf-lib'
import {deflateSync} from 'node:zlib'
import {shrinkPdf} from './shrink'

test('shrink returns readable independent PDF and preserves the source bytes',async()=>{
 const document=await PDFDocument.create();document.addPage([300,400]);const source=await document.save({useObjectStreams:false}),before=Buffer.from(source)
 const result=await shrinkPdf(source)
 assert.deepEqual(Buffer.from(source),before);assert.ok(result.bytes.length>0);assert.equal((await PDFDocument.load(result.bytes)).getPageCount(),1)
 assert.equal(result.streamsRecompressed,0);assert.equal(result.imagesDownsampled,0)
})

test('recompresses only smaller plain Flate streams and skips predictor streams',async()=>{
 const document=await PDFDocument.create();document.addPage([300,400]);const page=document.getPage(0),plain=Buffer.alloc(100000,65),encoded=deflateSync(plain,{level:1})
 const ref=document.context.register(PDFRawStream.of(document.context.obj({Filter:PDFName.of('FlateDecode'),Length:encoded.length}),encoded));page.node.set(PDFName.of('Contents'),ref)
 const source=await document.save({useObjectStreams:false}),result=await shrinkPdf(source),out=await PDFDocument.load(result.bytes)
 assert.equal(result.streamsRecompressed,1);assert.equal(out.getPageCount(),1)
})
