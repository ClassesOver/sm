import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { parseDocx } from '../../packages/docx-engine/src/index.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const run = (dir: string, request: unknown) => {
  const path = join(dir, 'request.json'); writeFileSync(path, JSON.stringify(request))
  return JSON.parse(execFileSync(process.execPath, ['--import', 'tsx', bridge, path], { cwd: resolve(import.meta.dirname, '../..'), encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }))
}
const levels = Array.from({ length: 9 }, (_, i) => ({ numFmt: 'decimal', lvlText: Array.from({ length: i + 1 }, (_, k) => `%${k + 1}`).join('.') + '.', indentLeft: 720 * (i + 1), hanging: 360, start: i === 1 ? 3 : 1, ...(i ? { lvlRestart: i } : {}) }))

test('真实桥分配同一编号定义，写九级与重启规则，保留原正文和非目标部件', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-custom-list-'))
  try {
    const source = await buildDocx({ bodyXml: '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>甲</w:t></w:r></w:p><w:p><w:r><w:t>乙</w:t></w:r></w:p><w:p><w:r><w:t>不变正文</w:t></w:r></w:p>' })
    const input = join(dir, 'source.docx'), output = join(dir, 'edited.docx'); writeFileSync(input, source)
    const model = run(dir, { kind: 'inspect', input })
    const operations = model.blocks.slice(0, 2).map((b: any, i: number) => ({ kind: 'setParagraphCustomList', blockId: b.blockId, expectedObjectSha256: b.expectedObjectSha256, definitionId: 'legal', levels, ilvl: i }))
    run(dir, { kind: 'patch', input, output, operations })
    const parsed = await parseDocx(readFileSync(output)), [first, second, untouched] = parsed.blocks
    assert.equal(first!.list!.numId, second!.list!.numId); assert.equal(second!.list!.ilvl, 1)
    assert.equal(first!.runs![0]!.bold, true); assert.equal(first!.format!.align, 'center'); assert.equal(untouched!.runs!.map(run => run.text).join(''), '不变正文')
    const definition = parsed.numbering.get(first!.list!.numId)!
    assert.equal(Object.keys(definition.levels).length, 9); assert.equal(definition.levels[1]!.start, 3); assert.equal(definition.levels[1]!.lvlRestart, 1)
    const a = await JSZip.loadAsync(source), b = await JSZip.loadAsync(readFileSync(output))
    for (const name of Object.keys(a.files)) if (!a.files[name]!.dir && !['word/document.xml', 'word/numbering.xml', '[Content_Types].xml', 'word/_rels/document.xml.rels'].includes(name)) assert.deepEqual(await b.file(name)!.async('uint8array'), await a.file(name)!.async('uint8array'), name)
    const invalid = join(dir, 'invalid.docx')
    assert.throws(() => run(dir, { kind: 'patch', input, output: invalid, operations: [{ ...operations[0], levels: [{ ...levels[0], lvlRestart: 2 }] }] }))
    assert.equal(existsSync(invalid), false); assert.deepEqual(readFileSync(input), Buffer.from(source))
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('源多级定义关联既有和缺失标题样式，追加编号不改旧定义，并支持重开后混合级别', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-custom-linked-'))
  try {
    const source = await buildDocx({ withNumbering: true, bodyXml: '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>原有标题</w:t></w:r></w:p><w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="2"/></w:numPr></w:pPr><w:r><w:t>旧列表</w:t></w:r></w:p>' })
    const input = join(dir, 'source.docx'), output = join(dir, 'edited.docx'); writeFileSync(input, source)
    const model = run(dir, { kind: 'inspect', input }), block = model.blocks[0]
    const linked = levels.map((level, i) => ({ ...level, ...(i === 1 ? { numFmt: 'bullet', lvlText: '•' } : {}), pStyle: `Heading${i + 1}` }))
    const op = { kind: 'setParagraphCustomList', blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, definitionId: 'linked', levels: linked, ilvl: 0 }
    run(dir, { kind: 'patch', input, output, operations: [op] })
    const parsed = await parseDocx(readFileSync(output)), numId = parsed.blocks[0]!.list!.numId
    assert.notEqual(numId, '2')
    const a = await JSZip.loadAsync(source), b = await JSZip.loadAsync(readFileSync(output))
    const before = await a.file('word/numbering.xml')!.async('string'), after = await b.file('word/numbering.xml')!.async('string')
    for (const child of before.matchAll(/<w:(?:abstractNum|num)\b[^>]*>[\s\S]*?<\/w:(?:abstractNum|num)>/g)) assert.ok(after.includes(child[0]))
    const styles = await b.file('word/styles.xml')!.async('string')
    assert.match(styles, /<w:style[^>]*w:styleId="Heading9"/)
    assert.ok(styles.includes('<w:b/>')); assert.ok(styles.includes('<w:sz w:val="32"/>'))
    assert.deepEqual(parsed.styles.get('Heading1')!.numPr, { numId, ilvl: 0 })
    assert.deepEqual(parsed.styles.get('Heading9')!.numPr, { numId, ilvl: 8 })
    const reopened = run(dir, { kind: 'inspect', input: output }), target = reopened.blocks[0]
    const next = join(dir, 'mixed.docx')
    run(dir, { kind: 'patch', input: output, output: next, operations: [{ kind: 'setParagraphListLevel', blockId: target.blockId, expectedObjectSha256: target.expectedObjectSha256, ilvl: 1, listKind: 'bullet' }] })
    assert.equal((await parseDocx(readFileSync(next))).blocks[0]!.list!.kind, 'bullet')
    const conflict = join(dir, 'conflict.docx')
    assert.throws(() => run(dir, { kind: 'patch', input, output: conflict, operations: [op, { ...op, levels: [{ ...linked[0], start: 99 }] }] }))
    assert.equal(existsSync(conflict), false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
