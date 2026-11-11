// Reuse the real native grant, CSRF, signed download and immutable asset checks.
process.env.PDF_OFFICE_GEOMETRY_SMOKE_FORMAT='xlsx'
process.env.PDF_PPTX_TEXT_GEOMETRY_SMOKE_DIRECTORY??='/tmp/pdf-xlsx-text-decoration-browser-20261111'
await import('./pdf-pptx-text-geometry-smoke.mjs')
