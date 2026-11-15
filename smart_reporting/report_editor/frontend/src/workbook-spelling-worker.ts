import { workbookSpellEngine } from './workbook-spell-engine'
import { runSheetSpellCheck, type SpellCellRef, type SpellEngine } from './vendor/genoffice-sheets-spelling/spell-check'
import affixes from '../node_modules/dictionary-en/index.aff?url'
import words from '../node_modules/dictionary-en/index.dic?url'

interface SpellRequest {
  run: number
  cells: SpellCellRef[]
  learned: string[]
  ignored: string[]
}

let engine: Promise<SpellEngine> | undefined
async function dictionaryText(url: string) {
  const response = await fetch(url)
  if (!response.ok) throw new Error('拼写词典加载失败')
  return response.text()
}

self.onmessage = async (event: MessageEvent<SpellRequest>) => {
  const { run, cells, learned, ignored } = event.data
  try {
    engine ??= Promise.all([dictionaryText(affixes), dictionaryText(words)])
      .then(([affixRules, dictionary]) => workbookSpellEngine(affixRules, dictionary))
    const findings = runSheetSpellCheck(cells, await engine, new Set(learned), new Set(ignored))
    self.postMessage({ run, findings })
  } catch {
    engine = undefined
    self.postMessage({ run, failed: true })
  }
}
