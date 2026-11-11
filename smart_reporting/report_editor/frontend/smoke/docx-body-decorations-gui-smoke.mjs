// 独立入口；共享真实 Chromium/patch_docx/ZIP回读设施，不写静态构建。
process.env.DOCX_INSERT_CASE = process.env.DOCX_BODY_NOTES_UNAVAILABLE === '1' ? 'body-decorations-no-notes' : 'body-decorations'
await import('./docx-insert-gui-smoke.mjs')
