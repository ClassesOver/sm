import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { createBlankPptx, openPptx, savePptx, listMasterParts, parseMasterPart, addElement, patchSlideXml, elementSpid } from '@genoffice/pptx-engine'
import { runTxn } from '../../packages/pptx-ops/src/index.ts'

async function fixture() {
  const opened = await openPptx(await createBlankPptx())
  const parts = listMasterParts(opened.archive)
  for (const part of parts) {
    const slide = parseMasterPart(opened.archive, part.partPath)!
    addElement(slide, { kind: 'textbox', offset: { x: 400000, y: part.kind === 'master' ? 100000 : 800000, cx: 5000000, cy: 500000 }, paragraphs: [{ runs: [{ text: `${part.kind}文字`, fontSize: 24 }] }] })
    opened.archive.entries.set(part.partPath, Buffer.from(patchSlideXml(slide)))
  }
  return openPptx(await savePptx(opened))
}
async function bridge(input: Uint8Array, patch?: object) {
  const dir = await mkdtemp('/dev/shm/pptx-master-test-'), source = join(dir, 'source.pptx'), output = join(dir, 'output.pptx'), request = join(dir, 'request.json')
  await writeFile(source, input); await writeFile(request, JSON.stringify({ action: patch ? 'edit' : 'inspect', input: source, output, ...patch }))
  const executable = join(dir, 'edit-pptx.mjs')
  const built = spawnSync('node_modules/.bin/esbuild', ['bridge/edit-pptx.ts', '--bundle', '--platform=node', '--format=esm', '--loader:.md=text', `--outfile=${executable}`, '--log-level=error', '--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'], { cwd: process.cwd(), encoding: 'utf8' }); assert.equal(built.status, 0, built.stderr)
  const result = spawnSync(process.execPath, [executable, request], { cwd: process.cwd(), encoding: 'utf8' })
  return { result, output, model: result.status === 0 ? JSON.parse(result.stdout) : undefined }
}
test('inspect列出真实母版和版式文字身份，实际bridge保存与固定源part setText事务等价', async () => {
  const opened = await fixture(), bytes = await savePptx(opened), inspected = await bridge(bytes)
  assert.equal(inspected.result.status, 0, inspected.result.stderr)
  assert.equal(inspected.model.masterTextParts.length, listMasterParts(opened.archive).length)
  const records = inspected.model.masterTextParts.map((part: any) => ({ partPath: part.partPath, spid: part.elements.at(-1).spid, text: `${part.kind}改后 <&> 😀\n第二段` }))
  assert.ok(records.every((item: any) => item.spid > 0))
  const output = await bridge(bytes, { masterTextEdits: records }); assert.equal(output.result.status, 0, output.result.stderr)
  const actual = await openPptx(await readFile(output.output)), expected = await openPptx(bytes)
  for (const item of records) {
    const slide = parseMasterPart(expected.archive, item.partPath)!, element = slide.elements.find(el => elementSpid(el) === item.spid)!
    assert.equal(runTxn(expected, { ops: [{ op: 'setText', target: { part: item.partPath, el: `e_${item.spid}` }, paragraphs: item.text.split('\n').map((text: string) => ({ runs: [{ text }] })) }] }).applied, true)
  }
  const targets = new Set(records.map((r: any) => r.partPath))
  for (const [path, bytes] of opened.archive.entries) {
    if (!targets.has(path)) assert.deepEqual(actual.archive.readBytes(path), bytes, path)
    else {
      // 源事务会生成creationId；比较重新解析的真实文字及非文字属性，不依赖随机GUID。
      const a = parseMasterPart(actual.archive, path)!, e = parseMasterPart(expected.archive, path)!
      assert.deepEqual(a.elements.map(el => 'text' in el ? el.text?.paragraphs : null), e.elements.map(el => 'text' in el ? el.text?.paragraphs : null))
    }
  }
})
test('强制伪造part、SPID、重复身份与超预算都拒绝且没有输出文件', async () => {
  const opened = await fixture(), bytes = await savePptx(opened), part = listMasterParts(opened.archive)[0]!, slide = parseMasterPart(opened.archive, part.partPath)!, spid = elementSpid(slide.elements.at(-1)!)!
  for (const edits of [[{ partPath: 'ppt/slides/slide1.xml', spid, text: '错误' }], [{ partPath: part.partPath, spid: 99999, text: '错误' }], Array(2).fill({ partPath: part.partPath, spid, text: '错误' })]) {
    const result = await bridge(bytes, { masterTextEdits: edits }); assert.notEqual(result.result.status, 0)
    await assert.rejects(readFile(result.output))
  }
})
test('混合run、超链接与动态字段按源setText纯文字规则处理，不额外拒绝或另造格式语义', async () => {
  const opened = await fixture(), path = listMasterParts(opened.archive)[0]!.partPath, part = parseMasterPart(opened.archive, path)!
  for (const runs of [
    [{ text: '标签', bold: true }, { text: '长正文保持这个样式', italic: true }],
    [{ text: '来源链接', hyperlinkRId: 'rId999' }],
    [{ text: '1', field: 'slidenum' as const }],
  ]) addElement(part, { kind: 'textbox', offset: { x: 10, y: 10, cx: 2000000, cy: 500000 }, paragraphs: [{ runs }] })
  opened.archive.entries.set(path, Buffer.from(patchSlideXml(part)))
  const bytes = await savePptx(opened), inspected = await bridge(bytes), target = inspected.model.masterTextParts.find((p: any) => p.partPath === path)
  const edits = target.elements.slice(-3).map((el: any) => { assert.equal(el.editable, true); return { partPath: path, spid: el.spid, text: '新正文 <&> 😀' } })
  const output = await bridge(bytes, { masterTextEdits: edits }); assert.equal(output.result.status, 0, output.result.stderr)
  const expected = await openPptx(bytes), result = runTxn(expected, { ops: edits.map((item: any) => ({ op: 'setText', target: { part: path, el: `e_${item.spid}` }, paragraphs: [{ runs: [{ text: item.text }] }] })) }); assert.equal(result.applied, true)
  const actual = await openPptx(await readFile(output.output)), a = parseMasterPart(actual.archive, path)!, e = parseMasterPart(expected.archive, path)!
  assert.deepEqual(a.elements.map(el => 'text' in el ? el.text?.paragraphs : null), e.elements.map(el => 'text' in el ? el.text?.paragraphs : null))
  const direct = join(await mkdtemp('/dev/shm/pptx-master-tsx-'), 'request.json'), directOutput = direct + '.pptx'
  // 未安装dist的既有tsx回退同样可执行源?raw依赖，不能只让bundled路径可用。
  const source = join(await mkdtemp('/dev/shm/pptx-master-tsx-input-'), 'source.pptx'); await writeFile(source, bytes)
  await writeFile(direct, JSON.stringify({ action: 'edit', input: source, output: directOutput, masterTextEdits: edits }))
  const native = spawnSync(process.execPath, ['--import', 'tsx', 'bridge/edit-pptx.ts', direct], { cwd: process.cwd(), encoding: 'utf8' }); assert.equal(native.status, 0, native.stderr)
})
