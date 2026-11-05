// Browser-only type subset extracted from upstream metrics.ts.
export interface FaceVerticalMetrics {
  unitsPerEm: number
  hheaAscender: number
  hheaDescender: number
  hheaLineGap: number
  typoAscender: number | null
  typoDescender: number | null
  typoLineGap: number | null
  winAscent: number | null
  winDescent: number | null
  /** OS/2 fsSelection bit 7 (USE_TYPO_METRICS) */
  useTypoMetrics: boolean
  xAvgCharWidth: number | null
  /** OS/2 ulCodePageRange1; bits 17-21 flag the East Asian code pages */
  codePageRange1: number | null
}

