export type SearchCorpus = { documents: number; totalLength: number; documentFrequencies: number[] }

export function mergeSearchCorpus(total: SearchCorpus, page: SearchCorpus) {
  total.documents += page.documents
  total.totalLength += page.totalLength
  page.documentFrequencies.forEach((count, index) => {
    total.documentFrequencies[index] = (total.documentFrequencies[index] ?? 0) + count
  })
}

export function bm25Score(length: number, frequencies: number[], corpus: SearchCorpus) {
  const averageLength = corpus.totalLength / corpus.documents || 1
  const normalization = 1.2 * (0.25 + 0.75 * length / averageLength)
  return frequencies.reduce((score, frequency, index) => {
    if (!frequency) return score
    const documentsWithTerm = corpus.documentFrequencies[index] ?? 0
    const idf = Math.max(0.000001,
      Math.log((corpus.documents - documentsWithTerm + 0.5) / (documentsWithTerm + 0.5)))
    return score + idf * 2.2 * frequency / (frequency + normalization)
  }, 0)
}
