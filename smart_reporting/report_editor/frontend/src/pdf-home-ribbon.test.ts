import { expect, it } from 'vitest'
import { PDF_HOME_READ_ONLY_COMMANDS } from './pdf-home-ribbon'

it('keeps document properties as an enabled read-only source command', () => {
  expect(PDF_HOME_READ_ONLY_COMMANDS).toEqual([
    { id: 'genoffice.pdf.home.properties.documentProperties', label: '文档属性', enabled: true },
  ])
})
