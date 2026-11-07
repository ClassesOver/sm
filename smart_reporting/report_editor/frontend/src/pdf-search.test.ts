import { expect, it } from 'vitest'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { buildSearchIndex, createSearchIndexCache, searchInIndex } from './genoffice-pdf-search'
import { foldCase } from './genoffice-find-text'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import source from './genoffice-pdf-search-source.json'
const doc = (pages: Record<string, unknown>[][]) => ({ numPages: pages.length, getPage: async (n: number) => ({ getTextContent: async () => ({ items: pages[n - 1] }) }) }) as unknown as PDFDocumentProxy
const run = (str: string, x = 0, hasEOL = false) => ({ str, transform: [1, 0, 0, 10, x, 20], width: str.length * 10, height: 10, hasEOL })
it('counts occurrences within one run and returns separate exact proportional boxes', async () => {
  const index = await buildSearchIndex(doc([[run('cat cat cat')]]))
  const rects = searchInIndex(index, 'cat').map(hit => hit.rects[0])
  expect(rects).toHaveLength(3)
  for (const [i, expected] of [[0, 20, 30, 30], [40, 20, 70, 30], [80, 20, 110, 30]].entries()) for (const [j, value] of expected.entries()) expect(rects[i][j]).toBeCloseTo(value)
})
it('finds across text items without inserting invented spaces and respects actual line breaks', async () => {
  const index = await buildSearchIndex(doc([[run('in', 0), run('voice', 20, true), run('due', 100)]]))
  expect(index[0].text).toBe('invoice\ndue')
  expect(searchInIndex(index, 'invoice')[0].rects).toHaveLength(2)
  expect(searchInIndex(index, 'voice due')).toEqual([])
})
it('keeps offsets stable for Turkish dotted I and supplementary characters', async () => {
  const text = 'İ𠀀 CAT cat'
  expect(foldCase(text).length).toBe(text.length)
  const index = await buildSearchIndex(doc([[run(text)]]))
  expect(searchInIndex(index, 'cat')).toHaveLength(2)
  expect(searchInIndex(index, 'cat', { matchCase: true })).toHaveLength(1)
  expect(searchInIndex(index, 'i')).toHaveLength(0)
})
it('applies Unicode whole-word boundaries while retaining source CJK substring semantics', async () => {
  const index = await buildSearchIndex(doc([[run('cat scatter cat_ 2cat cat. 中文测试中文')]]))
  expect(searchInIndex(index, 'cat')).toHaveLength(5)
  expect(searchInIndex(index, 'cat', { wholeWord: true })).toHaveLength(2)
  expect(searchInIndex(index, '中文', { wholeWord: true })).toHaveLength(2)
})
it('retains source non-overlap and global 1000-result cap', async () => {
  const index = await buildSearchIndex(doc([[run('aaa')], [run('x '.repeat(1500))]]))
  expect(searchInIndex(index, 'aa')).toHaveLength(1)
  expect(searchInIndex(index, 'x')).toHaveLength(1000)
})
it('indexes geometry-free text but does not fabricate a navigation box for it', async () => {
  const index = await buildSearchIndex(doc([[{ str: 'hidden' }, run(' visible')], []]))
  expect(index[0].text).toBe('hidden visible')
  expect(searchInIndex(index, 'hidden')).toHaveLength(0)
  expect(searchInIndex(index, 'visible')).toHaveLength(1)
  expect(searchInIndex(index, '')).toEqual([])
})
it('shares one extraction per document and rebuilds for a different actual preview or clear', async () => {
  let extractions = 0
  const original = { numPages: 1, getPage: async () => { extractions++; return { getTextContent: async () => ({ items: [run('original')] }) } } } as unknown as PDFDocumentProxy
  const cache = createSearchIndexCache(), a = cache.get(original)
  expect(cache.get(original)).toBe(a); await a; expect(extractions).toBe(1)
  expect(searchInIndex(await cache.get(doc([[run('changed')]])), 'changed')).toHaveLength(1)
  cache.clear(); await cache.get(original); expect(extractions).toBe(2)
})
it('preserves both pinned source manifests and local adaptation identities', () => {
  for (const file of source.files) expect(createHash('sha256').update(readFileSync(`${process.cwd()}/src/${file.localPath}`)).digest('hex')).toBe(file.localSha256)
})
