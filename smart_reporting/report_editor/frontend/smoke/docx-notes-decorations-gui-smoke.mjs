// 既有/新notes引用段落的真实保存、草稿和ZIP回读独立入口。
process.env.DOCX_INSERT_CASE = process.env.DOCX_NOTES_DECORATIONS_FRESH === '1' ? 'notes-decorations-fresh' : 'notes-decorations'
await import('./docx-insert-gui-smoke.mjs')
