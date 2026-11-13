import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { validatePageBorderValues, PAGE_BORDER_ART_NAMES, PAGE_BORDER_LINE_STYLES } from '../docx-page-borders.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const body = '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" w:header="851" w:footer="992" w:gutter="0"/></w:sectPr></w:pPr><w:r><w:t>第一节正文</w:t></w:r></w:p><w:p><w:r><w:t>第二节正文</w:t></w:r></w:p>'
function run(dir: string, request: unknown) {
  const requestPath = join(dir, 'request.json'); writeFileSync(requestPath, JSON.stringify(request))
  return execFileSync(process.execPath, ['--import', 'tsx', bridge, requestPath], { encoding: 'utf8', cwd: resolve(import.meta.dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe'] })
}
const documentXml = async (bytes: Uint8Array) => (await JSZip.loadAsync(bytes)).file('word/document.xml')!.async('string')
const side = (val: string, widthPt: number, spacePt: number, extra: Record<string, unknown> = {}) => ({ val, widthPt, spacePt, ...extra })
const custom = { display: 'firstPage', offsetFrom: 'text', spacePt: 4, widthPt: 1.5, color: 'C00000',
  sides: { top: side('double', 1.5, 4, { color: 'C00000' }), bottom: side('double', 1.5, 4, { color: 'C00000' }) } }
const layout = (section: { sectionId: string; expectedSectionSha256: string }, values: unknown) => ({ kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values })

test('preset lists match the pinned PageBorderDialog (24 line styles, 170 art borders)', () => {
  assert.equal(PAGE_BORDER_LINE_STYLES.length, 24); assert.equal(PAGE_BORDER_LINE_STYLES[0], 'single')
  assert.equal(PAGE_BORDER_ART_NAMES.length, 170); assert.equal(PAGE_BORDER_ART_NAMES[0], 'apples')
})

test('per-section box, custom, art and removal through the pinned applySectionSettings with read-back', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-page-borders-'))
  try {
    const input = join(dir, 'source.docx'), source = await buildDocx({ bodyXml: body }); writeFileSync(input, source)
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.equal(model.sections.length, 2)
    assert.deepEqual(model.sections.map((section: { settings: { pageBorder: boolean } }) => section.settings.pageBorder), [false, false])
    const set = join(dir, 'set.docx')
    run(dir, { kind: 'patch', input, output: set, operations: [
      layout(model.sections[0], { pageBorder: true, pageBorderProps: custom }),
      layout(model.sections[1], { pageBorder: true, pageBorderProps: null }),
    ] })
    const xml = await documentXml(readFileSync(set))
    assert.match(xml, /<w:pgBorders w:display="firstPage" w:offsetFrom="text"><w:top w:val="double" w:sz="12" w:space="4" w:color="C00000"\/><w:bottom w:val="double" w:sz="12" w:space="4" w:color="C00000"\/><\/w:pgBorders>/)
    assert.match(xml, /<w:pgBorders w:offsetFrom="page"><w:top w:val="single" w:sz="4" w:space="24" w:color="auto"\/><w:left [^>]*\/><w:bottom [^>]*\/><w:right [^>]*\/><\/w:pgBorders>/)
    assert.match(xml, /第一节正文/); assert.match(xml, /第二节正文/)
    const reopened = JSON.parse(run(dir, { kind: 'inspect', input: set }))
    assert.deepEqual(reopened.sections.map((section: { settings: { pageBorder: boolean } }) => section.settings.pageBorder), [true, true])
    assert.equal(reopened.sections[0].settings.pageBorderProps.display, 'firstPage')
    assert.deepEqual(Object.keys(reopened.sections[0].settings.pageBorderProps.sides).sort(), ['bottom', 'top'])
    // 艺术型（整篇）+ 删除
    const art = { offsetFrom: 'page', spacePt: 24, widthPt: 20, sides: Object.fromEntries(['top', 'left', 'bottom', 'right'].map(name => [name, side('apples', 20, 24, { art: true })])) }
    const arted = join(dir, 'art.docx')
    run(dir, { kind: 'patch', input: set, output: arted, operations: reopened.sections.map((section: never) => layout(section, { pageBorder: true, pageBorderProps: art })) })
    assert.equal(((await documentXml(readFileSync(arted))).match(/<w:top w:val="apples" w:sz="20" w:space="24" w:color="auto"\/>/g) ?? []).length, 2)
    const artModel = JSON.parse(run(dir, { kind: 'inspect', input: arted }))
    const removed = join(dir, 'removed.docx')
    run(dir, { kind: 'patch', input: arted, output: removed, operations: artModel.sections.map((section: never) => layout(section, { pageBorder: false })) })
    assert.doesNotMatch(await documentXml(readFileSync(removed)), /<w:pgBorders/)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('invalid border values, stale anchors and section-break batches are refused without output', async () => {
  const ok = { pageBorder: true, pageBorderProps: custom }
  validatePageBorderValues(ok); validatePageBorderValues({ pageBorder: false }); validatePageBorderValues({ pageBorder: true, pageBorderProps: null })
  const bad: unknown[] = [
    { pageBorder: 'yes' }, { pageBorderProps: custom }, { pageBorder: false, pageBorderProps: custom },
    { pageBorder: true, pageBorderProps: { ...custom, extra: 1 } }, { pageBorder: true, pageBorderProps: { ...custom, display: 'everyPage' } },
    { pageBorder: true, pageBorderProps: { ...custom, offsetFrom: 'edge' } }, { pageBorder: true, pageBorderProps: { ...custom, spacePt: 5 } },
    { pageBorder: true, pageBorderProps: { ...custom, sides: {} } }, { pageBorder: true, pageBorderProps: { ...custom, sides: { top: side('laser', 1.5, 4) } } },
    { pageBorder: true, pageBorderProps: { ...custom, sides: { top: side('double', 1.2, 4) } } }, { pageBorder: true, pageBorderProps: { ...custom, sides: { top: side('double', 1.5, 40) } } },
    { pageBorder: true, pageBorderProps: { ...custom, widthPt: 20, spacePt: 4, sides: { top: side('apples', 20, 4, { art: true, color: 'FF0000' }) } } },
    { pageBorder: true, pageBorderProps: { ...custom, widthPt: 40, spacePt: 4, sides: { top: side('apples', 40, 4, { art: true }) } } },
    { pageBorder: true, pageBorderProps: { ...custom, color: 'c00000' } },
    { pageBorder: true, pageBorderProps: { ...custom, sides: { top: side('double', 1.5, 4, { shadow: true, frame: true }) } } },
  ]
  for (const values of bad) assert.throws(() => validatePageBorderValues(values as never), JSON.stringify(values))
  const dir = mkdtempSync(join(tmpdir(), 'docx-page-borders-reject-'))
  try {
    const input = join(dir, 'source.docx'); writeFileSync(input, await buildDocx({ bodyXml: body }))
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    const out = join(dir, 'out.docx')
    for (const operations of [
      [layout(model.sections[0], bad[5])],
      [layout({ ...model.sections[0], expectedSectionSha256: 'f'.repeat(64) }, ok)],
      [layout(model.sections[1], ok), { kind: 'insertSectionBreak', blockId: model.blocks[1].blockId, expectedObjectSha256: model.blocks[1].expectedObjectSha256, type: 'nextPage' }],
    ]) {
      assert.throws(() => run(dir, { kind: 'patch', input, output: out, operations }))
      assert.equal(existsSync(out), false)
    }
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
