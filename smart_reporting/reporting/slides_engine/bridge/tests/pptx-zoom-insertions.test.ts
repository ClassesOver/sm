import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { createBlankPptx, duplicateSlide, getElementLink, openPptx, savePptx } from '@genoffice/pptx-engine'

const directory = await mkdtemp('/dev/shm/pptx-zoom-insertions-')
const source = join(directory, 'source.pptx')
const output = join(directory, 'output.pptx')
const request = join(directory, 'request.json')
const original = await openPptx(await createBlankPptx())
duplicateSlide(original, 0)
const bytes = await savePptx(original)
await writeFile(source, bytes)
const sourceSlide = original.deck.slides[0]!
const targetSlide = original.deck.slides[1]!
const identity = (slide: typeof sourceSlide) => createHash('sha256').update(slide.path).update('\0').update(slide.originalXml).digest('hex')
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
const bridge = join(directory, 'edit.mjs')
const build = spawnSync('node_modules/.bin/esbuild', ['bridge/edit-pptx.ts', '--bundle', '--platform=node', '--format=esm', '--loader:.md=text', `--outfile=${bridge}`, '--log-level=error', '--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'], { encoding: 'utf8' })
assert.equal(build.status, 0, build.stderr)

test('Zoom stores a static picture link bound to target identity after slide reorder', async () => {
  await writeFile(request, JSON.stringify({
    action: 'edit', input: source, output, order: [1, 0],
    zoomInsertions: [{ slideIdentity: identity(sourceSlide), targetSlideIdentity: identity(targetSlide), bytesBase64: png, geometry: { x: 10, y: 20, width: 200, height: 100 }, mode: 'slide' }],
  }))
  const result = spawnSync(process.execPath, [bridge, request], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  const edited = await openPptx(await import('node:fs/promises').then(fs => fs.readFile(output)))
  const destination = edited.deck.slides[1]!
  const picture = destination.elements.find(element => element.type === 'picture')
  assert.ok(picture)
  assert.equal(picture.type, 'picture')
  assert.deepEqual(getElementLink(edited, 1, picture.id), { kind: 'slide', slideIndex: 0 })
})

test('Zoom rejects forged slide identity before writing output', async () => {
  await writeFile(request, JSON.stringify({
    action: 'edit', input: source, output,
    zoomInsertions: [{ slideIdentity: 'f'.repeat(64), targetSlideIdentity: identity(targetSlide), bytesBase64: png, geometry: { x: 0, y: 0, width: 10, height: 10 }, mode: 'section' }],
  }))
  const result = spawnSync(process.execPath, [bridge, request], { encoding: 'utf8' })
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /zoom_insertions_invalid/)
})

test('Zoom is inserted only on its identity-bound source, after duplicate creation', async () => {
  await writeFile(request, JSON.stringify({
    action: 'edit', input: source, output, newSlides: [{ duplicateOf: 0 }], order: [2, 1, 0],
    zoomInsertions: [{ slideIdentity: identity(sourceSlide), targetSlideIdentity: identity(targetSlide), bytesBase64: png, geometry: { x: 10, y: 20, width: 200, height: 100 }, mode: 'section' }],
  }))
  const result = spawnSync(process.execPath, [bridge, request], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  const edited = await openPptx(await import('node:fs/promises').then(fs => fs.readFile(output)))
  assert.equal(edited.deck.slides[0]!.elements.filter(element => element.type === 'picture').length, 0)
  const picture = edited.deck.slides[2]!.elements.find(element => element.type === 'picture')!
  assert.ok(picture)
  assert.deepEqual(getElementLink(edited, 2, picture.id), { kind: 'slide', slideIndex: 1 })
})
