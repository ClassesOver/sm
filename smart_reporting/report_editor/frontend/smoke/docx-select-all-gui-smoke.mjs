// 源Home全选：只选择，不写入草稿；两个独立运行覆盖可编辑和只读。
process.env.DOCX_INSERT_CASE = process.env.DOCX_SELECT_READONLY === '1' ? 'select-all-readonly' : 'select-all'
await import('./docx-insert-gui-smoke.mjs')
