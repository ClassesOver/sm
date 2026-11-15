import nspell from 'nspell'
import type { SpellEngine } from './vendor/genoffice-sheets-spelling/spell-check'

export function workbookSpellEngine(affixes: string, words: string): SpellEngine {
  const dictionary = nspell(affixes, words)
  return {
    isWordMisspelled: word => !dictionary.correct(word),
    getWordSuggestions: word => dictionary.suggest(word),
  }
}
