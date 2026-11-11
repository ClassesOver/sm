// DOCX_INSERT_CASE可选hf-insert[-delete|-edge-title|-edge-even|-edge-multi]。
process.env.DOCX_INSERT_CASE ??= 'hf-insert'
await import('./docx-insert-gui-smoke.mjs')
