import { readFile, writeFile } from 'node:fs/promises'
import { z } from 'zod'
import { checkTextResources } from './text-operations'
import { inspectPdf, patchPdfWithReceipt } from './operations'

const requestSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('textResources') }).strict(),
  z.object({ kind: z.literal('inspect'), input: z.string().min(1), includeText: z.boolean().optional() }).strict(),
  z.object({ kind: z.literal('patch'), input: z.string().min(1), output: z.string().min(1), sourceSha256: z.string().regex(/^[a-f0-9]{64}$/), operations: z.array(z.unknown()).max(500) }).strict(),
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
