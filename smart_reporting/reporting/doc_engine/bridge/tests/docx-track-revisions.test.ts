import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'

const bridge = resolve(import.meta.dirname, '../edit-docx.ts')
const run = (dir: string, request: unknown) => {
  const path = join(dir, 'request.json')
  writeFileSync(path, JSON.stringify(request))
  return execFileSync(process.execPath, ['--import', 'tsx', bridge, path], {
    encoding: 'utf8', cwd: resolve(import.meta.dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe'],
  })
}
const zip = (bytes: Uint8Array) => JSZip.loadAsync(bytes)

test('track revisions toggle is source-bound, reopens from settings and preserves every other ZIP part', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-track-revisions-'))
  try {
    const settings = '<?xml version="1.0" encoding="UTF-8"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:zoom w:percent="90"/><w:doNotTrackMoves/><w:defaultTabStop w:val="720"/></w:settings>'
    const source = await buildDocx({ bodyXml: '<w:p><w:r><w:t>原文</w:t></w:r></w:p>', extraParts: [{ path: 'word/settings.xml', xml: settings, contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml' }] })
    const input = join(dir, 'source.docx')
    writeFileSync(input, source)
    const originalModel = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.equal(originalModel.trackRevisions, false)

    const enabledPath = join(dir, 'enabled.docx')
    run(dir, { kind: 'patch', input, output: enabledPath, operations: [{ kind: 'setTrackRevisions', sourceSha256: originalModel.sourceSha256, enabled: true }] })
    const enabled = readFileSync(enabledPath)
    const before = await zip(source), afterEnable = await zip(enabled)
    for (const name of Object.keys(before.files)) {
      if (before.files[name]!.dir || name === 'word/settings.xml') continue
      assert.deepEqual(await before.file(name)!.async('uint8array'), await afterEnable.file(name)!.async('uint8array'), name)
    }
    const enabledSettings = await afterEnable.file('word/settings.xml')!.async('string')
    assert.match(enabledSettings, /<w:trackRevisions\/>/)
    assert.match(enabledSettings, /<w:zoom w:percent="90"\/><w:trackRevisions\/><w:doNotTrackMoves\/>/)
    const enabledModel = JSON.parse(run(dir, { kind: 'inspect', input: enabledPath }))
    assert.equal(enabledModel.trackRevisions, true)

    const disabledPath = join(dir, 'disabled.docx')
    run(dir, { kind: 'patch', input: enabledPath, output: disabledPath, operations: [{ kind: 'setTrackRevisions', sourceSha256: enabledModel.sourceSha256, enabled: false }] })
    const disabled = readFileSync(disabledPath), afterDisable = await zip(disabled)
    assert.doesNotMatch(await afterDisable.file('word/settings.xml')!.async('string'), /<w:trackRevisions\b/)
    const disabledModel = JSON.parse(run(dir, { kind: 'inspect', input: disabledPath }))
    assert.equal(disabledModel.trackRevisions, false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

test('track revisions rejects stale identities and leaves no output', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'docx-track-revisions-stale-'))
  try {
    const input = join(dir, 'source.docx'), output = join(dir, 'never.docx')
    writeFileSync(input, await buildDocx({ bodyXml: '<w:p><w:r><w:t>原文</w:t></w:r></w:p>' }))
    const model = JSON.parse(run(dir, { kind: 'inspect', input }))
    assert.throws(() => run(dir, { kind: 'patch', input, output, operations: [{ kind: 'setTrackRevisions', sourceSha256: '0'.repeat(64), enabled: true }] }), /track_revisions_anchor_invalid/)
    assert.equal(existsSync(output), false)
    assert.equal(model.trackRevisions, false)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
