import { readFile, writeFile } from 'node:fs/promises'
import { z } from 'zod'
import { checkTextResources } from './text-operations'
import { inspectPdf, patchPdfWithReceipt } from './operations'
import { extractPagesBytes } from '../src/main/save-pdf'
import { createHash } from 'node:crypto'
import { inspectDesignWidgets, removeDesignWidgetWithReceipt } from './form-design'
import { protectPdf } from './protection'
import { convertPdfOffice } from './convert-office'
import {mergePdf} from './merge-pdf'
import {readExistingImageBackground,readExistingImagePixels} from './existing-image'
import {shrinkPdf} from './shrink'

const requestSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('textResources') }).strict(),
  z.object({ kind: z.literal('protect'), input: z.string().min(1), output: z.string().min(1), protection: z.unknown() }).strict(),
  z.object({ kind: z.literal('convertOffice'), input: z.string().min(1), output: z.string().min(1), format: z.enum(['pptx','docx','xlsx']), sourceSha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(),
  z.object({ kind: z.literal('inspect'), input: z.string().min(1), includeText: z.boolean().optional() }).strict(),
  z.object({kind:z.literal('imagePixels'),input:z.string().min(1),target:z.object({sourceSha256:z.string(),pageId:z.string(),imageId:z.string(),expectedImageSha256:z.string()}).strict()}).strict(),
  z.object({kind:z.literal('imageBackground'),input:z.string().min(1),target:z.object({sourceSha256:z.string(),pageId:z.string(),imageId:z.string(),expectedImageSha256:z.string(),clip:z.object({x:z.number().finite(),y:z.number().finite(),width:z.number().finite().positive(),height:z.number().finite().positive()}).strict(),pxWidth:z.number().int().min(1).max(2400)}).strict()}).strict(),
  z.object({ kind: z.literal('patch'), input: z.string().min(1), output: z.string().min(1), sourceSha256: z.string().regex(/^[a-f0-9]{64}$/), operations: z.array(z.unknown()).max(500) }).strict(),
  z.object({ kind: z.literal('extractPages'), input: z.string().min(1), output: z.string().min(1), pages: z.array(z.number().int().nonnegative()).min(1).max(10000) }).strict(),
  z.object({kind:z.literal('mergePdf'),input:z.string().min(1),output:z.string().min(1),others:z.array(z.string().min(1)).min(1)}).strict(),
  z.object({kind:z.literal('shrinkPdf'),input:z.string().min(1),output:z.string().min(1)}).strict(),
  z.object({ kind: z.literal('inspectDesignWidgets'), input: z.string().min(1) }).strict(),
  z.object({ kind: z.literal('removeDesignWidget'), input: z.string().min(1), output: z.string().min(1), sourceSha256: z.string().regex(/^[a-f0-9]{64}$/), target: z.object({fieldName:z.string().min(1).max(256),widgetId:z.string().regex(/^\d+R\d*$/),widgetIdentity:z.string().regex(/^[a-f0-9]{64}$/),expectedWidgetSha256:z.string().regex(/^[a-f0-9]{64}$/)}).strict() }).strict(),
])
try {
  const request = requestSchema.parse(JSON.parse(await readFile(process.argv[2]!, 'utf8')))
  if (request.kind === 'textResources') {
    console.log(JSON.stringify(await checkTextResources()))
    process.exit(0)
  }
  const source = new Uint8Array(await readFile(request.input))
  if (request.kind === 'inspect') {
    console.log(JSON.stringify(await inspectPdf(source, request.includeText)))
  } else if(request.kind==='imagePixels'){
    console.log(JSON.stringify(await readExistingImagePixels(source,request.target)))
  } else if(request.kind==='imageBackground'){
    console.log(JSON.stringify(await readExistingImageBackground(source,request.target)))
  } else if (request.kind === 'convertOffice') {
    if (request.input === request.output) throw new Error('转换输出不能覆盖来源文件')
    const {bytes,...receipt}=await convertPdfOffice(source,{format:request.format,sourceSha256:request.sourceSha256})
    await writeFile(request.output,bytes,{flag:'wx'})
    console.log(JSON.stringify(receipt))
  } else if (request.kind === 'protect') {
    if (request.input === request.output) throw new Error('PDF 输出不能覆盖来源文件')
    const {bytes,...receipt} = await protectPdf(source,request.protection)
    await writeFile(request.output,bytes,{flag:'wx'})
    console.log(JSON.stringify(receipt))
  } else if (request.kind === 'inspectDesignWidgets') {
    console.log(JSON.stringify(await inspectDesignWidgets(source)))
  } else if (request.kind === 'removeDesignWidget') {
    if (request.input === request.output) throw new Error('PDF 输出不能覆盖来源文件')
    const {bytes,...receipt} = await removeDesignWidgetWithReceipt(source, request.sourceSha256, request.target)
    await writeFile(request.output, bytes, {flag: 'wx'})
    console.log(JSON.stringify(receipt))
  } else if(request.kind==='mergePdf'){
    if([request.input,...request.others].includes(request.output))throw Error('PDF 输出不能覆盖来源文件')
    const others=await Promise.all(request.others.map(async path=>new Uint8Array(await readFile(path))))
    const {bytes,...receipt}=await mergePdf(source,others)
    await writeFile(request.output,bytes,{flag:'wx'})
    console.log(JSON.stringify(receipt))
  } else if(request.kind==='shrinkPdf'){
    if(request.input===request.output)throw Error('PDF 输出不能覆盖来源文件')
    const result=await shrinkPdf(source);await writeFile(request.output,result.bytes,{flag:'wx'})
    console.log(JSON.stringify({sourceSha256:createHash('sha256').update(source).digest('hex'),sha256:createHash('sha256').update(result.bytes).digest('hex'),size:result.bytes.length,streamsRecompressed:result.streamsRecompressed,imagesDownsampled:result.imagesDownsampled}))
  } else if (request.kind === 'extractPages') {
    if (request.input === request.output) throw new Error('PDF 输出不能覆盖来源文件')
    const content = await extractPagesBytes(source, request.pages)
    await writeFile(request.output, content, { flag: 'wx' })
    console.log(JSON.stringify({
      sourceSha256: createHash('sha256').update(source).digest('hex'),
      sha256: createHash('sha256').update(content).digest('hex'),
      size: content.length,
      pageCount: request.pages.length,
    }))
  } else {
    if (request.input === request.output) throw new Error('PDF 输出不能覆盖来源文件')
    const { bytes: content, ...receipt } = await patchPdfWithReceipt(source, request.operations, request.sourceSha256)
    await writeFile(request.output, content, { flag: 'wx' })
    console.log(JSON.stringify(receipt))
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
