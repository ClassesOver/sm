// 同段正文/notes、四类布局与双装饰的真实组合保存。
process.env.DOCX_INSERT_CASE = process.env.DOCX_LAYOUT_DECORATIONS_FRESH === '1' ? 'layout-decorations-fresh' : 'layout-decorations'
await import('./docx-insert-gui-smoke.mjs')
