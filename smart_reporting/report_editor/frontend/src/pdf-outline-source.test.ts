// @vitest-environment node
import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {expect,it} from 'vitest'
import {getDocument} from 'pdfjs-dist/legacy/build/pdf.mjs'
import {resolvePdfOutline} from './pdf-view-ribbon'

it('reads external and internal bookmark actions from an actual PDF using PDF.js', async () => {
  const python=fileURLToPath(new URL('../../../../.venv/bin/python',import.meta.url))
  const fixture=fileURLToPath(new URL('../smoke/pdf-outline-links-source.py',import.meta.url))
  const source=JSON.parse(execFileSync(python,[fixture],{encoding:'utf8'}))
  const loading=getDocument({data:new Uint8Array(Buffer.from(source.bytes,'base64'))})
  try {
    const pdf=await loading.promise
    expect(pdf.numPages).toBe(2)
    const raw=await pdf.getOutline()
    expect(raw?.[0].items[0].url).toBe('https://example.com/report')
    expect(await resolvePdfOutline(raw??[],pdf)).toEqual([
      {title:'First page',depth:0,pageIndex:0},
      {title:'Website',depth:1,url:'https://example.com/report'},
      {title:'Contact',depth:1,url:'mailto:review@example.com'},
      {title:'HTTP',depth:0,url:'http://example.com/help'},
      {title:'Second page',depth:0,pageIndex:1},
    ])
  } finally {await loading.destroy()}
})
