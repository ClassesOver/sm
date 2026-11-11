import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveOutputFamily } from '../vendor/pdf2docx/src/rebuild/fontmap'

for (const [source, target] of [
  ['Chrom Sans OTF', 'Liberation Sans'],
  ['Chrom Serif OTF', 'Liberation Serif'],
  ['Chrom Fixed OTF', 'Liberation Mono'],
] as const) {
  test('PDFium ' + source + ' uses installed metric-compatible ' + target, () => {
    assert.equal(resolveOutputFamily(source, (family) => family === target), target)
  })
  test('installed ' + source + ' remains unchanged', () => {
    assert.equal(resolveOutputFamily(source, (family) => family === source), source)
  })
}

test('unknown and unavailable families retain their original name', () => {
  assert.equal(resolveOutputFamily('Unknown Embedded Family', () => false), 'Unknown Embedded Family')
  assert.equal(resolveOutputFamily('Chrom Fixed OTF', () => false), 'Chrom Fixed OTF')
})
