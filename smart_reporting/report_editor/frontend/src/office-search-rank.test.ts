import { expect, it } from 'vitest'
import { bm25Score, mergeSearchCorpus } from './office-search-rank'

it('merges a full corpus across pages and scores rarer terms and shorter documents higher', () => {
  const total = { documents: 0, totalLength: 0, documentFrequencies: [] as number[] }
  mergeSearchCorpus(total, { documents: 6, totalLength: 240, documentFrequencies: [4, 0] })
  mergeSearchCorpus(total, { documents: 4, totalLength: 160, documentFrequencies: [0, 1] })
  expect(total).toEqual({ documents: 10, totalLength: 400, documentFrequencies: [4, 1] })
  expect(bm25Score(40, [0, 1], total)).toBeGreaterThan(bm25Score(40, [1, 0], total))
  expect(bm25Score(20, [0, 1], total)).toBeGreaterThan(bm25Score(50, [0, 1], total))
})
