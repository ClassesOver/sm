import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { createBlankPptx, openPptx, savePptx } from '@genoffice/pptx-engine'

const directory = await mkdtemp('/dev/shm/pptx-slide-identity-')
const source = join(directory, 'source.pptx')
const bytes = await createBlankPptx()
await writeFile(source, bytes)
const opened = await openPptx(bytes)
const slide = opened.deck.slides[0]!
const expected = createHash('sha256').update(slide.path).update('\0').update(slide.originalXml).digest('hex')

function build(entry: string, out: string) {
  const result = spawnSync('node_modules/.bin/esbuild', [entry, '--bundle', '--platform=node', '--format=esm', '--loader:.md=text', `--outfile=${out}`, '--log-level=error', '--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
}

test('inspect and render return the same server-recomputable source slide identity', async () => {
  const edit = join(directory, 'edit.mjs'), render = join(directory, 'render.mjs'), request = join(directory, 'request.json')
  build('bridge/edit-pptx.ts', edit)
  build('bridge/render-pptx.ts', render)
  await writeFile(request, JSON.stringify({ action: 'inspect', input: source }))
  const inspected = spawnSync(process.execPath, [edit, request], { encoding: 'utf8' })
  assert.equal(inspected.status, 0, inspected.stderr)
  const model = JSON.parse(inspected.stdout)
  assert.equal(model.slides[0].slideIdentity, expected)

  await writeFile(request, JSON.stringify({ input: source }))
  const rendered = spawnSync(process.execPath, [render, request], { encoding: 'utf8' })
  assert.equal(rendered.status, 0, rendered.stderr)
  assert.equal(JSON.parse(rendered.stdout).slides[0].slideIdentity, expected)
  assert.match(expected, /^[0-9a-f]{64}$/)
  assert.deepEqual(await readFile(source), Buffer.from(bytes))
})
